"""Drawdown-based accumulation strategy for leveraged ETFs.

Inspired by the TQQQ drawdown accumulation approach:
- Small DCA buys during normal conditions
- Aggressive buys during significant drawdowns
- Partial profit-taking when positions are up significantly
- Time-based cooldowns between orders to prevent overtrading
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta

import yfinance as yf

from trading_bot.config import DrawdownAccumulationConfig
from trading_bot.utils.logging import log


@dataclass
class DrawdownSignal:
    """Signal data for a single ETF."""

    symbol: str
    current_price: float
    high_252: float
    drawdown_pct: float  # Current drawdown from 252-day high (positive = drawdown)
    in_drawdown: bool  # True if drawdown >= threshold
    buy_amount_usd: float  # Suggested buy amount
    action: str  # "buy_normal", "buy_drawdown", "profit_take", "hold"
    reasoning: str


def compute_max_drawdown(prices: list[float], lookback: int = 252) -> tuple[float, float]:
    """Compute the current drawdown from the rolling high.

    Returns (drawdown_pct, high_price).
    drawdown_pct is positive when price is below the high (e.g., 25.0 means 25% down).
    """
    if not prices or len(prices) < 2:
        return 0.0, 0.0

    window = prices[-lookback:] if len(prices) > lookback else prices
    high_price = max(window)
    current_price = window[-1]

    if high_price <= 0:
        return 0.0, 0.0

    drawdown_pct = ((high_price - current_price) / high_price) * 100.0
    return max(0.0, drawdown_pct), high_price


async def evaluate_symbol(
    symbol: str,
    config: DrawdownAccumulationConfig,
    last_buy_date: datetime | None = None,
    position_pct_change: float | None = None,
) -> DrawdownSignal | None:
    """Evaluate a single symbol for drawdown accumulation signals.

    Args:
        symbol: Ticker symbol (e.g., "TQQQ")
        config: Strategy configuration
        last_buy_date: When the last buy order was filled for this symbol
        position_pct_change: Current position % change (for profit-taking)
    """
    loop = asyncio.get_event_loop()
    try:
        ticker = await loop.run_in_executor(
            None, lambda: yf.Ticker(symbol)
        )
        hist = await loop.run_in_executor(
            None, lambda: ticker.history(period="1y")
        )

        if hist.empty or len(hist) < 10:
            log.warning(f"Drawdown: insufficient data for {symbol}")
            return None

        prices = hist["Close"].tolist()
        current_price = prices[-1]
        drawdown_pct, high_price = compute_max_drawdown(prices, config.drawdown_lookback_days)
        in_drawdown = drawdown_pct >= config.drawdown_threshold_pct

        now = datetime.now()

        # 1. Check profit-taking first
        if position_pct_change is not None and position_pct_change >= config.profit_take_pct:
            return DrawdownSignal(
                symbol=symbol,
                current_price=current_price,
                high_252=high_price,
                drawdown_pct=drawdown_pct,
                in_drawdown=in_drawdown,
                buy_amount_usd=0.0,
                action="profit_take",
                reasoning=(
                    f"Position up {position_pct_change:.1f}% (threshold: {config.profit_take_pct}%). "
                    f"Taking {config.profit_take_fraction*100:.0f}% off the table."
                ),
            )

        # 2. Check cooldown
        if last_buy_date:
            days_since_buy = (now - last_buy_date).days
            required_days = (
                config.min_days_between_drawdown_buys if in_drawdown
                else config.min_days_between_buys
            )
            if days_since_buy < required_days:
                return DrawdownSignal(
                    symbol=symbol,
                    current_price=current_price,
                    high_252=high_price,
                    drawdown_pct=drawdown_pct,
                    in_drawdown=in_drawdown,
                    buy_amount_usd=0.0,
                    action="hold",
                    reasoning=(
                        f"Cooldown: {days_since_buy}d since last buy, "
                        f"need {required_days}d. Drawdown: {drawdown_pct:.1f}%"
                    ),
                )

        # 3. Determine buy amount
        if in_drawdown:
            return DrawdownSignal(
                symbol=symbol,
                current_price=current_price,
                high_252=high_price,
                drawdown_pct=drawdown_pct,
                in_drawdown=True,
                buy_amount_usd=config.drawdown_buy_usd,
                action="buy_drawdown",
                reasoning=(
                    f"DRAWDOWN BUY: {symbol} is {drawdown_pct:.1f}% below "
                    f"252-day high of ${high_price:.2f}. "
                    f"Aggressive accumulation: ${config.drawdown_buy_usd:.0f}"
                ),
            )
        else:
            return DrawdownSignal(
                symbol=symbol,
                current_price=current_price,
                high_252=high_price,
                drawdown_pct=drawdown_pct,
                in_drawdown=False,
                buy_amount_usd=config.normal_buy_usd,
                action="buy_normal",
                reasoning=(
                    f"DCA BUY: {symbol} at ${current_price:.2f}, "
                    f"{drawdown_pct:.1f}% from 252-day high. "
                    f"Normal accumulation: ${config.normal_buy_usd:.0f}"
                ),
            )

    except Exception as e:
        log.warning(f"Drawdown evaluation failed for {symbol}: {e}")
        return None
