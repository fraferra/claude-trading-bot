"""Crypto market data fetching and technical indicator computation."""

from __future__ import annotations

import asyncio
import math
from datetime import datetime
from functools import partial

from trading_bot.config import CryptoConfig
from trading_bot.models import Action, CryptoBarData, CryptoTechnicalSignals
from trading_bot.utils.logging import log


async def get_crypto_bars(
    api_key: str,
    secret_key: str,
    symbol: str,
    timeframe: str = "15Min",
    limit: int = 100,
) -> list[CryptoBarData]:
    """Fetch historical bars for a crypto pair via Alpaca."""
    from alpaca.data.historical import CryptoHistoricalDataClient
    from alpaca.data.requests import CryptoBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

    loop = asyncio.get_event_loop()
    client = CryptoHistoricalDataClient(api_key=api_key, secret_key=secret_key)

    # Map timeframe string to TimeFrame object
    tf_map = {
        "1Min": TimeFrame(1, TimeFrameUnit.Minute),
        "5Min": TimeFrame(5, TimeFrameUnit.Minute),
        "15Min": TimeFrame(15, TimeFrameUnit.Minute),
        "30Min": TimeFrame(30, TimeFrameUnit.Minute),
        "1Hour": TimeFrame(1, TimeFrameUnit.Hour),
        "4Hour": TimeFrame(4, TimeFrameUnit.Hour),
        "1Day": TimeFrame(1, TimeFrameUnit.Day),
    }
    tf = tf_map.get(timeframe, TimeFrame(15, TimeFrameUnit.Minute))

    # Alpaca crypto uses symbol format without slash: "BTC/USD" -> "BTC/USD"
    req = CryptoBarsRequest(symbol_or_symbols=symbol, timeframe=tf, limit=limit)

    bars_data = await loop.run_in_executor(
        None, partial(client.get_crypto_bars, req)
    )

    bars = []
    if symbol in bars_data:
        for bar in bars_data[symbol]:
            bars.append(CryptoBarData(
                symbol=symbol,
                timestamp=bar.timestamp,
                open=float(bar.open),
                high=float(bar.high),
                low=float(bar.low),
                close=float(bar.close),
                volume=float(bar.volume),
                vwap=float(bar.vwap) if bar.vwap else 0.0,
            ))

    return bars


async def get_crypto_latest_quote(
    api_key: str, secret_key: str, symbol: str
) -> float:
    """Get latest mid-price for a crypto pair via Alpaca."""
    from alpaca.data.historical import CryptoHistoricalDataClient
    from alpaca.data.requests import CryptoLatestQuoteRequest

    loop = asyncio.get_event_loop()
    client = CryptoHistoricalDataClient(api_key=api_key, secret_key=secret_key)

    req = CryptoLatestQuoteRequest(symbol_or_symbols=symbol)
    quotes = await loop.run_in_executor(
        None, partial(client.get_crypto_latest_quote, req)
    )

    quote = quotes.get(symbol)
    if quote:
        bid = float(quote.bid_price) if quote.bid_price else 0.0
        ask = float(quote.ask_price) if quote.ask_price else 0.0
        if bid and ask:
            return (bid + ask) / 2
        return ask or bid
    return 0.0


def compute_crypto_technicals(
    bars: list[CryptoBarData], config: CryptoConfig
) -> CryptoTechnicalSignals:
    """Compute RSI, MACD, Bollinger Bands from bar data. Pure function."""
    if not bars:
        return CryptoTechnicalSignals(symbol="unknown")

    symbol = bars[0].symbol
    closes = [b.close for b in bars]
    current_price = closes[-1] if closes else 0.0

    # --- RSI ---
    rsi = _compute_rsi(closes, config.rsi_period)

    # --- MACD ---
    macd_line, signal_line, histogram = _compute_macd(closes, 12, 26, 9)

    # --- Bollinger Bands ---
    bb_upper, bb_middle, bb_lower, bb_pct_b = _compute_bollinger(
        closes, config.bb_period, config.bb_std
    )

    # --- Scoring ---

    # Momentum score: combine RSI trend + MACD histogram
    momentum = 0.0
    if rsi is not None:
        # RSI above 50 = bullish momentum, below 50 = bearish
        momentum += (rsi - 50) / 50  # -1 to 1
    if histogram is not None:
        # Normalize histogram relative to price
        momentum += max(-1.0, min(1.0, histogram / (current_price * 0.002) if current_price > 0 else 0.0))
    momentum = max(-1.0, min(1.0, momentum / 2))  # Average

    # Mean-reversion score: based on BB %B
    mean_rev = 0.0
    if bb_pct_b is not None:
        # Below 0.2 = oversold (buy signal), above 0.8 = overbought (sell signal)
        if bb_pct_b < 0.2:
            mean_rev = (0.2 - bb_pct_b) / 0.2  # 0 to 1 (buy signal)
        elif bb_pct_b > 0.8:
            mean_rev = -(bb_pct_b - 0.8) / 0.2  # -1 to 0 (sell signal)

    # Composite signal: weighted average
    composite = 0.5 * momentum + 0.5 * mean_rev
    composite = max(-1.0, min(1.0, composite))

    # Direction
    if composite >= config.min_signal_score:
        direction = Action.BUY
    elif composite <= -config.min_signal_score:
        direction = Action.SELL
    else:
        direction = Action.HOLD

    return CryptoTechnicalSignals(
        symbol=symbol,
        rsi_14=rsi,
        macd=macd_line,
        macd_signal=signal_line,
        macd_histogram=histogram,
        bb_upper=bb_upper,
        bb_middle=bb_middle,
        bb_lower=bb_lower,
        bb_pct_b=bb_pct_b,
        momentum_score=round(momentum, 4),
        mean_reversion_score=round(mean_rev, 4),
        composite_signal=round(composite, 4),
        signal_direction=direction,
        current_price=current_price,
        timestamp=bars[-1].timestamp if bars else datetime.now(),
    )


def _compute_rsi(closes: list[float], period: int = 14) -> float | None:
    """Compute RSI using exponential moving average of gains/losses."""
    if len(closes) < period + 1:
        return None

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]

    # Initial average
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    # Smoothed (EMA-like)
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def _compute_macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[float | None, float | None, float | None]:
    """Compute MACD line, signal line, and histogram."""
    if len(closes) < slow + signal:
        return None, None, None

    fast_ema = _ema(closes, fast)
    slow_ema = _ema(closes, slow)

    if fast_ema is None or slow_ema is None:
        return None, None, None

    # Build MACD line series
    macd_series = []
    for i in range(len(closes)):
        f = _ema(closes[: i + 1], fast)
        s = _ema(closes[: i + 1], slow)
        if f is not None and s is not None:
            macd_series.append(f - s)

    if len(macd_series) < signal:
        return fast_ema - slow_ema, None, None

    macd_line = macd_series[-1]
    signal_line = _ema(macd_series, signal)

    if signal_line is not None:
        histogram = macd_line - signal_line
    else:
        histogram = None

    return round(macd_line, 6), round(signal_line, 6) if signal_line else None, round(histogram, 6) if histogram else None


def _compute_bollinger(
    closes: list[float], period: int = 20, num_std: float = 2.0
) -> tuple[float | None, float | None, float | None, float | None]:
    """Compute Bollinger Bands and %B."""
    if len(closes) < period:
        return None, None, None, None

    window = closes[-period:]
    middle = sum(window) / period
    variance = sum((x - middle) ** 2 for x in window) / period
    std = math.sqrt(variance)

    upper = middle + num_std * std
    lower = middle - num_std * std

    # %B = (price - lower) / (upper - lower)
    current = closes[-1]
    if upper != lower:
        pct_b = (current - lower) / (upper - lower)
    else:
        pct_b = 0.5

    return round(upper, 2), round(middle, 2), round(lower, 2), round(pct_b, 4)


def _ema(data: list[float], period: int) -> float | None:
    """Compute exponential moving average."""
    if len(data) < period:
        return None

    multiplier = 2 / (period + 1)
    ema_val = sum(data[:period]) / period

    for price in data[period:]:
        ema_val = (price - ema_val) * multiplier + ema_val

    return ema_val
