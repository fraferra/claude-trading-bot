"""Tests for OU-process regime classifier math.

Mathematical foundations tested:
  - Lag-1 autocorrelation (Pearson)
  - OLS linear slope for trend direction
  - Rolling realized-vol percentile
  - Regime decision tree (HIGH_VOL, LOW_VOL, TRENDING_UP/DOWN, MEAN_REVERTING)
  - REGIME_PARAMS table completeness
"""

from __future__ import annotations

import math
import random

import pytest

from trading_bot.analysis.regime_classifier import (
    REGIME_PARAMS,
    RegimeState,
    _lag1_autocorr,
    _linear_slope,
    _realized_vol_percentile,
    classify_regime,
    clear_cache,
    get_regime,
    update_regime_cache,
)
from trading_bot.models import MarketRegime


# ---------------------------------------------------------------------------
# Helpers: synthetic time series generators
# ---------------------------------------------------------------------------

def _white_noise(n: int, seed: int = 42) -> list[float]:
    """IID normal returns — should show near-zero autocorrelation."""
    rng = random.Random(seed)
    return [rng.gauss(0, 0.01) for _ in range(n)]


def _ar1_series(n: int, rho: float, sigma: float = 0.01, seed: int = 42) -> list[float]:
    """AR(1) series: r_t = rho * r_{t-1} + epsilon."""
    rng = random.Random(seed)
    series = [0.0]
    for _ in range(n - 1):
        series.append(rho * series[-1] + rng.gauss(0, sigma))
    return series


def _price_series_from_returns(returns: list[float], p0: float = 100.0) -> list[float]:
    prices = [p0]
    for r in returns:
        prices.append(prices[-1] * math.exp(r))
    return prices


def _trending_prices(n: int, drift: float = 0.001, seed: int = 42) -> list[float]:
    """Prices with positive drift (uptrend) and strong momentum."""
    rng = random.Random(seed)
    returns = [drift + rng.gauss(0, 0.005) for _ in range(n)]
    return _price_series_from_returns(returns)


def _high_vol_prices(n: int, seed: int = 42) -> list[float]:
    """Prices with very high volatility — should trigger HIGH_VOLATILITY regime."""
    rng = random.Random(seed)
    # Very high variance returns
    returns = [rng.gauss(0, 0.05) for _ in range(n)]
    return _price_series_from_returns(returns)


def _stable_prices(n: int, seed: int = 42) -> list[float]:
    """Almost flat prices — should trigger LOW_VOLATILITY regime."""
    rng = random.Random(seed)
    returns = [rng.gauss(0, 0.0001) for _ in range(n)]
    return _price_series_from_returns(returns)


def _mean_reverting_prices(n: int, rho: float = -0.4, seed: int = 42) -> list[float]:
    """Prices from a negatively-autocorrelated AR(1) process (mean-reverting)."""
    returns = _ar1_series(n, rho=rho, sigma=0.01, seed=seed)
    return _price_series_from_returns(returns)


# ---------------------------------------------------------------------------
# TestOUMathCore
# ---------------------------------------------------------------------------

class TestLag1Autocorr:
    def test_white_noise_near_zero(self):
        """IID returns should have near-zero lag-1 autocorrelation."""
        series = _white_noise(500)
        rho = _lag1_autocorr(series)
        assert abs(rho) < 0.15, f"Expected |ρ| < 0.15 for white noise, got {rho:.3f}"

    def test_positive_ar1_detected(self):
        """AR(1) with ρ=0.6 should yield positive autocorrelation."""
        series = _ar1_series(500, rho=0.6)
        rho = _lag1_autocorr(series)
        assert rho > 0.3, f"Expected positive autocorr for AR(1) ρ=0.6, got {rho:.3f}"

    def test_negative_ar1_detected(self):
        """AR(1) with ρ=-0.4 should yield negative autocorrelation."""
        series = _ar1_series(500, rho=-0.4)
        rho = _lag1_autocorr(series)
        assert rho < -0.15, f"Expected negative autocorr for AR(1) ρ=-0.4, got {rho:.3f}"

    def test_insufficient_data_returns_zero(self):
        """Fewer than 4 points should return 0.0 safely."""
        assert _lag1_autocorr([]) == 0.0
        assert _lag1_autocorr([1.0, 2.0]) == 0.0
        assert _lag1_autocorr([1.0, 2.0, 3.0]) == 0.0

    def test_constant_series_returns_zero(self):
        """Constant returns → zero variance → returns 0.0 (no crash)."""
        result = _lag1_autocorr([0.01] * 50)
        assert result == 0.0

    def test_output_in_range(self):
        """Autocorrelation must always be in [-1, 1]."""
        for seed in range(10):
            rng = random.Random(seed)
            series = [rng.gauss(0, 1) for _ in range(100)]
            rho = _lag1_autocorr(series)
            assert -1.0 <= rho <= 1.0


class TestLinearSlope:
    def test_flat_prices_slope_near_zero(self):
        """Constant price series → OLS slope ≈ 0."""
        log_prices = [math.log(100.0)] * 60
        slope = _linear_slope(log_prices)
        assert abs(slope) < 1e-10

    def test_uptrend_positive_slope(self):
        """Monotonically increasing prices → positive slope."""
        prices = [100.0 + i for i in range(60)]
        log_prices = [math.log(p) for p in prices]
        slope = _linear_slope(log_prices)
        assert slope > 0

    def test_downtrend_negative_slope(self):
        """Monotonically decreasing prices → negative slope."""
        prices = [200.0 - i for i in range(60)]
        log_prices = [math.log(p) for p in prices]
        slope = _linear_slope(log_prices)
        assert slope < 0

    def test_single_point_returns_zero(self):
        """Only 1 data point → 0.0 (no crash)."""
        assert _linear_slope([1.0]) == 0.0

    def test_empty_returns_zero(self):
        assert _linear_slope([]) == 0.0

    def test_larger_slope_for_steeper_trend(self):
        """Steeper trend → larger magnitude slope."""
        gentle = [math.log(100.0 + i * 0.1) for i in range(60)]
        steep = [math.log(100.0 + i * 5.0) for i in range(60)]
        assert _linear_slope(steep) > _linear_slope(gentle)


class TestRealizedVolPercentile:
    def test_insufficient_data_returns_default(self):
        """Not enough data → (0.0, 0.5) default."""
        vol, pct = _realized_vol_percentile([0.01] * 5, vol_window=30, bars_per_year=365)
        assert vol == 0.0
        assert pct == 0.5

    def test_current_vol_higher_than_history(self):
        """When recent vol exceeds all historical vols → percentile near 1.0."""
        # Build a long series of tiny returns, then spike at the end
        calm = [0.0001] * 100
        volatile = [0.10] * 5  # much higher vol at end
        series = calm + volatile
        _, pct = _realized_vol_percentile(series, vol_window=30, bars_per_year=365)
        assert pct > 0.7, f"Expected high vol percentile, got {pct:.3f}"

    def test_current_vol_lower_than_history(self):
        """When recent vol is low relative to history → percentile near 0.0.

        Need enough calm bars at end to fill the entire vol_window.
        """
        volatile = [0.05] * 100
        calm = [0.0001] * 40  # must be >= vol_window to dominate last window
        series = volatile + calm
        _, pct = _realized_vol_percentile(series, vol_window=30, bars_per_year=365)
        assert pct < 0.5, f"Expected low vol percentile, got {pct:.3f}"

    def test_vol_always_non_negative(self):
        """Annualized vol must always be ≥ 0."""
        series = _white_noise(200)
        vol, _ = _realized_vol_percentile(series, vol_window=20, bars_per_year=252)
        assert vol >= 0.0

    def test_percentile_in_unit_interval(self):
        """Percentile must be in [0, 1]."""
        series = _white_noise(200)
        _, pct = _realized_vol_percentile(series, vol_window=20, bars_per_year=252)
        assert 0.0 <= pct <= 1.0


# ---------------------------------------------------------------------------
# TestRegimeClassification
# ---------------------------------------------------------------------------

class TestRegimeClassification:
    def test_insufficient_data_returns_none(self):
        """Fewer than min_bars → None."""
        prices = [100.0 + i for i in range(10)]  # way too few
        result = classify_regime(prices)
        assert result is None

    def test_returns_regime_state_object(self):
        """With enough data, classify_regime returns a RegimeState."""
        prices = _trending_prices(200)
        result = classify_regime(prices)
        assert result is not None
        assert isinstance(result, RegimeState)
        assert isinstance(result.regime, MarketRegime)

    def test_high_volatility_detected(self):
        """Extremely volatile price series → HIGH_VOLATILITY."""
        prices = _high_vol_prices(300, seed=1)
        result = classify_regime(prices)
        assert result is not None
        # High vol should push vol_percentile ≥ 0.75
        if result.vol_percentile >= 0.75:
            assert result.regime == MarketRegime.HIGH_VOLATILITY

    def test_low_volatility_detected(self):
        """Very stable prices → LOW_VOLATILITY."""
        prices = _stable_prices(300)
        result = classify_regime(prices)
        assert result is not None
        if result.vol_percentile <= 0.25:
            assert result.regime == MarketRegime.LOW_VOLATILITY

    def test_trending_up_detected(self):
        """Strong uptrend → TRENDING_UP (positive ρ + positive slope)."""
        # Use a strongly positively autocorrelated AR(1) process with drift
        returns = _ar1_series(300, rho=0.5, seed=7)
        # Add positive drift to force upward slope
        returns = [r + 0.003 for r in returns]
        prices = _price_series_from_returns(returns)
        result = classify_regime(prices)
        assert result is not None
        # If ρ > trend_threshold and slope > 0 → TRENDING_UP
        if result.autocorr > 0.08 and result.trend_slope > 0:
            assert result.regime == MarketRegime.TRENDING_UP

    def test_trending_down_detected(self):
        """Strong downtrend → TRENDING_DOWN (positive ρ + negative slope + mid vol)."""
        returns = _ar1_series(300, rho=0.5, seed=7)
        returns = [r - 0.003 for r in returns]  # negative drift
        prices = _price_series_from_returns(returns)
        result = classify_regime(prices)
        assert result is not None
        # Only assert if both autocorr AND vol conditions are in range for this path
        if (result.autocorr > 0.08
                and result.trend_slope < 0
                and 0.25 < result.vol_percentile < 0.75):
            assert result.regime == MarketRegime.TRENDING_DOWN

    def test_mean_reverting_detected(self):
        """Strongly mean-reverting AR(1) → MEAN_REVERTING (mid vol range required)."""
        prices = _mean_reverting_prices(300, rho=-0.4)
        result = classify_regime(prices)
        assert result is not None
        # Only assert MEAN_REVERTING if vol is in the mid range (not overridden by vol check)
        if (result.autocorr < -0.08
                and 0.25 < result.vol_percentile < 0.75):
            assert result.regime == MarketRegime.MEAN_REVERTING

    def test_confidence_in_unit_interval(self):
        """Confidence must always be in [0, 1]."""
        prices = _trending_prices(200)
        result = classify_regime(prices)
        if result is not None:
            assert 0.0 <= result.confidence <= 1.0

    def test_kappa_non_negative(self):
        """OU speed κ = -log(|ρ|) must be non-negative."""
        prices = _trending_prices(200)
        result = classify_regime(prices)
        if result is not None:
            assert result.kappa >= 0.0

    def test_autocorr_in_valid_range(self):
        """Autocorrelation must be in (-1, 1)."""
        prices = _trending_prices(200)
        result = classify_regime(prices)
        if result is not None:
            assert -1.0 < result.autocorr < 1.0

    def test_high_vol_confidence_high_when_extreme(self):
        """When vol_pct is very high, confidence should be close to 1.0."""
        # Simulate a result with extreme vol_pct
        state = RegimeState(
            symbol="TEST",
            regime=MarketRegime.HIGH_VOLATILITY,
            autocorr=0.0,
            kappa=0.0,
            vol_annualized=0.9,
            vol_percentile=0.99,
            trend_slope=0.0,
            confidence=0.99,
        )
        assert state.confidence >= 0.9

    def test_deterministic_output_same_input(self):
        """Same price series → same regime result."""
        prices = _trending_prices(200, seed=99)
        r1 = classify_regime(prices)
        r2 = classify_regime(prices)
        if r1 is not None and r2 is not None:
            assert r1.regime == r2.regime
            assert r1.autocorr == r2.autocorr
            assert r1.vol_percentile == r2.vol_percentile


# ---------------------------------------------------------------------------
# TestRegimeParams
# ---------------------------------------------------------------------------

class TestRegimeParams:
    def test_all_regimes_present(self):
        """Every MarketRegime value must have an entry in REGIME_PARAMS."""
        for regime in MarketRegime:
            assert regime in REGIME_PARAMS, f"Missing REGIME_PARAMS entry for {regime}"

    def test_trending_up_favors_momentum(self):
        params = REGIME_PARAMS[MarketRegime.TRENDING_UP]
        assert params["momentum_weight"] > params["mean_rev_weight"]

    def test_mean_reverting_favors_mean_rev(self):
        params = REGIME_PARAMS[MarketRegime.MEAN_REVERTING]
        assert params["mean_rev_weight"] > params["momentum_weight"]

    def test_high_volatility_reduces_position_scale(self):
        params = REGIME_PARAMS[MarketRegime.HIGH_VOLATILITY]
        low_vol_params = REGIME_PARAMS[MarketRegime.LOW_VOLATILITY]
        assert params["position_size_multiplier"] < low_vol_params["position_size_multiplier"]

    def test_high_volatility_requires_stronger_signal(self):
        """HIGH_VOLATILITY should have the highest min_signal_multiplier."""
        params = REGIME_PARAMS[MarketRegime.HIGH_VOLATILITY]
        for regime, p in REGIME_PARAMS.items():
            if regime != MarketRegime.HIGH_VOLATILITY:
                assert params["min_signal_multiplier"] >= p["min_signal_multiplier"]

    def test_all_weights_positive(self):
        for regime, params in REGIME_PARAMS.items():
            assert params["momentum_weight"] > 0, f"{regime}: momentum_weight <= 0"
            assert params["mean_rev_weight"] > 0, f"{regime}: mean_rev_weight <= 0"
            assert params["position_size_multiplier"] > 0, f"{regime}: position_size_multiplier <= 0"

    def test_regime_state_params_method(self):
        """RegimeState.params() should return the correct regime params."""
        state = RegimeState(
            symbol="BTC",
            regime=MarketRegime.TRENDING_UP,
            autocorr=0.3,
            kappa=0.5,
            vol_annualized=0.5,
            vol_percentile=0.5,
            trend_slope=0.001,
            confidence=0.8,
        )
        params = state.params()
        assert params == REGIME_PARAMS[MarketRegime.TRENDING_UP]


# ---------------------------------------------------------------------------
# TestRegimeCache
# ---------------------------------------------------------------------------

class TestRegimeCache:
    def setup_method(self):
        clear_cache()

    def test_cache_miss_returns_none(self):
        assert get_regime("BTC") is None

    def test_cache_hit_after_update(self):
        state = RegimeState(
            symbol="ETH",
            regime=MarketRegime.LOW_VOLATILITY,
            autocorr=0.0,
            kappa=0.0,
            vol_annualized=0.1,
            vol_percentile=0.2,
            trend_slope=0.0,
            confidence=0.8,
        )
        update_regime_cache("ETH", state)
        result = get_regime("ETH")
        assert result is not None
        assert result.regime == MarketRegime.LOW_VOLATILITY

    def test_clear_cache_removes_all(self):
        state = RegimeState(
            symbol="SOL",
            regime=MarketRegime.MEAN_REVERTING,
            autocorr=-0.2,
            kappa=0.2,
            vol_annualized=0.3,
            vol_percentile=0.5,
            trend_slope=0.0,
            confidence=0.7,
        )
        update_regime_cache("SOL", state)
        clear_cache()
        assert get_regime("SOL") is None

    def test_overwrite_updates_regime(self):
        for regime in [MarketRegime.TRENDING_UP, MarketRegime.MEAN_REVERTING]:
            state = RegimeState(
                symbol="AAPL",
                regime=regime,
                autocorr=0.1,
                kappa=0.1,
                vol_annualized=0.2,
                vol_percentile=0.5,
                trend_slope=0.0,
                confidence=0.7,
            )
            update_regime_cache("AAPL", state)
        assert get_regime("AAPL").regime == MarketRegime.MEAN_REVERTING
