"""Stock watchlist monitor — scores and auto-trades watchlist stocks."""

from __future__ import annotations

from trading_bot.models import Action, OrderRequest, OrderType, Platform, Side, WSEvent, WSEventType
from trading_bot.monitors.adaptation import StrategyAdaptation
from trading_bot.monitors.base import BaseMonitor
from trading_bot.strategies.stock_scorer import MultiSignalStockScorer
from trading_bot.utils.logging import log


class StockWatchlistMonitor(BaseMonitor):
    monitor_type = "stock_watchlist"

    def get_interval_seconds(self) -> int:
        return self.config.monitors.stock_watchlist_interval_minutes * 60

    async def run_cycle(self) -> None:
        scorer = MultiSignalStockScorer(self.config)
        broker = self.brokers.get("alpaca")
        if not broker:
            log.warning("No Alpaca broker configured for stock watchlist monitor")
            return

        portfolio = await broker.get_account()
        adaptation = StrategyAdaptation(self.config.monitors, self.repo)
        state = await self.repo.get_monitor_state(self.monitor_id)
        scale = state["current_position_scale"] if state else 1.0

        for symbol in self.config.stocks.watchlist:
            try:
                score = await scorer.score_stock(symbol)

                await self.repo.insert_decision(
                    symbol=symbol,
                    action=score.suggested_action.value,
                    confidence=score.confidence,
                    reasoning=score.reasoning,
                    source=f"monitor:{self.monitor_id}",
                    strategy_name=scorer.name,
                )

                if score.suggested_action == Action.HOLD:
                    continue

                risk_check = self.risk_manager.check_decision(
                    type("D", (), {"confidence": score.confidence, "action": score.suggested_action})()  # type: ignore
                )
                if not risk_check.approved:
                    continue

                current_price = await broker.get_quote(symbol)
                raw_qty = self.risk_manager.calculate_position_size(
                    score.confidence, portfolio.equity, current_price,
                )
                qty = raw_qty * scale

                if qty <= 0:
                    continue

                side = Side.BUY if score.suggested_action == Action.BUY else Side.SELL
                order = OrderRequest(
                    symbol=symbol, side=side, quantity=qty,
                    order_type=OrderType.MARKET, platform=Platform.ALPACA,
                )

                order_check = self.risk_manager.check_order(order, portfolio, current_price)
                if not order_check.approved:
                    continue
                if order_check.adjusted_quantity is not None:
                    order.quantity = order_check.adjusted_quantity

                result = await broker.submit_order(order)
                self.risk_manager.record_trade()

                trade_id = await self.repo.insert_trade(
                    order_id=result.order_id, symbol=symbol, side=side.value,
                    quantity=order.quantity, filled_price=result.filled_price,
                    platform="alpaca", source=f"monitor:{self.monitor_id}",
                    strategy_name=scorer.name, reasoning=score.reasoning,
                    confidence=score.confidence, status=result.status.value,
                )
                await self.repo.insert_monitor_trade(
                    self.monitor_id, trade_id, current_price, order.quantity,
                )

                await self.event_bus.broadcast(WSEvent(
                    type=WSEventType.TRADE_EXECUTED,
                    data={
                        "symbol": symbol, "side": side.value,
                        "quantity": order.quantity,
                        "filled_price": result.filled_price,
                        "source": f"monitor:{self.monitor_id}",
                    },
                ))

                log.info(f"Monitor {self.monitor_id}: {side.value} {order.quantity:.2f} {symbol}")

            except Exception as e:
                log.warning(f"Monitor {self.monitor_id} failed on {symbol}: {e}")

        await adaptation.evaluate_and_adapt(self.monitor_id)
