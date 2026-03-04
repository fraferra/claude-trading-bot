"""Kalshi prediction market trading monitor — autonomous discovery and trading."""

from __future__ import annotations

import asyncio
import json

from trading_bot.agents.kalshi_analyst import KalshiAnalystAgent
from trading_bot.agents.kalshi_discovery import KalshiDiscoveryAgent
from trading_bot.models import (
    Action, OrderRequest, OrderType, Platform, Side, WSEvent, WSEventType,
)
from trading_bot.monitors.adaptation import StrategyAdaptation
from trading_bot.monitors.base import BaseMonitor
from trading_bot.utils.logging import log


class KalshiPredictionMonitor(BaseMonitor):
    """Autonomous Kalshi prediction market trading monitor.

    Every cycle:
    1. Discover interesting markets
    2. Estimate probabilities with LLM
    3. Trade on markets where AI probability diverges from market price
    """

    monitor_type = "kalshi_prediction"

    def get_interval_seconds(self) -> int:
        return self.config.kalshi.scan_interval_minutes * 60

    async def run_cycle(self) -> None:
        broker = self.brokers.get("kalshi")
        if not broker:
            log.warning("No Kalshi broker configured — skipping cycle")
            return

        discovery = KalshiDiscoveryAgent(self.config, broker)
        analyst = KalshiAnalystAgent(self.config)

        # 1. Discovery: find interesting markets
        markets = await discovery.find_opportunities()
        if not markets:
            log.info("Kalshi Monitor: no markets found this cycle")
            return

        log.info(f"Kalshi Monitor: analyzing {len(markets)} markets")

        # 2. Analysis: estimate probabilities (with concurrency limit)
        estimates = []
        sem = asyncio.Semaphore(3)  # Max 3 concurrent LLM calls

        async def _analyze(m):
            async with sem:
                return await analyst.analyze_market(m)

        results = await asyncio.gather(
            *[_analyze(m) for m in markets], return_exceptions=True
        )

        for r in results:
            if isinstance(r, Exception):
                log.warning(f"Kalshi analysis failed: {r}")
                continue
            estimates.append(r)
            # Log to DB
            await self.repo.insert_kalshi_estimate(
                ticker=r.ticker,
                title=r.title,
                market_price=r.market_price,
                ai_probability=r.ai_probability,
                edge_pct=r.edge_pct,
                kelly_fraction=r.kelly_fraction,
                suggested_side=r.suggested_side.value if r.suggested_side else None,
                reasoning=r.reasoning[:500],
                category=r.category,
            )
            # Log decision for visibility
            signals = {
                "market_price": r.market_price,
                "ai_probability": r.ai_probability,
                "edge_pct": r.edge_pct,
                "kelly_fraction": r.kelly_fraction,
                "category": r.category,
                "title": r.title,
            }
            min_edge = self.config.kalshi.min_edge_pct
            if abs(r.edge_pct) < min_edge:
                outcome = "filtered_edge"
                action = "hold"
            else:
                outcome = "pending_execution"
                action = r.suggested_side.value if r.suggested_side else "hold"
            await self.repo.insert_agent_decision(
                agent_type="kalshi_prediction",
                symbol=r.ticker,
                action=action,
                confidence=min(0.95, abs(r.edge_pct) * 2 + 0.5),
                reasoning=r.reasoning,
                signals_json=json.dumps(signals),
                outcome=outcome,
            )

        # 3. Generate decisions
        portfolio = await broker.get_account()
        state = await self.repo.get_monitor_state(self.monitor_id)
        scale = state["current_position_scale"] if state else 1.0

        decisions = await analyst.generate_decisions(estimates, portfolio)

        if decisions:
            await self.event_bus.broadcast(WSEvent(
                type=WSEventType.STRATEGY_SIGNAL,
                data={
                    "strategy": "kalshi_prediction",
                    "edges_found": len(decisions),
                    "source": f"monitor:{self.monitor_id}",
                },
            ))

        # 4. Execute trades — track cash committed to avoid exceeding balance
        available_cash = portfolio.cash
        log.info(f"Kalshi Monitor: executing {len(decisions)} decisions, available cash=${available_cash:.2f}")

        for decision in decisions:
            try:
                current_price = await broker.get_quote(decision.symbol)
                raw_size = decision.suggested_size_usd * scale
                # Kalshi trades in contracts (integer), cost = qty * price
                qty = max(1, int(raw_size / current_price)) if current_price > 0 else 0
                if qty <= 0:
                    continue

                # Cap quantity to what we can actually afford
                if current_price > 0:
                    max_affordable = int(available_cash / current_price)
                    if max_affordable <= 0:
                        log.info(
                            f"Kalshi Monitor: skipping {decision.symbol} — "
                            f"insufficient cash (${available_cash:.2f} < {current_price:.2f})"
                        )
                        await self.repo.insert_agent_decision(
                            agent_type="kalshi_prediction",
                            symbol=decision.symbol,
                            action=(decision.side or Side.BUY).value,
                            confidence=decision.confidence,
                            reasoning=f"Insufficient cash: ${available_cash:.2f} available, need ${current_price:.2f} per contract",
                            signals_json=json.dumps({"price": current_price, "qty": float(qty), "cash": available_cash}),
                            outcome="rejected_risk",
                        )
                        continue
                    qty = min(qty, max_affordable)

                side = decision.side or Side.BUY
                order = OrderRequest(
                    symbol=decision.symbol,
                    side=side,
                    quantity=float(qty),
                    order_type=OrderType.LIMIT,
                    limit_price=current_price,
                    platform=Platform.KALSHI,
                )

                order_check = self.risk_manager.check_order(order, portfolio, current_price)
                if not order_check.approved:
                    await self.repo.insert_agent_decision(
                        agent_type="kalshi_prediction",
                        symbol=decision.symbol,
                        action=side.value,
                        confidence=decision.confidence,
                        reasoning=f"Risk rejected: {order_check.reason}. Original: {decision.reasoning[:300]}",
                        signals_json=json.dumps({"price": current_price, "qty": float(qty)}),
                        outcome="rejected_risk",
                    )
                    continue
                if order_check.adjusted_quantity is not None:
                    order.quantity = order_check.adjusted_quantity

                # Final affordable check after risk adjustment
                order_cost = order.quantity * current_price
                if order_cost > available_cash:
                    order.quantity = float(int(available_cash / current_price))
                    if order.quantity <= 0:
                        continue
                    order_cost = order.quantity * current_price

                trade_result = await broker.submit_order(order)
                self.risk_manager.record_trade()

                # Deduct committed cash so next orders respect remaining balance
                available_cash -= order_cost
                portfolio.cash = available_cash

                trade_id = await self.repo.insert_trade(
                    order_id=trade_result.order_id,
                    symbol=decision.symbol,
                    side=side.value,
                    quantity=order.quantity,
                    filled_price=trade_result.filled_price,
                    platform="kalshi",
                    source=f"monitor:{self.monitor_id}",
                    strategy_name="kalshi_prediction",
                    reasoning=decision.reasoning[:500],
                    confidence=decision.confidence,
                    status=trade_result.status.value,
                )
                await self.repo.insert_agent_decision(
                    agent_type="kalshi_prediction",
                    symbol=decision.symbol,
                    action=side.value,
                    confidence=decision.confidence,
                    reasoning=decision.reasoning,
                    signals_json=json.dumps({"price": current_price, "qty": order.quantity, "filled": trade_result.filled_price}),
                    outcome="executed",
                    trade_id=trade_id,
                )
                await self.repo.insert_monitor_trade(
                    self.monitor_id, trade_id, current_price, order.quantity,
                )

                await self.event_bus.broadcast(WSEvent(
                    type=WSEventType.TRADE_EXECUTED,
                    data={
                        "symbol": decision.symbol,
                        "side": side.value,
                        "quantity": order.quantity,
                        "source": f"monitor:{self.monitor_id}",
                    },
                ))

            except Exception as e:
                log.warning(f"Kalshi Monitor trade failed for {decision.symbol}: {e}")

        # 5. Strategy adaptation
        adaptation = StrategyAdaptation(self.config.monitors, self.repo)
        await adaptation.evaluate_and_adapt(self.monitor_id)
