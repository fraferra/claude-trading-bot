"""Drawdown accumulation monitor — DCA into leveraged ETFs with drawdown-aware sizing."""

from __future__ import annotations

import json

from trading_bot.models import (
    Action,
    OrderRequest,
    OrderType,
    Platform,
    Side,
    WSEvent,
    WSEventType,
)
from trading_bot.monitors.base import BaseMonitor
from trading_bot.strategies.drawdown_accumulation import evaluate_symbol
from trading_bot.utils.logging import log


class DrawdownAccumulationMonitor(BaseMonitor):
    """Monitor that accumulates leveraged ETF positions with drawdown-aware sizing.

    - Small DCA buys during normal conditions
    - Aggressive buys during significant drawdowns
    - Partial profit-taking when positions are up significantly
    - Tracks portfolio drawdown from high watermark
    """

    monitor_type = "drawdown_accumulation"

    def get_interval_seconds(self) -> int:
        return self.config.drawdown_accumulation.scan_interval_minutes * 60

    async def run_cycle(self) -> None:
        da_config = self.config.drawdown_accumulation
        if not da_config.enabled:
            log.info("Drawdown accumulation disabled, skipping cycle")
            return

        broker = self.brokers.get("alpaca")
        if not broker:
            log.warning("No Alpaca broker for drawdown accumulation monitor")
            return

        portfolio = await broker.get_account()

        # --- Track portfolio drawdown from high watermark ---
        await self._track_portfolio_drawdown(portfolio.equity)

        # --- Check strategy allocation limit ---
        strategy_value = await self.repo.get_strategy_total_value(
            source_prefix=f"monitor:{self.monitor_id}",
            symbols=da_config.watchlist,
        )
        strategy_pct = strategy_value / portfolio.equity if portfolio.equity > 0 else 0
        if strategy_pct >= da_config.max_portfolio_pct:
            log.info(
                f"Drawdown accumulation at {strategy_pct:.1%} of portfolio "
                f"(limit: {da_config.max_portfolio_pct:.0%}), skipping buys"
            )
            # Still check profit-taking even when at limit
            await self._check_profit_taking(broker, portfolio, da_config)
            return

        # --- Evaluate each symbol ---
        for symbol in da_config.watchlist:
            try:
                # Get last buy date for cooldown
                last_buy = await self.repo.get_last_buy_date(
                    symbol, source_prefix=f"monitor:{self.monitor_id}"
                )

                # Get current position % change for profit-taking
                position_pct_change = self._get_position_pct_change(portfolio, symbol)

                signal = await evaluate_symbol(
                    symbol=symbol,
                    config=da_config,
                    last_buy_date=last_buy,
                    position_pct_change=position_pct_change,
                )

                if signal is None:
                    continue

                # Log the signal as an agent decision
                await self.repo.insert_agent_decision(
                    agent_type="drawdown_accumulation",
                    symbol=symbol,
                    action=signal.action,
                    confidence=0.8 if signal.in_drawdown else 0.6,
                    reasoning=signal.reasoning,
                    signals_json=json.dumps({
                        "current_price": signal.current_price,
                        "high_252": signal.high_252,
                        "drawdown_pct": round(signal.drawdown_pct, 2),
                        "in_drawdown": signal.in_drawdown,
                        "buy_amount_usd": signal.buy_amount_usd,
                    }),
                    outcome="executed" if signal.action != "hold" else "hold",
                )

                if signal.action == "hold":
                    log.info(f"Drawdown {symbol}: HOLD — {signal.reasoning}")
                    continue

                if signal.action == "profit_take":
                    await self._execute_profit_take(broker, portfolio, symbol, signal, da_config)
                    continue

                # Buy actions (buy_normal or buy_drawdown)
                buy_amount = signal.buy_amount_usd

                # Cap to remaining allocation
                remaining_alloc = (da_config.max_portfolio_pct * portfolio.equity) - strategy_value
                if remaining_alloc <= 0:
                    log.info(f"Drawdown {symbol}: allocation limit reached, skipping")
                    continue
                buy_amount = min(buy_amount, remaining_alloc)

                # Calculate quantity
                qty = buy_amount / signal.current_price
                if qty < 0.01:
                    log.info(f"Drawdown {symbol}: quantity too small ({qty:.4f}), skipping")
                    continue

                # Submit buy order
                order = OrderRequest(
                    symbol=symbol,
                    side=Side.BUY,
                    quantity=round(qty, 2),
                    order_type=OrderType.MARKET,
                    platform=Platform.ALPACA,
                )

                result = await broker.submit_order(order)
                self.risk_manager.record_trade()

                trade_id = await self.repo.insert_trade(
                    order_id=result.order_id,
                    symbol=symbol,
                    side="buy",
                    quantity=order.quantity,
                    filled_price=result.filled_price,
                    platform="alpaca",
                    source=f"monitor:{self.monitor_id}",
                    strategy_name="drawdown_accumulation",
                    reasoning=signal.reasoning,
                    confidence=0.8 if signal.in_drawdown else 0.6,
                    status=result.status.value,
                )
                await self.repo.insert_monitor_trade(
                    self.monitor_id, trade_id, signal.current_price, order.quantity,
                )
                await self.repo.increment_monitor_trade(self.monitor_id)

                # Update strategy value for subsequent iterations
                strategy_value += buy_amount

                await self.event_bus.broadcast(WSEvent(
                    type=WSEventType.TRADE_EXECUTED,
                    data={
                        "symbol": symbol,
                        "side": "buy",
                        "quantity": order.quantity,
                        "filled_price": result.filled_price,
                        "source": f"monitor:{self.monitor_id}",
                        "strategy": "drawdown_accumulation",
                        "drawdown_pct": round(signal.drawdown_pct, 1),
                        "action_type": signal.action,
                    },
                ))

                log.info(
                    f"Drawdown {symbol}: {signal.action.upper()} "
                    f"{order.quantity:.2f} shares @ ${signal.current_price:.2f} "
                    f"(${buy_amount:.0f}, drawdown={signal.drawdown_pct:.1f}%)"
                )

            except Exception as e:
                log.warning(f"Drawdown monitor failed on {symbol}: {e}")

    async def _track_portfolio_drawdown(self, current_equity: float) -> None:
        """Track portfolio high watermark and current drawdown."""
        prev_hwm = await self.repo.get_high_watermark(platform="alpaca")
        new_hwm = max(prev_hwm, current_equity) if prev_hwm > 0 else current_equity

        drawdown_pct = 0.0
        if new_hwm > 0:
            drawdown_pct = ((new_hwm - current_equity) / new_hwm) * 100.0
            drawdown_pct = max(0.0, drawdown_pct)

        await self.repo.insert_portfolio_drawdown(
            platform="alpaca",
            equity=current_equity,
            high_watermark=new_hwm,
            drawdown_pct=round(drawdown_pct, 4),
        )

        if drawdown_pct > 5.0:
            log.warning(
                f"Portfolio drawdown: {drawdown_pct:.1f}% from peak "
                f"(equity=${current_equity:.0f}, HWM=${new_hwm:.0f})"
            )

    def _get_position_pct_change(self, portfolio, symbol: str) -> float | None:
        """Get the percentage change on an existing position."""
        for pos in portfolio.positions:
            if pos.symbol == symbol and pos.quantity > 0:
                if pos.avg_entry_price > 0:
                    return ((pos.current_price - pos.avg_entry_price) / pos.avg_entry_price) * 100.0
        return None

    async def _execute_profit_take(self, broker, portfolio, symbol, signal, da_config) -> None:
        """Execute a partial profit-take sell."""
        for pos in portfolio.positions:
            if pos.symbol == symbol and pos.quantity > 0:
                sell_qty = round(pos.quantity * da_config.profit_take_fraction, 2)
                if sell_qty < 0.01:
                    log.info(f"Drawdown {symbol}: profit-take qty too small, skipping")
                    return

                order = OrderRequest(
                    symbol=symbol,
                    side=Side.SELL,
                    quantity=sell_qty,
                    order_type=OrderType.MARKET,
                    platform=Platform.ALPACA,
                )

                result = await broker.submit_order(order)
                self.risk_manager.record_trade()

                pnl = None
                if result.filled_price and pos.avg_entry_price > 0:
                    pnl = (result.filled_price - pos.avg_entry_price) * sell_qty

                trade_id = await self.repo.insert_trade(
                    order_id=result.order_id,
                    symbol=symbol,
                    side="sell",
                    quantity=sell_qty,
                    filled_price=result.filled_price,
                    platform="alpaca",
                    source=f"monitor:{self.monitor_id}",
                    strategy_name="drawdown_accumulation",
                    reasoning=signal.reasoning,
                    confidence=0.7,
                    status=result.status.value,
                )
                await self.repo.insert_monitor_trade(
                    self.monitor_id, trade_id, signal.current_price, sell_qty,
                )
                await self.repo.increment_monitor_trade(self.monitor_id, pnl=pnl)

                await self.event_bus.broadcast(WSEvent(
                    type=WSEventType.TRADE_EXECUTED,
                    data={
                        "symbol": symbol,
                        "side": "sell",
                        "quantity": sell_qty,
                        "filled_price": result.filled_price,
                        "source": f"monitor:{self.monitor_id}",
                        "strategy": "drawdown_accumulation",
                        "action_type": "profit_take",
                        "pnl": pnl,
                    },
                ))

                log.info(
                    f"Drawdown {symbol}: PROFIT TAKE — sold {sell_qty:.2f} shares "
                    f"(P&L: ${pnl:.2f})" if pnl else
                    f"Drawdown {symbol}: PROFIT TAKE — sold {sell_qty:.2f} shares"
                )
                return

    async def _check_profit_taking(self, broker, portfolio, da_config) -> None:
        """Check all watchlist positions for profit-taking even at allocation limit."""
        for symbol in da_config.watchlist:
            pct_change = self._get_position_pct_change(portfolio, symbol)
            if pct_change is not None and pct_change >= da_config.profit_take_pct:
                signal = type("Signal", (), {
                    "current_price": 0,
                    "reasoning": (
                        f"Position up {pct_change:.1f}% (threshold: {da_config.profit_take_pct}%). "
                        f"Taking {da_config.profit_take_fraction*100:.0f}% off the table."
                    ),
                })()
                # Get current price for the signal
                for pos in portfolio.positions:
                    if pos.symbol == symbol:
                        signal.current_price = pos.current_price
                        break
                await self._execute_profit_take(broker, portfolio, symbol, signal, da_config)
