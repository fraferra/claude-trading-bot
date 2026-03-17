"""Short selling composite scorer — technical + fundamental signals.

Scores range from -1.0 (strong short) to 0.0 (no signal).
Each signal contributes a negative weight when triggered.
An uptrend penalty (+0.15) is applied when price > SMA(200) to avoid
shorting into strong uptrends.

Includes a broad market screener that pulls the S&P 500 + NASDAQ-100
universe and pre-filters for overbought conditions before running
detailed scoring.
"""

from __future__ import annotations

import asyncio
from functools import partial

import pandas as pd
import yfinance as yf

from trading_bot.models import ShortSignals
from trading_bot.utils.logging import log


def compute_rsi(closes, period: int = 14) -> float | None:
    """Compute RSI from a pandas Series of close prices."""
    if len(closes) < period + 1:
        return None
    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    last_loss = loss.iloc[-1]
    if last_loss == 0:
        return 100.0
    rs = gain.iloc[-1] / last_loss
    return 100 - (100 / (1 + rs))


def compute_bollinger_pct_b(closes, period: int = 20, num_std: float = 2.0) -> float | None:
    """Compute Bollinger Band %B: (price - lower) / (upper - lower)."""
    if len(closes) < period:
        return None
    sma = closes.rolling(period).mean()
    std = closes.rolling(period).std()
    upper = sma + num_std * std
    lower = sma - num_std * std
    band_width = upper.iloc[-1] - lower.iloc[-1]
    if band_width == 0:
        return 0.5
    return (closes.iloc[-1] - lower.iloc[-1]) / band_width


def compute_atr(highs, lows, closes, period: int = 14) -> float | None:
    """Compute Average True Range."""
    if len(closes) < period + 1:
        return None
    import pandas as pd

    prev_close = closes.shift(1)
    tr = pd.concat([
        highs - lows,
        (highs - prev_close).abs(),
        (lows - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    return float(atr.iloc[-1])


def compute_volume_ratio(volumes, period: int = 20) -> float | None:
    """Current volume / average volume over period."""
    if len(volumes) < period:
        return None
    avg = volumes.rolling(period).mean().iloc[-1]
    if avg == 0:
        return None
    return float(volumes.iloc[-1] / avg)


def compute_macd_histogram(closes, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[float | None, bool]:
    """Compute MACD histogram and whether it's declining."""
    if len(closes) < slow + signal:
        return None, False
    ema_fast = closes.ewm(span=fast, adjust=False).mean()
    ema_slow = closes.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    hist_val = float(histogram.iloc[-1])
    declining = len(histogram) >= 2 and histogram.iloc[-1] < histogram.iloc[-2]
    return hist_val, declining


def compute_short_composite(signals: ShortSignals) -> tuple[float, dict[str, float]]:
    """Compute composite short score from individual signals.

    Returns (score, breakdown) where score is in [-1.0, 0.0].
    More negative = stronger short signal.
    """
    breakdown: dict[str, float] = {}
    score = 0.0

    # RSI(2) extreme overbought (mean reversion signal)
    if signals.rsi_2 is not None and signals.rsi_2 > 95:
        weight = -0.25
        breakdown["rsi_2_extreme"] = weight
        score += weight

    # Bollinger %B above upper band
    if signals.bb_pct_b is not None and signals.bb_pct_b > 1.0:
        weight = -0.20
        breakdown["bb_above_upper"] = weight
        score += weight

    # RSI(14) overbought
    if signals.rsi_14 is not None and signals.rsi_14 > 70:
        weight = -0.15
        breakdown["rsi_14_overbought"] = weight
        score += weight

    # MACD histogram declining from positive
    if signals.macd_histogram is not None and signals.macd_histogram > 0 and signals.macd_hist_declining:
        weight = -0.15
        breakdown["macd_declining"] = weight
        score += weight

    # Volume spike
    if signals.volume_ratio is not None and signals.volume_ratio > 1.5:
        weight = -0.10
        breakdown["volume_spike"] = weight
        score += weight

    # High P/E ratio
    if signals.pe_ratio is not None and signals.pe_ratio > 35:
        weight = -0.10
        breakdown["high_pe"] = weight
        score += weight

    # Uptrend penalty: price > SMA(200) — avoid shorting into strong uptrends
    if signals.price_vs_sma200 is not None and signals.price_vs_sma200 > 0:
        weight = 0.15
        breakdown["uptrend_penalty"] = weight
        score += weight

    # Clamp to [-1.0, 0.0]
    score = max(-1.0, min(0.0, score))

    return score, breakdown


async def score_short(symbol: str) -> ShortSignals:
    """Fetch data and compute short score for a symbol."""
    loop = asyncio.get_event_loop()
    ticker = yf.Ticker(symbol)

    # Fetch 1 year of daily data for SMA(200)
    hist = await loop.run_in_executor(None, partial(ticker.history, period="1y"))
    if hist.empty or len(hist) < 30:
        return ShortSignals(symbol=symbol, short_score=0.0)

    closes = hist["Close"]
    highs = hist["High"]
    lows = hist["Low"]
    volumes = hist["Volume"]
    current_price = float(closes.iloc[-1])

    # Compute all signals
    rsi_2 = compute_rsi(closes, 2)
    rsi_14 = compute_rsi(closes, 14)
    bb_pct_b = compute_bollinger_pct_b(closes)
    macd_hist, macd_declining = compute_macd_histogram(closes)
    volume_ratio = compute_volume_ratio(volumes)
    atr_14 = compute_atr(highs, lows, closes, 14)

    # Price vs SMA(200)
    sma_200 = float(closes.rolling(200).mean().iloc[-1]) if len(closes) >= 200 else None
    price_vs_sma200 = (current_price / sma_200 - 1.0) if sma_200 else None

    # Fundamentals: P/E ratio
    pe_ratio = None
    try:
        info = await loop.run_in_executor(None, lambda: ticker.info)
        pe_ratio = info.get("trailingPE")
    except Exception:
        pass

    signals = ShortSignals(
        symbol=symbol,
        rsi_2=round(rsi_2, 2) if rsi_2 is not None else None,
        rsi_14=round(rsi_14, 2) if rsi_14 is not None else None,
        bb_pct_b=round(bb_pct_b, 4) if bb_pct_b is not None else None,
        macd_histogram=round(macd_hist, 4) if macd_hist is not None else None,
        macd_hist_declining=macd_declining,
        volume_ratio=round(volume_ratio, 2) if volume_ratio is not None else None,
        price_vs_sma200=round(price_vs_sma200, 4) if price_vs_sma200 is not None else None,
        atr_14=round(atr_14, 2) if atr_14 is not None else None,
        pe_ratio=round(pe_ratio, 2) if pe_ratio is not None else None,
        current_price=round(current_price, 2),
    )

    score, breakdown = compute_short_composite(signals)
    signals.short_score = round(score, 4)
    signals.signal_breakdown = breakdown

    return signals


# ---------------------------------------------------------------------------
# Stock universe: S&P 500 + NASDAQ-100 (~500 unique tickers)
# ---------------------------------------------------------------------------

async def get_broad_universe() -> list[str]:
    """Fetch S&P 500 + NASDAQ-100 tickers from Wikipedia."""
    loop = asyncio.get_event_loop()
    tickers: set[str] = set()

    # S&P 500
    try:
        tables = await loop.run_in_executor(
            None,
            lambda: pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"),
        )
        if tables:
            sp500 = tables[0]
            col = "Symbol" if "Symbol" in sp500.columns else sp500.columns[0]
            tickers.update(
                s.strip().replace(".", "-") for s in sp500[col].dropna().tolist()
            )
    except Exception as e:
        log.warning(f"Failed to fetch S&P 500 list: {e}")

    # NASDAQ-100 supplement
    try:
        tables = await loop.run_in_executor(
            None,
            lambda: pd.read_html(
                "https://en.wikipedia.org/wiki/Nasdaq-100",
                match="Ticker",
            ),
        )
        if tables:
            ndx = tables[0]
            col = "Ticker" if "Ticker" in ndx.columns else ndx.columns[1]
            tickers.update(
                s.strip().replace(".", "-") for s in ndx[col].dropna().tolist()
            )
    except Exception as e:
        log.warning(f"Failed to fetch NASDAQ-100 list: {e}")

    # Fallback: if we got nothing, return a reasonable set
    if len(tickers) < 50:
        log.warning("Universe fetch returned too few tickers; using fallback set")
        tickers.update([
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B",
            "JPM", "V", "UNH", "XOM", "JNJ", "WMT", "MA", "PG", "HD", "CVX",
            "MRK", "ABBV", "LLY", "AVGO", "PEP", "KO", "COST", "TMO", "MCD",
            "CSCO", "ACN", "ABT", "DHR", "CRM", "NFLX", "AMD", "INTC", "QCOM",
            "TXN", "NEE", "BA", "UNP", "LOW", "INTU", "AMAT", "ISRG", "BKNG",
            "GS", "AXP", "CAT", "DE", "SYK", "PANW", "PLTR", "CRWD", "SNOW",
        ])

    return sorted(tickers)


# ---------------------------------------------------------------------------
# Fast pre-filter: batch-screen the broad universe for overbought stocks
# ---------------------------------------------------------------------------

async def prefilter_overbought(
    tickers: list[str],
    rsi_min: float = 65.0,
    near_high_pct: float = 0.95,
    max_candidates: int = 40,
) -> list[dict]:
    """Quick batch pre-screen for overbought conditions.

    Uses yfinance batch download (3mo daily data for all tickers at once)
    to compute RSI(14) and proximity to recent high. Returns candidates
    sorted by RSI descending.
    """
    loop = asyncio.get_event_loop()

    log.info(f"Short pre-filter: batch-downloading data for {len(tickers)} tickers...")
    try:
        data = await loop.run_in_executor(
            None,
            lambda: yf.download(
                " ".join(tickers),
                period="3mo",
                group_by="ticker",
                progress=False,
                threads=True,
            ),
        )
    except Exception as e:
        log.error(f"Batch download failed: {e}")
        return []

    if data.empty:
        return []

    candidates: list[dict] = []
    single_ticker = len(tickers) == 1

    for sym in tickers:
        try:
            if single_ticker:
                closes = data["Close"].dropna()
            else:
                if sym not in data.columns.get_level_values(0):
                    continue
                closes = data[sym]["Close"].dropna()

            if len(closes) < 20:
                continue

            current_price = float(closes.iloc[-1])
            high_period = float(closes.max())

            # RSI(14) quick calculation
            delta = closes.diff()
            gain = delta.where(delta > 0, 0.0).rolling(14).mean()
            loss_s = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
            last_loss = float(loss_s.iloc[-1])
            rsi = 100.0 if last_loss == 0 else 100 - (100 / (1 + float(gain.iloc[-1]) / last_loss))

            near_high = current_price / high_period if high_period > 0 else 0

            # Pre-filter: either overbought RSI OR near period high
            qualifies = False
            reasons = []
            if rsi >= rsi_min:
                qualifies = True
                reasons.append(f"RSI={rsi:.1f}")
            if near_high >= near_high_pct:
                qualifies = True
                reasons.append(f"near_high={near_high:.1%}")

            if qualifies:
                candidates.append({
                    "symbol": sym,
                    "rsi_14": round(rsi, 2),
                    "near_high_pct": round(near_high, 4),
                    "current_price": round(current_price, 2),
                    "reason": ", ".join(reasons),
                })
        except Exception:
            continue

    # Sort by RSI descending (most overbought first), cap results
    candidates.sort(key=lambda c: c["rsi_14"], reverse=True)
    result = candidates[:max_candidates]
    log.info(
        f"Short pre-filter: {len(candidates)} passed from {len(tickers)}, "
        f"returning top {len(result)}"
    )
    return result


# ---------------------------------------------------------------------------
# Broad market scan: universe → pre-filter → detailed scoring
# ---------------------------------------------------------------------------

async def broad_market_short_scan(
    rsi_min: float = 65.0,
    near_high_pct: float = 0.95,
    max_prefilter: int = 40,
) -> list[ShortSignals]:
    """Full market scan: fetch universe → pre-filter → detail-score survivors."""
    universe = await get_broad_universe()
    log.info(f"Short broad scan: universe has {len(universe)} tickers")

    # Pre-filter down to overbought candidates
    candidates = await prefilter_overbought(
        universe, rsi_min=rsi_min, near_high_pct=near_high_pct,
        max_candidates=max_prefilter,
    )

    if not candidates:
        log.info("Short broad scan: no candidates passed pre-filter")
        return []

    # Detailed scoring on survivors
    symbols = [c["symbol"] for c in candidates]
    log.info(f"Short broad scan: detailed scoring on {len(symbols)} candidates")

    sem = asyncio.Semaphore(5)

    async def _score(sym: str):
        async with sem:
            return await score_short(sym)

    results = await asyncio.gather(
        *[_score(s) for s in symbols], return_exceptions=True,
    )

    scored: list[ShortSignals] = []
    for r in results:
        if isinstance(r, Exception):
            log.warning(f"Detailed scoring failed: {r}")
            continue
        scored.append(r)

    # Sort by short_score ascending (most negative = strongest short)
    scored.sort(key=lambda s: s.short_score)
    return scored
