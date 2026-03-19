"""Cross-platform arbitrage monitor: Polymarket ↔ Kalshi.

Scans for price discrepancies between Polymarket and Kalshi on matched markets
and executes both legs concurrently to lock in the spread.

Every cycle:
1. Check settlements for both platforms
2. Scan for cross-platform opportunities
3. Re-verify edge with fresh quotes
4. Submit both legs concurrently (asyncio.gather)
5. Record arb pair for P&L tracking
"""

from __future__ import annotations

import asyncio
import json

from trading_bot.models import (
    OrderRequest,
    OrderType,
    Platform,
    Side,
    WSEvent,
    WSEventType,
)
from trading_bot.monitors.adaptation import StrategyAdaptation
from trading_bot.monitors.base import BaseMonitor
from trading_bot.strategies.cross_platform_arb import CrossPlatformArbScanner
from trading_bot.utils.logging import log


class CrossPlatformArbMonitor(BaseMonitor):
    """Polymarket ↔ Kalshi cross-platform arbitrage monitor."""

    monitor_type = "cross_platform_arb"

    def get_interval_seconds(self) -> int:
        return self.config.cross_platform_arb.scan_interval_minutes * 60

    async def run_cycle(self) -> None:
        poly_broker = self.brokers.get("polymarket")
        kalshi_broker = self.brokers.get("kalshi")

        if not poly_broker or not kalshi_broker:
            log.warning(
                "CrossPlatformArbMonitor: need both polymarket and kalshi brokers — skipping"
            )
            return

        if not self.config.cross_platform_arb.enabled:
            return

        # 1. Settlement checks for both platforms
        await self._check_polymarket_settlements(poly_broker)
        await self._check_kalshi_settlements(kalshi_broker)

        # 2. Scan for opportunities
        scanner = CrossPlatformArbScanner(self.config.cross_platform_arb)
        result = await scanner.scan(poly_broker, kalshi_broker)

        opportunities = result.metadata.get("opportunities", [])

        if opportunities:
            await self.event_bus.broadcast(WSEvent(
                type=WSEventType.STRATEGY_SIGNAL,
                data={
                    "strategy": "cross_platform_arb",
                    "opportunities_found": result.metadata.get("opportunities_found", 0),
                    "pairs_matched": result.metadata.get("pairs_matched", 0),
                    "source": f"monitor:{self.monitor_id}",
                    "opportunities": opportunities[:5],
                },
            ))

        # 3. Pair decisions back into (poly_decision, kalshi_decision) tuples
        decisions = result.decisions
        # Decisions come in pairs: [poly_leg, kalshi_leg, poly_leg, kalshi_leg, ...]
        poly_portfolio = await poly_broker.get_account()
        kalshi_portfolio = await kalshi_broker.get_account()

        i = 0
        while i + 1 < len(decisions):
            poly_dec = decisions[i]
            kalshi_dec = decisions[i + 1]
            i += 2

            if not poly_dec.reasoning.startswith("[XPLAT|poly|"):
                continue
            if not kalshi_dec.reasoning.startswith("[XPLAT|kalshi|"):
                continue

            await self._execute_cross_platform_arb(
                poly_dec, kalshi_dec, poly_broker, kalshi_broker,
                poly_portfolio, kalshi_portfolio,
            )

        # 4. Strategy adaptation
        adaptation = StrategyAdaptation(self.config.monitors, self.repo)
        await adaptation.evaluate_and_adapt(self.monitor_id)

    async def _execute_cross_platform_arb(
        self, poly_dec, kalshi_dec, poly_broker, kalshi_broker,
        poly_portfolio, kalshi_portfolio,
    ) -> None:
        """Execute one cross-platform arb pair (Polymarket + Kalshi legs) concurrently."""
        cfg = self.config.cross_platform_arb

        # Parse routing tag to get execution parameters
        # Tag format: [XPLAT|poly|{direction}|kalshi={ticker}]
        #             [XPLAT|kalshi|{direction}|poly={token_id}|kprice={price}]
        try:
            kalshi_price = _parse_kalshi_price(kalshi_dec.reasoning)
        except Exception:
            kalshi_price = None

        # Get fresh Polymarket price
        try:
            poly_fresh_price = await poly_broker.get_quote(poly_dec.symbol)
        except Exception as e:
            log.warning(f"CrossPlatformArb: failed Poly quote for {poly_dec.symbol}: {e}")
            return

        # Get fresh Kalshi price
        try:
            kalshi_fresh_price = await kalshi_broker.get_quote(kalshi_dec.symbol)
            # If buying NO on Kalshi (selling YES), use complement
            if kalshi_dec.side == Side.SELL:
                kalshi_buy_price = 1.0 - kalshi_fresh_price  # price of NO
            else:
                kalshi_buy_price = kalshi_fresh_price
        except Exception as e:
            log.warning(f"CrossPlatformArb: failed Kalshi quote for {kalshi_dec.symbol}: {e}")
            return

        # Re-verify edge
        combined_cost = poly_fresh_price + kalshi_buy_price
        total_fees = cfg.fee_estimate_poly_pct + cfg.fee_estimate_kalshi_pct
        fresh_net_edge = (1.0 - combined_cost) - total_fees

        if fresh_net_edge < cfg.min_net_edge_pct:
            log.info(
                f"CrossPlatformArb: edge closed after re-verification "
                f"(combined={combined_cost:.4f}, net_edge={fresh_net_edge:.4f})"
            )
            return

        # Size
        poly_size_usd = min(cfg.max_size_per_leg_usd, poly_portfolio.cash * 0.1)
        kalshi_size_usd = min(cfg.max_size_per_leg_usd, kalshi_portfolio.cash * 0.1)

        poly_qty = poly_size_usd / poly_fresh_price if poly_fresh_price > 0 else 0
        # Kalshi uses integer contracts
        kalshi_qty = max(1, int(kalshi_size_usd / kalshi_buy_price)) if kalshi_buy_price > 0 else 0

        if poly_qty <= 0 or kalshi_qty <= 0:
            return

        poly_order = OrderRequest(
            symbol=poly_dec.symbol,
            side=poly_dec.side or Side.BUY,
            quantity=poly_qty,
            order_type=OrderType.LIMIT,
            limit_price=poly_fresh_price,
            platform=Platform.POLYMARKET,
        )

        kalshi_order = OrderRequest(
            symbol=kalshi_dec.symbol,
            side=kalshi_dec.side or Side.BUY,
            quantity=float(kalshi_qty),
            order_type=OrderType.LIMIT,
            limit_price=kalshi_buy_price,
            platform=Platform.KALSHI,
        )

        log.info(
            f"CrossPlatformArb: submitting legs — "
            f"Poly {poly_dec.symbol[:20]} @ {poly_fresh_price:.4f} | "
            f"Kalshi {kalshi_dec.symbol} @ {kalshi_buy_price:.4f} | "
            f"net_edge={fresh_net_edge:.2%}"
        )

        async def _submit_poly():
            try:
                return await poly_broker.submit_order(poly_order), None
            except Exception as e:
                return None, e

        async def _submit_kalshi():
            try:
                return await kalshi_broker.submit_order(kalshi_order), None
            except Exception as e:
                return None, e

        (poly_result, poly_err), (kalshi_result, kalshi_err) = await asyncio.gather(
            _submit_poly(), _submit_kalshi()
        )

        poly_trade_id = None
        kalshi_trade_id = None
        reasoning = poly_dec.reasoning

        if poly_err or poly_result is None:
            log.warning(f"CrossPlatformArb: Polymarket leg failed: {poly_err}")
        else:
            self.risk_manager.record_trade()
            poly_trade_id = await self.repo.insert_trade(
                order_id=poly_result.order_id,
                symbol=poly_dec.symbol,
                side=(poly_dec.side or Side.BUY).value,
                quantity=poly_qty,
                filled_price=poly_result.filled_price,
                platform="polymarket",
                source=f"monitor:{self.monitor_id}",
                strategy_name=CrossPlatformArbScanner.name,
                reasoning=reasoning[:500],
                confidence=poly_dec.confidence,
                status=poly_result.status.value,
            )
            await self.repo.insert_monitor_trade(
                self.monitor_id, poly_trade_id, poly_fresh_price, poly_qty,
            )
            await self.event_bus.broadcast(WSEvent(
                type=WSEventType.TRADE_EXECUTED,
                data={
                    "symbol": poly_dec.symbol,
                    "side": (poly_dec.side or Side.BUY).value,
                    "quantity": poly_qty,
                    "source": f"monitor:{self.monitor_id}",
                    "strategy": "cross_platform_arb",
                },
            ))

        if kalshi_err or kalshi_result is None:
            log.warning(f"CrossPlatformArb: Kalshi leg failed: {kalshi_err}")
        else:
            self.risk_manager.record_trade()
            kalshi_trade_id = await self.repo.insert_trade(
                order_id=kalshi_result.order_id,
                symbol=kalshi_dec.symbol,
                side=(kalshi_dec.side or Side.BUY).value,
                quantity=float(kalshi_qty),
                filled_price=kalshi_result.filled_price,
                platform="kalshi",
                source=f"monitor:{self.monitor_id}",
                strategy_name=CrossPlatformArbScanner.name,
                reasoning=reasoning[:500],
                confidence=kalshi_dec.confidence,
                status=kalshi_result.status.value,
            )
            await self.repo.insert_monitor_trade(
                self.monitor_id, kalshi_trade_id, kalshi_buy_price, float(kalshi_qty),
            )
            await self.event_bus.broadcast(WSEvent(
                type=WSEventType.TRADE_EXECUTED,
                data={
                    "symbol": kalshi_dec.symbol,
                    "side": (kalshi_dec.side or Side.BUY).value,
                    "quantity": kalshi_qty,
                    "source": f"monitor:{self.monitor_id}",
                    "strategy": "cross_platform_arb",
                },
            ))

        # Record arb pair
        if poly_trade_id or kalshi_trade_id:
            await self.repo.insert_arb_pair(
                polymarket_trade_id=poly_trade_id,
                kalshi_trade_id=kalshi_trade_id,
                gross_edge=round(1.0 - combined_cost, 4),
                net_edge=round(fresh_net_edge, 4),
            )

        if (poly_err or poly_result is None) and (kalshi_err or kalshi_result is None):
            log.warning("CrossPlatformArb: BOTH legs failed — no position taken")
        elif poly_err or kalshi_err:
            log.warning(
                "CrossPlatformArb: PARTIAL ARB — only one leg filled. "
                "Position is directional, not hedged."
            )
        else:
            log.info(
                f"CrossPlatformArb: both legs filled, "
                f"net_edge={fresh_net_edge:.2%}, "
                f"poly_trade={poly_trade_id}, kalshi_trade={kalshi_trade_id}"
            )

    async def _check_polymarket_settlements(self, broker) -> None:
        """Record P&L for settled Polymarket positions."""
        try:
            unsettled = await self.repo.get_unsettled_polymarket_trades()
            if not unsettled:
                return

            for trade in unsettled:
                try:
                    is_settled, result = await broker.check_market_settled(trade["symbol"])
                    if not is_settled:
                        continue

                    entry_price = trade["filled_price"] or 0.0
                    qty = trade["quantity"]
                    side = trade["side"]

                    if side == "buy":
                        payout_per = (1.0 - entry_price) if result == "yes" else -entry_price
                    else:
                        payout_per = entry_price if result == "no" else -(1.0 - entry_price)

                    total_pnl = payout_per * qty

                    await self.repo.insert_polymarket_settlement(
                        trade_id=trade["id"],
                        condition_id="",
                        token_id=trade["symbol"],
                        side=side,
                        quantity=qty,
                        entry_price=entry_price,
                        result=result or "",
                        payout_per_contract=round(payout_per, 4),
                        total_pnl=round(total_pnl, 2),
                    )
                    await self.repo.increment_monitor_trade(self.monitor_id, pnl=total_pnl)

                    log.info(
                        f"CrossPlatformArb Poly settlement: {trade['symbol'][:20]} "
                        f"{side.upper()} → {(result or '?').upper()} → "
                        f"{'+'if total_pnl>0 else ''}${total_pnl:.2f}"
                    )
                except Exception as e:
                    log.debug(f"CrossPlatformArb Poly settlement check failed: {e}")
        except Exception as e:
            log.warning(f"CrossPlatformArb Poly settlement error: {e}")

    async def _check_kalshi_settlements(self, broker) -> None:
        """Record P&L for settled Kalshi positions in cross-platform arb trades."""
        try:
            unsettled = await self.repo.get_unsettled_kalshi_trades()
            if not unsettled:
                return

            for trade in unsettled:
                if "cross_platform" not in (trade.get("strategy_name") or ""):
                    continue
                try:
                    is_settled, result = await broker.check_market_settled(trade["symbol"])
                    if not is_settled:
                        continue

                    entry_price = trade["filled_price"] or 0.0
                    qty = trade["quantity"]
                    side = trade["side"]

                    if side == "buy":
                        payout_per = (1.0 - entry_price) if result == "yes" else -entry_price
                    else:
                        payout_per = entry_price if result == "no" else -(1.0 - entry_price)

                    total_pnl = payout_per * qty

                    await self.repo.insert_kalshi_settlement(
                        trade_id=trade["id"],
                        ticker=trade["symbol"],
                        side=side,
                        quantity=qty,
                        entry_price=entry_price,
                        result=result or "",
                        payout_per_contract=round(payout_per, 4),
                        total_pnl=round(total_pnl, 2),
                    )
                    await self.repo.increment_monitor_trade(self.monitor_id, pnl=total_pnl)

                    log.info(
                        f"CrossPlatformArb Kalshi settlement: {trade['symbol']} "
                        f"{side.upper()} → {(result or '?').upper()} → "
                        f"{'+'if total_pnl>0 else ''}${total_pnl:.2f}"
                    )
                except Exception as e:
                    log.debug(f"CrossPlatformArb Kalshi settlement check failed: {e}")
        except Exception as e:
            log.warning(f"CrossPlatformArb Kalshi settlement error: {e}")


def _parse_kalshi_price(reasoning: str) -> float:
    """Extract the Kalshi price from a decision reasoning tag."""
    import re
    match = re.search(r"kprice=(\d+\.\d+)", reasoning)
    if match:
        return float(match.group(1))
    return 0.5
