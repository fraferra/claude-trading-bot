"""Continuous non-linear stochastic regime classifier for crypto markets.

Mathematical foundation:
  Price dynamics are modelled as a discrete-time Ornstein-Uhlenbeck process
  (continuous-time limit: dX_t = κ(μ - X_t)dt + σ dW_t).

  For log-returns r_t, an AR(1) fit gives:
      r_{t+1} = a + b·r_t + ε_t

  where:
    b  = lag-1 autocorrelation ρ       (AR coefficient)
    κ  = -log(|ρ|)                     (mean-reversion speed per bar)
    sign(ρ) > 0  → trending            (positive autocorrelation)
    sign(ρ) < 0  → mean-reverting      (negative autocorrelation)

  Combined with rolling realized-vol percentile vs. historical distribution,
  these two quantities map directly onto the existing MarketRegime enum.

Module-level cache:
  The monitor writes here every cycle; the strategy reads synchronously.
  No broker/DB dependency — pure in-process state.
"""

from __future__ import annotations

import math
from datetime import datetime

from trading_bot.models import MarketRegime
from trading_bot.utils.logging import log


# ---------------------------------------------------------------------------
# Module-level regime cache  (monitor writes, strategy reads)
# ---------------------------------------------------------------------------

_regime_cache: dict[str, "RegimeState"] = {}


def update_regime_cache(symbol: str, state: "RegimeState") -> None:
    _regime_cache[symbol] = state


def get_regime(symbol: str) -> "RegimeState | None":
    return _regime_cache.get(symbol)


def clear_cache() -> None:
    _regime_cache.clear()


# ---------------------------------------------------------------------------
# Regime parameter table
# ---------------------------------------------------------------------------

# For each regime: (min_signal_multiplier, position_size_multiplier,
#                   momentum_weight, mean_rev_weight)
REGIME_PARAMS: dict[MarketRegime, dict[str, float]] = {
    MarketRegime.TRENDING_UP: {
        "min_signal_multiplier": 0.75,  # Lower bar — trend alignment
        "position_size_multiplier": 1.00,
        "momentum_weight": 0.75,
        "mean_rev_weight": 0.25,
    },
    MarketRegime.TRENDING_DOWN: {
        "min_signal_multiplier": 1.15,  # Higher bar — only strong counter-signals
        "position_size_multiplier": 0.70,
        "momentum_weight": 0.75,
        "mean_rev_weight": 0.25,
    },
    MarketRegime.MEAN_REVERTING: {
        "min_signal_multiplier": 0.85,
        "position_size_multiplier": 0.80,
        "momentum_weight": 0.25,  # Lean on BB mean-reversion
        "mean_rev_weight": 0.75,
    },
    MarketRegime.HIGH_VOLATILITY: {
        "min_signal_multiplier": 1.30,  # Much stronger signal required
        "position_size_multiplier": 0.40,  # Half-Kelly style reduction
        "momentum_weight": 0.50,
        "mean_rev_weight": 0.50,
    },
    MarketRegime.LOW_VOLATILITY: {
        "min_signal_multiplier": 0.90,
        "position_size_multiplier": 1.00,
        "momentum_weight": 0.50,
        "mean_rev_weight": 0.50,
    },
}


# ---------------------------------------------------------------------------
# Data class (defined here to avoid a circular models import)
# ---------------------------------------------------------------------------

class RegimeState:
    """Snapshot of the regime classification for one symbol."""

    __slots__ = (
        "symbol", "regime", "autocorr", "kappa",
        "vol_annualized", "vol_percentile", "trend_slope",
        "confidence", "timestamp",
    )

    def __init__(
        self,
        symbol: str,
        regime: MarketRegime,
        autocorr: float,
        kappa: float,
        vol_annualized: float,
        vol_percentile: float,
        trend_slope: float,
        confidence: float,
    ) -> None:
        self.symbol = symbol
        self.regime = regime
        self.autocorr = autocorr          # lag-1 return autocorrelation
        self.kappa = kappa                # OU speed (bars⁻¹); higher = faster reversion
        self.vol_annualized = vol_annualized
        self.vol_percentile = vol_percentile  # 0–1 vs. historical distribution
        self.trend_slope = trend_slope    # linear-regression slope of log-price
        self.confidence = confidence      # 0–1 classifier confidence
        self.timestamp = datetime.now()

    def params(self) -> dict[str, float]:
        return REGIME_PARAMS[self.regime]

    def __repr__(self) -> str:
        return (
            f"RegimeState({self.symbol} | {self.regime.value} | "
            f"ρ={self.autocorr:+.3f} κ={self.kappa:.3f} "
            f"vol_pct={self.vol_percentile:.2f} conf={self.confidence:.2f})"
        )


# ---------------------------------------------------------------------------
# Core math functions (pure, no I/O)
# ---------------------------------------------------------------------------

def _lag1_autocorr(series: list[float]) -> float:
    """Pearson lag-1 autocorrelation. Returns 0.0 if not computable."""
    n = len(series)
    if n < 4:
        return 0.0
    x = series[:-1]
    y = series[1:]
    mean_x = sum(x) / len(x)
    mean_y = sum(y) / len(y)
    num = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(len(x)))
    den_x = math.sqrt(sum((v - mean_x) ** 2 for v in x))
    den_y = math.sqrt(sum((v - mean_y) ** 2 for v in y))
    if den_x < 1e-12 or den_y < 1e-12:
        return 0.0
    return num / (den_x * den_y)


def _linear_slope(series: list[float]) -> float:
    """OLS slope of index vs. series values (per bar). Sign = trend direction."""
    n = len(series)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mean_x = (n - 1) / 2
    mean_y = sum(series) / n
    num = sum((xs[i] - mean_x) * (series[i] - mean_y) for i in range(n))
    den = sum((xs[i] - mean_x) ** 2 for i in range(n))
    return num / den if den > 1e-12 else 0.0


def _realized_vol_percentile(
    log_returns: list[float],
    vol_window: int,
    bars_per_year: float,
) -> tuple[float, float]:
    """
    Returns (current_annualized_vol, percentile_vs_history).

    Builds a rolling window of realized vols and ranks the most recent one.
    """
    if len(log_returns) < vol_window + 1:
        return 0.0, 0.5

    rolling_vols: list[float] = []
    for i in range(vol_window, len(log_returns) + 1):
        window = log_returns[i - vol_window : i]
        mean = sum(window) / len(window)
        variance = sum((r - mean) ** 2 for r in window) / len(window)
        rolling_vols.append(math.sqrt(variance) * math.sqrt(bars_per_year))

    if not rolling_vols:
        return 0.0, 0.5

    current = rolling_vols[-1]
    history = rolling_vols[:-1] or rolling_vols  # avoid empty history
    pct = sum(1 for v in history if v < current) / len(history)
    return round(current, 4), round(pct, 4)


# ---------------------------------------------------------------------------
# Top-level classifier
# ---------------------------------------------------------------------------

def classify_regime(
    prices: list[float],
    *,
    autocorr_window: int = 60,
    vol_window: int = 30,
    bars_per_year: float = 365.0,      # use 365 for 1-day crypto bars
    trend_threshold: float = 0.08,     # |ρ| must exceed this to call trend/MR
    vol_high_pct: float = 0.75,
    vol_low_pct: float = 0.25,
) -> RegimeState | None:
    """
    Classify the current market regime from a price series.

    Parameters
    ----------
    prices          : list of close prices, oldest first.
    autocorr_window : bars used for lag-1 autocorrelation of log-returns.
    vol_window      : bars used for each rolling realized-vol estimate.
    bars_per_year   : annualization factor (365 for daily crypto, 96*365 for 15-min).
    trend_threshold : minimum |ρ| to declare trending or mean-reverting.
    vol_high_pct    : vol-percentile above which HIGH_VOLATILITY is flagged.
    vol_low_pct     : vol-percentile below which LOW_VOLATILITY is flagged.

    Returns None if there is not enough data.
    """
    min_bars = max(autocorr_window, vol_window) + 5
    if len(prices) < min_bars:
        log.debug(f"regime_classifier: not enough bars ({len(prices)} < {min_bars})")
        return None

    symbol = "unknown"

    # Log-returns
    log_returns = [
        math.log(prices[i] / prices[i - 1])
        for i in range(1, len(prices))
        if prices[i - 1] > 0 and prices[i] > 0
    ]
    if len(log_returns) < autocorr_window:
        return None

    # 1. Lag-1 autocorrelation on the most recent autocorr_window returns
    recent_ret = log_returns[-autocorr_window:]
    rho = _lag1_autocorr(recent_ret)

    # 2. OU speed: κ = -log(|ρ|) — valid only when |ρ| < 1
    abs_rho = min(abs(rho), 0.9999)
    kappa = -math.log(abs_rho) if abs_rho > 1e-6 else 10.0  # very fast reversion

    # 3. Realized vol percentile
    vol_ann, vol_pct = _realized_vol_percentile(log_returns, vol_window, bars_per_year)

    # 4. Trend direction from log-price slope
    log_prices = [math.log(p) for p in prices[-autocorr_window:]]
    slope = _linear_slope(log_prices)

    # ------------------------------------------------------------------
    # Regime decision tree
    # Volatility regime takes priority; then trend/mean-reversion.
    # ------------------------------------------------------------------
    if vol_pct >= vol_high_pct:
        regime = MarketRegime.HIGH_VOLATILITY
        # Confidence proportional to how extreme the vol is
        confidence = min(1.0, (vol_pct - vol_high_pct) / (1.0 - vol_high_pct + 1e-6) * 0.5 + 0.5)

    elif vol_pct <= vol_low_pct:
        regime = MarketRegime.LOW_VOLATILITY
        confidence = min(1.0, (vol_low_pct - vol_pct) / (vol_low_pct + 1e-6) * 0.5 + 0.5)

    elif rho >= trend_threshold:
        # Positive autocorrelation → trending
        regime = MarketRegime.TRENDING_UP if slope >= 0 else MarketRegime.TRENDING_DOWN
        confidence = min(1.0, (rho - trend_threshold) / (1.0 - trend_threshold + 1e-6) * 0.6 + 0.4)

    elif rho <= -trend_threshold:
        # Negative autocorrelation → mean-reverting
        regime = MarketRegime.MEAN_REVERTING
        confidence = min(1.0, (-rho - trend_threshold) / (1.0 - trend_threshold + 1e-6) * 0.6 + 0.4)

    else:
        # Near-zero autocorrelation → random-walk / uncertain → treat as LOW_VOL
        regime = MarketRegime.LOW_VOLATILITY
        confidence = max(0.3, 1.0 - abs(rho) / trend_threshold)

    return RegimeState(
        symbol=symbol,
        regime=regime,
        autocorr=round(rho, 4),
        kappa=round(kappa, 4),
        vol_annualized=vol_ann,
        vol_percentile=vol_pct,
        trend_slope=round(slope, 8),
        confidence=round(confidence, 3),
    )


def classify_regime_for_symbol(
    symbol: str,
    prices: list[float],
    **kwargs,
) -> RegimeState | None:
    """Classify and tag the result with the symbol, then update the cache."""
    state = classify_regime(prices, **kwargs)
    if state is not None:
        state.symbol = symbol
        update_regime_cache(symbol, state)
        log.info(
            f"Regime [{symbol}]: {state.regime.value} | "
            f"ρ={state.autocorr:+.3f} κ={state.kappa:.3f} "
            f"vol={state.vol_annualized:.1%} (p{state.vol_percentile:.0%}) "
            f"conf={state.confidence:.2f}"
        )
    return state
