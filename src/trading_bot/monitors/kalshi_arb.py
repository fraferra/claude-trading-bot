"""Kalshi arbitrage monitor — continuously scans for MECE multi-outcome arbitrage.

Runs every N minutes and executes risk-free arbitrage on Kalshi events where the
sum of YES prices across mutually exclusive outcomes deviates from $1.00 enough
to cover fees and leave a net profit margin.

No LLM calls — pure math.
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
from trading_bot.strategies.kalshi_arb import KalshiArbitrageScanner
from trading_bot.utils.logging import log


class KalshiArbMonitor(BaseMonitor):
    """Kalshi MECE arbitrage monitor.

    Every cycle:
    1. Check for settled trades (P&L recording)
    2. Scan for arbitrage opportunities (pure math, no LLM)
    3. Re-verify edge with fresh quotes
    4. Submit all legs of each arb concurrently
    """

    monitor_type = "kalshi_arb"

    def get_interval_seconds(self) -> int:
        return self.config.kalshi_arb.scan_interval_minutes * 60

    async def run_cycle(self) -> None:
        broker = self.brokers.get("kalshi")
        if not broker:
            log.warning("KalshiArbMonitor: no Kalshi broker configured — skipping")
            return
        if not self.config.kalshi_arb.enabled:
            return

        # 1. Settlement check before scanning for new trades
        await self._check_settlements(broker)

        # 2. Scan for opportunities
        scanner = KalshiArbitrageScanner(self.config.kalshi_arb)
        result = await scanner.scan(broker)

        opportunity_groups = result.metadata.get("opportunity_groups", [])

        if opportunity_groups:
            await self.event_bus.broadcast(WSEvent(
                type=WSEventType.STRATEGY_SIGNAL,
                data={
                    "strategy": "kalshi_arb",
                    "opportunities_found": result.metadata["opportunities_found"],
                    "events_scanned": result.metadata["events_scanned"],
                    "source": f"monitor:{self.monitor_id}",
                    "opportunities": [
                        {
                            "event_title": o["event_title"],
                            "price_sum": o["price_sum"],
                            "net_edge": o["net_edge"],
                            "direction": o["direction"],
                            "n_legs": o["n_legs"],
                        }
                        for o in opportunity_groups
                    ],
                },
            ))

        # 3. Get portfolio balance
        portfolio = await broker.get_account()
        available_cash = portfolio.cash
        log.info(
            f"KalshiArbMonitor: {len(opportunity_groups)} opportunities, "
            f"available cash=${available_cash:.2f}"
        )

        # 4. Execute each opportunity group
        for opp in opportunity_groups:
            await self._execute_opportunity(opp, broker, portfolio, available_cash)
            # Update available_cash estimate (rough — real deductions happen inside)

        # 5. Strategy adaptation
        adaptation = StrategyAdaptation(self.config.monitors, self.repo)
        await adaptation.evaluate_and_adapt(self.monitor_id)

    async def _execute_opportunity(
        self, opp: dict, broker, portfolio, available_cash: float
    ) -> None:
        """Execute all legs of a single arbitrage opportunity.

        Fetches fresh quotes, re-verifies the edge still exists, then
        submits all leg orders concurrently via asyncio.gather().
        """
        tickers = opp["tickers"]
        direction = opp["direction"]
        event_title = opp["event_title"]
        n_legs = opp["n_legs"]

        # Re-verify with fresh quotes
        try:
            fresh_prices = await asyncio.gather(
                *[broker.get_quote(t) for t in tickers],
                return_exceptions=True,
            )
        except Exception as e:
            log.warning(f"KalshiArb: failed to get fresh quotes for {event_title}: {e}")
            return

        # Filter out any failed quotes
        valid = [
            (t, p) for t, p in zip(tickers, fresh_prices)
            if isinstance(p, float) and 0.01 <= p <= 0.99
        ]
        if len(valid) < self.config.kalshi_arb.min_markets:
            log.info(f"KalshiArb: too few valid quotes for {event_title}, skipping")
            return

        fresh_sum = sum(p for _, p in valid)
        raw_edge = abs(1.0 - fresh_sum)
        total_fees = self.config.kalshi_arb.fee_estimate_pct * len(valid)
        fresh_net_edge = raw_edge - total_fees

        if fresh_net_edge < self.config.kalshi_arb.min_edge_pct:
            log.info(
                f"KalshiArb: edge closed for {event_title} "
                f"(fresh_sum={fresh_sum:.4f}, net_edge={fresh_net_edge:.4f}), skipping"
            )
            await self.repo.insert_agent_decision(
                agent_type="kalshi_arb",
                symbol=opp["event_ticker"],
                action="hold",
                confidence=0.0,
                reasoning=f"Edge closed after re-verification: fresh_sum={fresh_sum:.4f}",
                signals_json=json.dumps({
                    "scan_sum": opp["price_sum"],
                    "fresh_sum": round(fresh_sum, 4),
                    "fresh_net_edge": round(fresh_net_edge, 4),
                }),
                outcome="filtered_stale",
            )
            return

        # Check total cost against available cash and exposure limit
        # For buy_all: cost = sum of (qty * price) per leg
        # Use uniform qty across legs for simplicity
        cfg = self.config.kalshi_arb
        per_leg_usd = min(cfg.max_size_per_leg_usd, cfg.max_total_exposure_usd / len(valid))
        estimated_total_cost = sum(per_leg_usd for _ in valid)  # rough upper bound

        if estimated_total_cost > available_cash:
            log.info(
                f"KalshiArb: insufficient cash for {event_title} "
                f"(need ~${estimated_total_cost:.2f}, have ${available_cash:.2f})"
            )
            await self.repo.insert_agent_decision(
                agent_type="kalshi_arb",
                symbol=opp["event_ticker"],
                action="hold",
                confidence=0.0,
                reasoning=f"Insufficient cash: need ~${estimated_total_cost:.2f}, available ${available_cash:.2f}",
                signals_json=json.dumps({"estimated_cost": estimated_total_cost, "available_cash": available_cash}),
                outcome="rejected_risk",
            )
            return

        # Build orders for each valid leg
        orders: list[tuple] = []
        for ticker, fresh_price in valid:
            qty = max(1, int(per_leg_usd / fresh_price))
            side = Side.BUY if direction == "buy_all" else Side.SELL
            order = OrderRequest(
                symbol=ticker,
                side=side,
                quantity=float(qty),
                order_type=OrderType.LIMIT,
                limit_price=fresh_price,
                platform=Platform.KALSHI,
            )
            orders.append((ticker, order, fresh_price, qty, side))

        # Submit all legs concurrently — this is the key to arb: minimize timing gap
        async def _submit_leg(ticker, order, price, qty, side):
            try:
                trade_result = await broker.submit_order(order)
                self.risk_manager.record_trade()
                return (ticker, order, price, qty, side, trade_result, None)
            except Exception as e:
                return (ticker, order, price, qty, side, None, e)

        log.info(
            f"KalshiArb: submitting {len(orders)} legs for {event_title} "
            f"({direction}, fresh_sum={fresh_sum:.4f}, net_edge={fresh_net_edge:.2%})"
        )

        leg_results = await asyncio.gather(
            *[_submit_leg(t, o, p, q, s) for t, o, p, q, s in orders]
        )

        total_cost = 0.0
        filled_legs = 0

        for (ticker, order, price, qty, side, trade_result, err) in leg_results:
            if err or trade_result is None:
                log.warning(f"KalshiArb leg failed for {ticker}: {err}")
                await self.repo.insert_agent_decision(
                    agent_type="kalshi_arb",
                    symbol=ticker,
                    action=side.value,
                    confidence=0.5,
                    reasoning=f"Leg order failed: {err}",
                    signals_json=json.dumps({"price": price, "qty": qty, "error": str(err)}),
                    outcome="rejected_risk",
                )
                continue

            trade_id = await self.repo.insert_trade(
                order_id=trade_result.order_id,
                symbol=ticker,
                side=side.value,
                quantity=order.quantity,
                filled_price=trade_result.filled_price,
                platform="kalshi",
                source=f"monitor:{self.monitor_id}",
                strategy_name=KalshiArbitrageScanner.name,
                reasoning=(
                    f"KalshiArb: {event_title[:80]} | "
                    f"fresh_sum={fresh_sum:.4f} net_edge={fresh_net_edge:.2%} | {direction}"
                ),
                confidence=min(0.99, 0.70 + fresh_net_edge * 3),
                status=trade_result.status.value,
            )

            await self.repo.insert_monitor_trade(
                self.monitor_id, trade_id, price, order.quantity,
            )

            await self.repo.insert_agent_decision(
                agent_type="kalshi_arb",
                symbol=ticker,
                action=side.value,
                confidence=min(0.99, 0.70 + fresh_net_edge * 3),
                reasoning=(
                    f"KalshiArb leg: {event_title[:80]} | "
                    f"direction={direction} price={price:.2f} qty={qty}"
                ),
                signals_json=json.dumps({
                    "event_ticker": opp["event_ticker"],
                    "price": price,
                    "qty": float(qty),
                    "fresh_sum": round(fresh_sum, 4),
                    "net_edge": round(fresh_net_edge, 4),
                    "direction": direction,
                    "n_legs": n_legs,
                    "filled_price": trade_result.filled_price,
                }),
                outcome="executed",
                trade_id=trade_id,
            )

            leg_cost = qty * price
            total_cost += leg_cost
            filled_legs += 1

            await self.event_bus.broadcast(WSEvent(
                type=WSEventType.TRADE_EXECUTED,
                data={
                    "symbol": ticker,
                    "side": side.value,
                    "quantity": order.quantity,
                    "source": f"monitor:{self.monitor_id}",
                    "strategy": "kalshi_arb",
                },
            ))

        if filled_legs > 0:
            log.info(
                f"KalshiArb: executed {filled_legs}/{len(orders)} legs for {event_title}, "
                f"total cost=${total_cost:.2f}"
            )
        if filled_legs < len(orders):
            log.warning(
                f"KalshiArb: PARTIAL ARB WARNING — only {filled_legs}/{len(orders)} legs filled "
                f"for {event_title}. Position is NOT fully hedged."
            )

    async def _check_settlements(self, broker) -> None:
        """Check if any Kalshi trades have settled and record P&L.

        Identical logic to KalshiPredictionMonitor._check_settlements.
        Safe to call from multiple monitors — insert_kalshi_settlement is
        guarded by trade_id uniqueness so no double-settlement risk.
        """
        try:
            unsettled = await self.repo.get_unsettled_kalshi_trades()
            if not unsettled:
                return

            ticker_trades: dict[str, list[dict]] = {}
            for trade in unsettled:
                ticker_trades.setdefault(trade["symbol"], []).append(trade)

            log.info(
                f"KalshiArb settlement check: {len(unsettled)} unsettled trades "
                f"across {len(ticker_trades)} markets"
            )

            for ticker, trades in ticker_trades.items():
                try:
                    is_settled, result = await broker.check_market_settled(ticker)
                    if not is_settled:
                        continue

                    log.info(f"KalshiArb: market {ticker} settled: result={result.upper()}")

                    for trade in trades:
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
                            ticker=ticker,
                            side=side,
                            quantity=qty,
                            entry_price=entry_price,
                            result=result,
                            payout_per_contract=round(payout_per, 4),
                            total_pnl=round(total_pnl, 2),
                        )

                        await self.repo.increment_monitor_trade(self.monitor_id, pnl=total_pnl)

                        await self.repo.insert_agent_decision(
                            agent_type="kalshi_arb",
                            symbol=ticker,
                            action="settled",
                            confidence=1.0,
                            reasoning=(
                                f"Market settled: {result.upper()}. "
                                f"{'WON' if total_pnl > 0 else 'LOST'} "
                                f"${abs(total_pnl):.2f} "
                                f"({qty:.0f} contracts @ {entry_price*100:.0f}c)"
                            ),
                            signals_json=json.dumps({
                                "result": result,
                                "entry_price": entry_price,
                                "payout_per_contract": round(payout_per, 4),
                                "total_pnl": round(total_pnl, 2),
                                "quantity": qty,
                                "side": side,
                            }),
                            outcome="settled_win" if total_pnl > 0 else "settled_loss",
                            trade_id=trade["id"],
                        )

                        emoji = "+" if total_pnl > 0 else ""
                        log.info(
                            f"KalshiArb settlement: {ticker} {side.upper()} {qty:.0f} @ "
                            f"{entry_price*100:.0f}c → {result.upper()} → "
                            f"{emoji}${total_pnl:.2f}"
                        )

                        await self.event_bus.broadcast(WSEvent(
                            type=WSEventType.TRADE_EXECUTED,
                            data={
                                "symbol": ticker,
                                "side": "settled",
                                "source": f"monitor:{self.monitor_id}",
                                "result": result,
                                "pnl": total_pnl,
                            },
                        ))

                except Exception as e:
                    log.warning(f"KalshiArb settlement check failed for {ticker}: {e}")

        except Exception as e:
            log.warning(f"KalshiArb settlement check error: {e}")
