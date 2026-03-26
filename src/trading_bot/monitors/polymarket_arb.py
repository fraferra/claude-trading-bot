"""Polymarket arbitrage monitor — continuously scans for multi-outcome arbitrage.

Runs every N minutes and executes risk-free arbitrage on Polymarket events where
the sum of YES prices across mutually exclusive outcomes deviates from $1.00
enough to cover fees and leave a net profit margin.

No LLM calls — pure math.
"""

from __future__ import annotations

import asyncio
import json

import httpx

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
from trading_bot.strategies.arbitrage import ArbitrageScanner
from trading_bot.utils.logging import log

POLYMARKET_CLOB = "https://clob.polymarket.com"


class PolymarketArbMonitor(BaseMonitor):
    """Polymarket multi-outcome arbitrage monitor.

    Every cycle:
    1. Check for settled trades (P&L recording)
    2. Scan for arbitrage opportunities (pure math, no LLM)
    3. Re-verify edge with fresh quotes per opportunity group
    4. Submit all legs of each arb concurrently

    Optionally uses a WebSocket price feed for sub-second price updates
    when config.polymarket.ws_enabled is True.
    """

    monitor_type = "polymarket_arb"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._ws_feed = None
        if getattr(self.config.polymarket, "ws_enabled", False):
            from trading_bot.brokers.polymarket_ws import PolymarketWebSocketFeed
            ttl = getattr(self.config.polymarket, "ws_price_ttl_seconds", 5)
            self._ws_feed = PolymarketWebSocketFeed(ttl_seconds=ttl)

    async def start(self) -> None:
        """Start monitor and optionally the WebSocket feed."""
        await super().start()
        if self._ws_feed:
            try:
                top_n = getattr(self.config.polymarket, "ws_top_markets", 200)
                from trading_bot.analysis.market_data import get_all_events
                events = await get_all_events(limit=top_n)
                token_ids = [
                    t.get("token_id", "")
                    for event in events
                    for market in event.get("markets", [])
                    for t in market.get("tokens", [])
                    if t.get("token_id")
                ]
                await self._ws_feed.start(token_ids[:500])
                log.info(
                    f"PolymarketArbMonitor: WebSocket feed started "
                    f"for {len(token_ids[:500])} tokens"
                )
            except Exception as e:
                log.warning(f"PolymarketArbMonitor: WebSocket feed start failed: {e}")
                self._ws_feed = None

    async def stop(self) -> None:
        if self._ws_feed:
            await self._ws_feed.stop()
        await super().stop()

    async def _get_price(self, broker, token_id: str) -> float:
        """Get price, preferring WebSocket cache over REST API."""
        if self._ws_feed:
            cached = self._ws_feed.get_price_sync(token_id)
            if cached is not None:
                return cached
        return await broker.get_quote(token_id)

    def get_interval_seconds(self) -> int:
        return self.config.monitors.arb_scan_interval_minutes * 60

    async def run_cycle(self) -> None:
        broker = self.brokers.get("polymarket")
        if not broker:
            log.warning("PolymarketArbMonitor: no Polymarket broker configured — skipping")
            return

        # 1. Settlement check before scanning for new trades
        await self._check_settlements(broker)

        # 2. Scan for opportunities
        scanner = ArbitrageScanner(self.config)
        result = await scanner.scan()

        opportunity_groups = result.metadata.get("opportunities", [])

        if opportunity_groups:
            await self.event_bus.broadcast(WSEvent(
                type=WSEventType.STRATEGY_SIGNAL,
                data={
                    "strategy": "polymarket_arb",
                    "opportunities_found": result.metadata.get("opportunities_found", 0),
                    "events_scanned": result.metadata.get("events_scanned", 0),
                    "source": f"monitor:{self.monitor_id}",
                    "opportunities": [
                        {
                            "event_title": o["event_title"],
                            "price_sum": o["price_sum"],
                            "edge_pct": o["edge_pct"],
                            "direction": o["direction"],
                        }
                        for o in opportunity_groups[:5]
                    ],
                },
            ))

        # 3. Get portfolio balance
        portfolio = await broker.get_account()
        available_cash = portfolio.cash
        log.info(
            f"PolymarketArbMonitor: {len(opportunity_groups)} opportunities, "
            f"available cash=${available_cash:.2f}"
        )

        # 4. Execute each opportunity group
        state = await self.repo.get_monitor_state(self.monitor_id)
        scale = state["current_position_scale"] if state else 1.0

        for opp in opportunity_groups:
            await self._execute_opportunity(opp, broker, portfolio, available_cash, scale)

        # 5. Strategy adaptation
        adaptation = StrategyAdaptation(self.config.monitors, self.repo)
        await adaptation.evaluate_and_adapt(self.monitor_id)

    async def _execute_opportunity(
        self, opp: dict, broker, portfolio, available_cash: float, scale: float
    ) -> None:
        """Execute all legs of a single arbitrage opportunity.

        Re-verifies edge with fresh quotes, then submits all legs concurrently.
        """
        outcomes = opp.get("outcomes", [])
        direction = opp["direction"]
        event_title = opp["event_title"]

        if not outcomes:
            return

        # Re-verify with fresh quotes
        # Prefer token_id (for CLOB midpoint API), fall back to condition_id; skip blanks
        token_ids = [o.get("token_id") or o.get("condition_id", "") for o in outcomes]
        outcomes = [o for o, t in zip(outcomes, token_ids) if t]
        token_ids = [t for t in token_ids if t]
        if len(token_ids) < 2:
            log.info(f"PolymarketArb: not enough outcomes with valid IDs for {event_title}, skipping")
            return
        try:
            fresh_prices = await asyncio.gather(
                *[self._get_price(broker, t) for t in token_ids],
                return_exceptions=True,
            )
        except Exception as e:
            log.warning(f"PolymarketArb: failed to get fresh quotes for {event_title}: {e}")
            return

        valid = [
            (t, p, o) for t, p, o in zip(token_ids, fresh_prices, outcomes)
            if isinstance(p, float) and 0.001 <= p <= 0.999
        ]
        if len(valid) < 2:
            log.info(f"PolymarketArb: too few valid quotes for {event_title}, skipping")
            return

        fresh_sum = sum(p for _, p, _ in valid)
        raw_edge = abs(1.0 - fresh_sum)
        total_fees = self.config.strategies.arbitrage.fee_estimate_pct * len(valid)
        fresh_net_edge = raw_edge - total_fees

        if fresh_net_edge < self.config.strategies.arbitrage.min_edge_pct:
            log.info(
                f"PolymarketArb: edge closed for {event_title} "
                f"(fresh_sum={fresh_sum:.4f}, net_edge={fresh_net_edge:.4f}), skipping"
            )
            return

        cfg = self.config.strategies.arbitrage
        per_leg_usd = cfg.max_size_per_leg_usd * scale
        estimated_total_cost = per_leg_usd * len(valid)

        if estimated_total_cost > available_cash and available_cash > 0:
            per_leg_usd = min(per_leg_usd, available_cash / len(valid))

        if per_leg_usd < 1.0:
            log.info(f"PolymarketArb: per-leg size too small for {event_title}, skipping")
            return

        # Build orders for each valid leg
        orders: list[tuple] = []
        for token_id, fresh_price, outcome in valid:
            qty = per_leg_usd / fresh_price if fresh_price > 0 else 0
            if qty <= 0:
                continue
            side = Side.BUY if direction == "buy_all" else Side.SELL
            order = OrderRequest(
                symbol=token_id,
                side=side,
                quantity=qty,
                order_type=OrderType.LIMIT,
                limit_price=fresh_price,
                platform=Platform.POLYMARKET,
            )
            orders.append((token_id, order, fresh_price, qty, side, outcome))

        if not orders:
            return

        async def _submit_leg(token_id, order, price, qty, side, outcome):
            try:
                # Arb legs bypass the daily trade-count limit — arb positions are
                # fully hedged (one leg per outcome) so they are not directional
                # speculation and should not count against the per-day cap.
                # We still enforce the daily loss limit and basic cash check.
                if portfolio.equity > 0:
                    daily_loss_pct = -portfolio.daily_pnl / portfolio.equity
                    if daily_loss_pct >= self.risk_manager.config.daily_loss_limit_pct:
                        return (token_id, order, price, qty, side, outcome, None,
                                "daily loss limit reached")
                order_value = order.quantity * price
                if order_value > portfolio.cash:
                    max_qty = portfolio.cash / price if price > 0 else 0
                    if max_qty <= 0:
                        return (token_id, order, price, qty, side, outcome, None,
                                "insufficient cash")
                    order.quantity = max_qty

                trade_result = await broker.submit_order(order)
                self.risk_manager.record_trade()
                return (token_id, order, price, order.quantity, side, outcome, trade_result, None)
            except Exception as e:
                return (token_id, order, price, qty, side, outcome, None, e)

        log.info(
            f"PolymarketArb: submitting {len(orders)} legs for {event_title} "
            f"({direction}, fresh_sum={fresh_sum:.4f}, net_edge={fresh_net_edge:.2%})"
        )

        leg_results = await asyncio.gather(
            *[_submit_leg(t, o, p, q, s, oc) for t, o, p, q, s, oc in orders]
        )

        filled_legs = 0
        for (token_id, order, price, qty, side, outcome, trade_result, err) in leg_results:
            if err or trade_result is None:
                log.warning(f"PolymarketArb leg failed for {token_id}: {err}")
                continue

            condition_id = outcome.get("condition_id", token_id)
            trade_id = await self.repo.insert_trade(
                order_id=trade_result.order_id,
                symbol=token_id,
                side=side.value,
                quantity=order.quantity,
                filled_price=trade_result.filled_price,
                platform="polymarket",
                source=f"monitor:{self.monitor_id}",
                strategy_name=ArbitrageScanner.name,
                reasoning=(
                    f"PolymarketArb: {event_title[:80]} | "
                    f"fresh_sum={fresh_sum:.4f} net_edge={fresh_net_edge:.2%} | {direction}"
                ),
                confidence=min(0.99, 0.70 + fresh_net_edge * 3),
                status=trade_result.status.value,
            )

            await self.repo.insert_monitor_trade(
                self.monitor_id, trade_id, price, order.quantity,
            )

            await self.repo.insert_agent_decision(
                agent_type="polymarket_arb",
                symbol=token_id,
                action=side.value,
                confidence=min(0.99, 0.70 + fresh_net_edge * 3),
                reasoning=(
                    f"PolymarketArb leg: {event_title[:80]} | "
                    f"direction={direction} price={price:.4f} qty={qty:.2f}"
                ),
                signals_json=json.dumps({
                    "condition_id": condition_id,
                    "token_id": token_id,
                    "price": price,
                    "qty": float(qty),
                    "fresh_sum": round(fresh_sum, 4),
                    "net_edge": round(fresh_net_edge, 4),
                    "direction": direction,
                    "n_legs": len(orders),
                    "filled_price": trade_result.filled_price,
                }),
                outcome="executed",
                trade_id=trade_id,
            )

            filled_legs += 1

            await self.event_bus.broadcast(WSEvent(
                type=WSEventType.TRADE_EXECUTED,
                data={
                    "symbol": token_id,
                    "side": side.value,
                    "quantity": order.quantity,
                    "source": f"monitor:{self.monitor_id}",
                    "strategy": "polymarket_arb",
                },
            ))

        if filled_legs > 0:
            log.info(
                f"PolymarketArb: executed {filled_legs}/{len(orders)} legs for {event_title}, "
                f"net_edge={fresh_net_edge:.2%}"
            )
        if filled_legs < len(orders):
            log.warning(
                f"PolymarketArb: PARTIAL ARB WARNING — only {filled_legs}/{len(orders)} legs "
                f"filled for {event_title}. Position may NOT be fully hedged."
            )

    async def _check_settlements(self, broker) -> None:
        """Check if any Polymarket trades have settled and record P&L."""
        try:
            unsettled = await self.repo.get_unsettled_polymarket_trades()
            if not unsettled:
                return

            log.info(f"PolymarketArb settlement check: {len(unsettled)} unsettled trades")

            async with httpx.AsyncClient(timeout=10.0) as client:
                for trade in unsettled:
                    try:
                        token_id = trade["symbol"]
                        # Get market info to check resolution
                        resp = await client.get(
                            f"{POLYMARKET_CLOB}/markets",
                            params={"clob_token_ids": token_id},
                        )
                        if resp.status_code != 200:
                            continue

                        markets = resp.json()
                        if not markets:
                            continue

                        market = markets[0] if isinstance(markets, list) else markets
                        is_resolved = market.get("closed", False) or market.get("resolved", False)
                        if not is_resolved:
                            continue

                        # Determine result from token outcome
                        tokens = market.get("tokens", [])
                        result = None
                        for token in tokens:
                            if token.get("token_id") == token_id:
                                winner = token.get("winner", False)
                                outcome = token.get("outcome", "").lower()
                                if winner:
                                    result = outcome  # 'yes' or 'no'
                                    break

                        if result is None:
                            # Fallback: check if market is resolved and find winning token
                            for token in tokens:
                                if token.get("winner", False):
                                    result = token.get("outcome", "").lower()
                                    break

                        if result is None:
                            continue

                        # Determine whether the traded token is YES or NO
                        token_outcome = "yes"
                        for token in tokens:
                            if token.get("token_id") == token_id:
                                token_outcome = token.get("outcome", "yes").lower()
                                break

                        entry_price = trade["filled_price"] or 0.0
                        qty = trade["quantity"]
                        side = trade["side"]
                        condition_id = market.get("condition_id", market.get("conditionId", ""))

                        # Token pays $1 if its outcome matches the result, $0 otherwise
                        token_won = (token_outcome == result)
                        if side == "buy":
                            payout_per = (1.0 - entry_price) if token_won else -entry_price
                        else:
                            payout_per = entry_price if not token_won else -(1.0 - entry_price)

                        total_pnl = payout_per * qty

                        await self.repo.insert_polymarket_settlement(
                            trade_id=trade["id"],
                            condition_id=condition_id,
                            token_id=token_id,
                            side=side,
                            quantity=qty,
                            entry_price=entry_price,
                            result=result,
                            payout_per_contract=round(payout_per, 4),
                            total_pnl=round(total_pnl, 2),
                        )

                        await self.repo.increment_monitor_trade(self.monitor_id, pnl=total_pnl)
                        if hasattr(broker, "record_settlement_pnl"):
                            broker.record_settlement_pnl(total_pnl)

                        await self.repo.insert_agent_decision(
                            agent_type="polymarket_arb",
                            symbol=token_id,
                            action="settled",
                            confidence=1.0,
                            reasoning=(
                                f"Market settled: {result.upper()}. "
                                f"{'WON' if total_pnl > 0 else 'LOST'} "
                                f"${abs(total_pnl):.2f} "
                                f"({qty:.2f} shares @ {entry_price:.4f})"
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
                            f"PolymarketArb settlement: {token_id[:20]} {side.upper()} "
                            f"{qty:.2f} @ {entry_price:.4f} → {result.upper()} → "
                            f"{emoji}${total_pnl:.2f}"
                        )

                        await self.event_bus.broadcast(WSEvent(
                            type=WSEventType.TRADE_EXECUTED,
                            data={
                                "symbol": token_id,
                                "side": "settled",
                                "source": f"monitor:{self.monitor_id}",
                                "result": result,
                                "pnl": total_pnl,
                            },
                        ))

                    except Exception as e:
                        log.warning(
                            f"PolymarketArb settlement check failed for "
                            f"{trade.get('symbol', '?')}: {e}"
                        )

        except Exception as e:
            log.warning(f"PolymarketArb settlement check error: {e}")
