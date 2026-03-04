"""Polymarket arbitrage monitor — continuously scans for multi-outcome arbitrage."""

from __future__ import annotations

from trading_bot.models import (
    Action, OrderRequest, OrderType, Platform, Side, WSEvent, WSEventType,
)
from trading_bot.monitors.adaptation import StrategyAdaptation
from trading_bot.monitors.base import BaseMonitor
from trading_bot.strategies.arbitrage import ArbitrageScanner
from trading_bot.utils.logging import log


class PolymarketArbMonitor(BaseMonitor):
    monitor_type = "polymarket_arb"

    def get_interval_seconds(self) -> int:
        return self.config.monitors.arb_scan_interval_minutes * 60

    async def run_cycle(self) -> None:
        scanner = ArbitrageScanner(self.config)
        broker = self.brokers.get("polymarket")
        if not broker:
            return

        state = await self.repo.get_monitor_state(self.monitor_id)
        scale = state["current_position_scale"] if state else 1.0

        result = await scanner.scan()
        portfolio = await broker.get_account()

        if result.decisions:
            await self.event_bus.broadcast(WSEvent(
                type=WSEventType.STRATEGY_SIGNAL,
                data={
                    "strategy": scanner.name,
                    "opportunities_found": result.metadata.get("opportunities_found", 0),
                    "decisions_count": len(result.decisions),
                },
            ))

        for decision in result.decisions:
            try:
                current_price = await broker.get_quote(decision.symbol)
                raw_size = decision.suggested_size_usd * scale
                qty = raw_size / current_price if current_price > 0 else 0

                if qty <= 0:
                    continue

                side = decision.side or Side.BUY
                order = OrderRequest(
                    symbol=decision.symbol, side=side, quantity=qty,
                    order_type=OrderType.MARKET, platform=Platform.POLYMARKET,
                )

                order_check = self.risk_manager.check_order(order, portfolio, current_price)
                if not order_check.approved:
                    continue
                if order_check.adjusted_quantity is not None:
                    order.quantity = order_check.adjusted_quantity

                trade_result = await broker.submit_order(order)
                self.risk_manager.record_trade()

                trade_id = await self.repo.insert_trade(
                    order_id=trade_result.order_id, symbol=decision.symbol,
                    side=side.value, quantity=order.quantity,
                    filled_price=trade_result.filled_price, platform="polymarket",
                    source=f"monitor:{self.monitor_id}", strategy_name=scanner.name,
                    reasoning=decision.reasoning, confidence=decision.confidence,
                    status=trade_result.status.value,
                )
                await self.repo.insert_monitor_trade(
                    self.monitor_id, trade_id, current_price, order.quantity,
                )

                await self.event_bus.broadcast(WSEvent(
                    type=WSEventType.TRADE_EXECUTED,
                    data={
                        "symbol": decision.symbol, "side": side.value,
                        "quantity": order.quantity,
                        "source": f"monitor:{self.monitor_id}",
                    },
                ))

            except Exception as e:
                log.warning(f"Monitor {self.monitor_id} trade failed: {e}")

        adaptation = StrategyAdaptation(self.config.monitors, self.repo)
        await adaptation.evaluate_and_adapt(self.monitor_id)
