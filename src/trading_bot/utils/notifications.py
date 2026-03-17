"""Telegram notification service for the trading bot."""

from __future__ import annotations

import asyncio
from datetime import datetime

import httpx

from trading_bot.utils.logging import log


async def send_telegram(config, message: str, parse_mode: str = "Markdown") -> bool:
    """Send a Telegram message. Returns True on success."""
    if not config.telegram.enabled:
        return False

    url = f"https://api.telegram.org/bot{config.telegram.bot_token}/sendMessage"
    payload = {
        "chat_id": config.telegram.chat_id,
        "text": message,
        "parse_mode": parse_mode,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                return True
            log.warning(f"Telegram API returned {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        log.warning(f"Telegram send failed: {e}")
        return False


async def notify_trade(config, symbol: str, side: str, quantity: float,
                       price: float | None, source: str) -> None:
    """Send trade execution notification."""
    if not config.telegram.notify_trades:
        return
    emoji = "🟢" if side == "buy" else "🔴"
    price_str = f"${price:.2f}" if price else "pending"
    msg = (
        f"{emoji} *Trade Executed*\n"
        f"Symbol: `{symbol}`\n"
        f"Side: {side.upper()}\n"
        f"Qty: {quantity}\n"
        f"Price: {price_str}\n"
        f"Source: {source}"
    )
    await send_telegram(config, msg)


async def notify_error(config, source: str, error: str) -> None:
    """Send error notification."""
    if not config.telegram.notify_errors:
        return
    msg = (
        f"🚨 *Error: {source}*\n"
        f"```\n{error[:500]}\n```"
    )
    await send_telegram(config, msg)


async def notify_daily_summary(config, equity: float, daily_pnl: float,
                                positions_count: int, trades_today: int) -> None:
    """Send daily portfolio summary."""
    if not config.telegram.daily_summary:
        return
    pnl_emoji = "📈" if daily_pnl >= 0 else "📉"
    msg = (
        f"📊 *Daily Summary — {datetime.now().strftime('%b %d')}*\n\n"
        f"Equity: ${equity:,.2f}\n"
        f"{pnl_emoji} Daily P&L: ${daily_pnl:+,.2f}\n"
        f"Open Positions: {positions_count}\n"
        f"Trades Today: {trades_today}"
    )
    await send_telegram(config, msg)
