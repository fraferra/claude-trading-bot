"""Position Guard Monitor — automated stop-loss, trailing stops, and take-profit."""

from __future__ import annotations

from trading_bot.monitors.base import BaseMonitor
from trading_bot.models import (
    OrderRequest, OrderType, Platform, Side, WSEvent, WSEventType,
)
from trading_bot.utils.logging import log


class PositionGuardMonitor(BaseMonitor):
    """Monitors all open positions and enforces stop-loss, trailing stop, and take-profit rules."""

    monitor_type = "position_guard"

    def get_interval_seconds(self) -> int:
        return self.config.position_guard.scan_interval_minutes * 60

    async def run_cycle(self) -> None:
        cfg = self.config.position_guard
        if not cfg.enabled:
            return

        alpaca = self.brokers.get("alpaca")
        if not alpaca:
            return

        account = await alpaca.get_account()
        positions = account.positions

        if not positions:
            return

        excluded = set(s.upper() for s in cfg.exclude_symbols)

        for pos in positions:
            if pos.symbol in excluded:
                continue

            is_short = pos.quantity < 0
            if is_short and not cfg.enable_for_shorts:
                continue

            current_price = pos.current_price
            entry_price = pos.avg_entry_price

            if entry_price <= 0 or current_price <= 0:
                continue

            # Calculate P&L percentage
            if is_short:
                pnl_pct = ((entry_price - current_price) / entry_price) * 100
            else:
                pnl_pct = ((current_price - entry_price) / entry_price) * 100

            # --- Hard Stop Loss ---
            if pnl_pct <= -cfg.stop_loss_pct:
                log.warning(
                    f"STOP LOSS triggered for {pos.symbol}: "
                    f"P&L {pnl_pct:.1f}% <= -{cfg.stop_loss_pct}%"
                )
                await self._exit_position(pos, "stop_loss", pnl_pct)
                continue

            # --- Trailing Stop ---
            hw = await self.repo.get_high_watermark_price(pos.symbol)
            if hw:
                high_price = max(hw["high_price"], current_price) if not is_short else min(hw["high_price"], current_price)
            else:
                high_price = current_price

            # Update high watermark
            await self.repo.upsert_high_watermark(pos.symbol, high_price if not is_short else current_price, entry_price)

            if not is_short and high_price > entry_price:
                drop_from_high = ((high_price - current_price) / high_price) * 100
                if drop_from_high >= cfg.trailing_stop_pct:
                    log.warning(
                        f"TRAILING STOP triggered for {pos.symbol}: "
                        f"dropped {drop_from_high:.1f}% from high ${high_price:.2f}"
                    )
                    await self._exit_position(pos, "trailing_stop", pnl_pct)
                    continue

            # --- Take Profit ---
            if pnl_pct >= cfg.take_profit_pct:
                if cfg.partial_take_profit:
                    sell_qty = abs(pos.quantity) * cfg.partial_take_fraction
                    if sell_qty >= 0.01:
                        log.info(
                            f"TAKE PROFIT (partial) for {pos.symbol}: "
                            f"P&L {pnl_pct:.1f}%, selling {cfg.partial_take_fraction:.0%}"
                        )
                        await self._sell_partial(pos, sell_qty, "take_profit_partial", pnl_pct)
                else:
                    log.info(
                        f"TAKE PROFIT (full) for {pos.symbol}: P&L {pnl_pct:.1f}%"
                    )
                    await self._exit_position(pos, "take_profit", pnl_pct)

    async def _exit_position(self, pos, reason: str, pnl_pct: float) -> None:
        """Fully exit a position."""
        alpaca = self.brokers["alpaca"]
        qty = abs(pos.quantity)
        side = Side.SELL if pos.quantity > 0 else Side.BUY

        order = OrderRequest(
            symbol=pos.symbol,
            side=side,
            quantity=qty,
            order_type=OrderType.MARKET,
            platform=Platform.ALPACA,
        )
        try:
            result = await alpaca.submit_order(order)
            trade_id = await self.repo.insert_trade(
                order_id=result.order_id,
                symbol=pos.symbol,
                side=side.value,
                quantity=qty,
                filled_price=result.filled_price,
                platform="alpaca",
                source=f"guard:{reason}",
                reasoning=f"Position guard: {reason} at {pnl_pct:.1f}%",
                status=result.status.value,
            )
            await self.repo.delete_high_watermark(pos.symbol)
            await self.repo.increment_monitor_trade(self.monitor_id)

            await self.event_bus.broadcast(WSEvent(
                type=WSEventType.TRADE_EXECUTED,
                data={
                    "symbol": pos.symbol,
                    "side": side.value,
                    "quantity": qty,
                    "reason": reason,
                    "pnl_pct": round(pnl_pct, 2),
                    "source": "position_guard",
                },
            ))

            # Send telegram notification if available
            await self._notify_telegram(pos.symbol, reason, pnl_pct, qty, result.filled_price)

            log.info(f"Position guard {reason}: sold {qty} {pos.symbol} (trade {trade_id})")
        except Exception as e:
            log.error(f"Position guard failed to exit {pos.symbol}: {e}")

    async def _sell_partial(self, pos, qty: float, reason: str, pnl_pct: float) -> None:
        """Sell a partial position."""
        alpaca = self.brokers["alpaca"]
        side = Side.SELL if pos.quantity > 0 else Side.BUY

        order = OrderRequest(
            symbol=pos.symbol,
            side=side,
            quantity=round(qty, 4),
            order_type=OrderType.MARKET,
            platform=Platform.ALPACA,
        )
        try:
            result = await alpaca.submit_order(order)
            await self.repo.insert_trade(
                order_id=result.order_id,
                symbol=pos.symbol,
                side=side.value,
                quantity=round(qty, 4),
                filled_price=result.filled_price,
                platform="alpaca",
                source=f"guard:{reason}",
                reasoning=f"Position guard: {reason} at {pnl_pct:.1f}%",
                status=result.status.value,
            )
            await self.repo.increment_monitor_trade(self.monitor_id)

            await self.event_bus.broadcast(WSEvent(
                type=WSEventType.TRADE_EXECUTED,
                data={
                    "symbol": pos.symbol,
                    "side": side.value,
                    "quantity": round(qty, 4),
                    "reason": reason,
                    "pnl_pct": round(pnl_pct, 2),
                    "source": "position_guard",
                },
            ))
            log.info(f"Position guard {reason}: sold {qty:.4f} {pos.symbol}")
        except Exception as e:
            log.error(f"Position guard partial sell failed for {pos.symbol}: {e}")

    async def _notify_telegram(self, symbol: str, reason: str, pnl_pct: float, qty: float, price: float | None) -> None:
        """Send telegram notification if configured."""
        try:
            from trading_bot.utils.notifications import send_telegram
            emoji = "🛑" if "stop" in reason else "💰"
            msg = (
                f"{emoji} *Position Guard: {reason.upper()}*\n"
                f"Symbol: `{symbol}`\n"
                f"P&L: {pnl_pct:+.1f}%\n"
                f"Qty: {qty}\n"
                f"Price: ${price:.2f}" if price else ""
            )
            await send_telegram(self.config, msg)
        except Exception:
            pass  # Telegram not configured or failed
