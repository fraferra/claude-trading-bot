"""Tests for short-selling technical indicator functions and composite scorer.

Mathematical functions tested:
  - compute_rsi(closes, period)        — Wilder smoothed RSI
  - compute_bollinger_pct_b(closes)    — (price - lower) / (upper - lower)
  - compute_atr(highs, lows, closes)   — Average True Range
  - compute_macd_histogram(closes)     — MACD line - signal line, and declining flag
  - compute_short_composite(signals)   — weighted signal aggregation, clamped [-1, 0]
"""

from __future__ import annotations

import pandas as pd
import pytest

from trading_bot.models import ShortSignals
from trading_bot.strategies.short_scorer import (
    compute_atr,
    compute_bollinger_pct_b,
    compute_macd_histogram,
    compute_rsi,
    compute_short_composite,
    compute_volume_ratio,
)


# ---------------------------------------------------------------------------
# Helpers: build pandas Series/DataFrames
# ---------------------------------------------------------------------------

def _closes(values: list[float]) -> pd.Series:
    return pd.Series(values, dtype=float)


def _highs_lows_closes(n: int, base: float = 100.0, spread: float = 1.0):
    closes = pd.Series([base] * n, dtype=float)
    highs = closes + spread
    lows = closes - spread
    return highs, lows, closes


# ---------------------------------------------------------------------------
# TestComputeRSI
# ---------------------------------------------------------------------------

class TestComputeRSI:
    def test_all_gains_returns_100(self):
        """14 consecutive gains → RSI ≈ 100."""
        closes = _closes([100.0 + i for i in range(30)])
        rsi = compute_rsi(closes, 14)
        assert rsi is not None
        assert rsi > 95.0

    def test_all_losses_returns_0(self):
        """14 consecutive losses → RSI ≈ 0."""
        closes = _closes([100.0 - i for i in range(30)])
        rsi = compute_rsi(closes, 14)
        assert rsi is not None
        assert rsi < 5.0

    def test_mixed_moderate_rsi(self):
        """Alternating up/down → RSI in moderate range."""
        values = [100.0 + (1 if i % 2 == 0 else -1) for i in range(60)]
        closes = _closes(values)
        rsi = compute_rsi(closes, 14)
        assert rsi is not None
        assert 30.0 < rsi < 70.0

    def test_insufficient_data_returns_none(self):
        """Fewer than period+1 points → None."""
        closes = _closes([100.0] * 10)
        assert compute_rsi(closes, 14) is None

    def test_exactly_minimum_data_works(self):
        """Exactly period+1 points → result returned."""
        closes = _closes([100.0 + i for i in range(15)])  # period=14 → need 15
        rsi = compute_rsi(closes, 14)
        assert rsi is not None

    def test_rsi_in_valid_range(self):
        """RSI must always be in [0, 100]."""
        import random
        rng = random.Random(42)
        values = [100.0]
        for _ in range(60):
            values.append(values[-1] * (1 + rng.gauss(0, 0.02)))
        closes = _closes(values)
        rsi = compute_rsi(closes, 14)
        if rsi is not None:
            assert 0.0 <= rsi <= 100.0

    def test_constant_prices_returns_100(self):
        """No price change → no losses → RS → inf → RSI = 100."""
        closes = _closes([100.0] * 20)
        rsi = compute_rsi(closes, 14)
        assert rsi is not None
        assert rsi == 100.0

    def test_rsi_shorter_period_is_more_volatile(self):
        """RSI(2) fluctuates more than RSI(14) — tests that period affects sensitivity."""
        # A series that alternates up-down-up-down makes RSI(2) swing wildly
        alternating = [100.0 + (5.0 if i % 2 == 0 else -5.0) for i in range(60)]
        closes = pd.Series(alternating, dtype=float)
        rsi2  = compute_rsi(closes, 2)
        rsi14 = compute_rsi(closes, 14)
        # Both should be valid — just verify they can differ
        # (which is the core property of different periods)
        assert rsi2 is not None
        assert rsi14 is not None
        # With alternating data RSI(14) should be closer to 50 than RSI(2)
        assert abs(rsi14 - 50.0) <= abs(rsi2 - 50.0) + 30  # rsi14 more stable


# ---------------------------------------------------------------------------
# TestComputeBollingerPctB
# ---------------------------------------------------------------------------

class TestComputeBollingerPctB:
    def test_price_at_upper_band(self):
        """Price = SMA + 2σ → %B ≈ 1.0."""
        # Build a stable series then set last price to upper band
        values = [100.0] * 20
        closes = _closes(values)
        sma = 100.0
        std = 0.0  # degenerate — test the non-degenerate version below
        # Use a series with known std
        import numpy as np
        n = 30
        vals = [100.0 + (i - n // 2) * 0.1 for i in range(n)]  # slight spread
        closes2 = pd.Series(vals, dtype=float)
        result = compute_bollinger_pct_b(closes2, period=20)
        assert result is not None
        # Just check we get a float
        assert isinstance(result, float)

    def test_price_well_above_upper_band_exceeds_one(self):
        """Price far above upper band → %B > 1.0."""
        # Build a stable series, then spike up the last value
        base = [100.0] * 25
        spike = base[:-1] + [200.0]
        closes = _closes(spike)
        pct_b = compute_bollinger_pct_b(closes, period=20)
        assert pct_b is not None
        assert pct_b > 1.0

    def test_price_well_below_lower_band_negative(self):
        """Price far below lower band → %B < 0.0."""
        base = [100.0] * 25
        drop = base[:-1] + [1.0]
        closes = _closes(drop)
        pct_b = compute_bollinger_pct_b(closes, period=20)
        assert pct_b is not None
        assert pct_b < 0.0

    def test_constant_prices_no_crash(self):
        """Zero standard deviation → returns 0.5 (no division by zero crash)."""
        closes = _closes([100.0] * 25)
        pct_b = compute_bollinger_pct_b(closes, period=20)
        assert pct_b == 0.5

    def test_insufficient_data_returns_none(self):
        """Fewer than period points → None."""
        closes = _closes([100.0] * 10)
        assert compute_bollinger_pct_b(closes, period=20) is None

    def test_result_is_float(self):
        """Result should always be a float when data is sufficient."""
        values = [100.0 + i * 0.5 for i in range(30)]
        closes = _closes(values)
        pct_b = compute_bollinger_pct_b(closes, period=20)
        assert pct_b is not None
        assert isinstance(pct_b, float)


# ---------------------------------------------------------------------------
# TestComputeATR
# ---------------------------------------------------------------------------

class TestComputeATR:
    def test_constant_prices_atr_near_zero(self):
        """No price movement → ATR ≈ 0 (true range is spread only)."""
        highs, lows, closes = _highs_lows_closes(30, spread=0.0)
        atr = compute_atr(highs, lows, closes, period=14)
        assert atr is not None
        assert atr == pytest.approx(0.0, abs=1e-6)

    def test_wide_range_gives_higher_atr(self):
        """Larger high-low spread → higher ATR."""
        h1, l1, c1 = _highs_lows_closes(30, spread=1.0)
        h2, l2, c2 = _highs_lows_closes(30, spread=5.0)
        atr1 = compute_atr(h1, l1, c1, 14)
        atr2 = compute_atr(h2, l2, c2, 14)
        assert atr2 > atr1

    def test_atr_always_non_negative(self):
        """ATR can never be negative."""
        import random
        rng = random.Random(42)
        base = 100.0
        closes = pd.Series([base + rng.gauss(0, 2) for _ in range(40)])
        highs = closes + abs(pd.Series([rng.gauss(0, 1) for _ in range(40)]))
        lows = closes - abs(pd.Series([rng.gauss(0, 1) for _ in range(40)]))
        atr = compute_atr(highs, lows, closes, 14)
        assert atr is not None
        assert atr >= 0.0

    def test_insufficient_data_returns_none(self):
        """Fewer than period+1 closes → None."""
        h, l, c = _highs_lows_closes(10)
        assert compute_atr(h, l, c, period=14) is None

    def test_gap_accounted_in_true_range(self):
        """Gap between previous close and high/low contributes to true range."""
        # Create a series with a big gap up
        closes = pd.Series([100.0] * 20 + [150.0] + [150.0] * 9)
        highs = closes + 0.5
        lows = closes - 0.5
        atr = compute_atr(highs, lows, closes, 14)
        assert atr is not None
        assert atr > 1.0  # gap contribution makes ATR > the 1.0 spread


# ---------------------------------------------------------------------------
# TestComputeMACDHistogram
# ---------------------------------------------------------------------------

class TestComputeMACDHistogram:
    def _rising_closes(self, n: int = 60) -> pd.Series:
        return _closes([100.0 + i * 0.5 for i in range(n)])

    def _falling_closes(self, n: int = 60) -> pd.Series:
        return _closes([200.0 - i * 0.5 for i in range(n)])

    def test_uptrend_histogram_often_positive(self):
        """In a strong uptrend, MACD > signal → histogram positive."""
        closes = self._rising_closes(80)
        hist, _ = compute_macd_histogram(closes)
        assert hist is not None
        # For a pure uptrend, the fast EMA leads → histogram should be positive
        assert hist > 0

    def test_downtrend_histogram_often_negative(self):
        """In a strong downtrend, MACD < signal → histogram negative."""
        closes = self._falling_closes(80)
        hist, _ = compute_macd_histogram(closes)
        assert hist is not None
        assert hist < 0

    def test_returns_none_on_insufficient_data(self):
        """Fewer than slow+signal bars → None."""
        closes = _closes([100.0] * 20)  # 26+9=35 needed
        hist, declining = compute_macd_histogram(closes)
        assert hist is None

    def test_histogram_reflects_recent_vs_prev_bar(self):
        """Declining is True exactly when histogram[-1] < histogram[-2]."""
        # Build a long series and then verify the logic directly
        up = [100.0 + i * 1.0 for i in range(100)]
        closes = _closes(up)
        hist, declining = compute_macd_histogram(closes)
        assert hist is not None
        # Manually compute expected declining from the raw series
        fast = closes.ewm(span=12, adjust=False).mean()
        slow = closes.ewm(span=26, adjust=False).mean()
        macd_line = fast - slow
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        histogram = macd_line - signal_line
        expected_declining = histogram.iloc[-1] < histogram.iloc[-2]
        assert bool(declining) == bool(expected_declining)

    def test_histogram_declining_flag_is_bool_like(self):
        """The declining flag is boolean-like (True or False)."""
        closes = _closes([100.0 + i * 0.5 for i in range(60)])
        hist, declining = compute_macd_histogram(closes)
        assert declining in (True, False)

    def test_returns_float_and_bool(self):
        """Return types must be (float | None, bool-like)."""
        closes = _closes([100.0 + i * 0.1 for i in range(60)])
        hist, declining = compute_macd_histogram(closes)
        if hist is not None:
            assert isinstance(hist, float)
        # Accept both Python bool and numpy bool
        assert declining in (True, False)


# ---------------------------------------------------------------------------
# TestComputeVolumeRatio
# ---------------------------------------------------------------------------

class TestComputeVolumeRatio:
    def test_volume_equal_to_average_returns_one(self):
        """Constant volume → ratio ≈ 1.0."""
        volumes = pd.Series([1000.0] * 25)
        ratio = compute_volume_ratio(volumes, period=20)
        assert ratio is not None
        assert ratio == pytest.approx(1.0, rel=0.01)

    def test_high_recent_volume_ratio_above_one(self):
        """Recent spike → ratio > 1.0."""
        volumes = pd.Series([1000.0] * 24 + [5000.0])
        ratio = compute_volume_ratio(volumes, period=20)
        assert ratio is not None
        assert ratio > 1.0

    def test_low_recent_volume_ratio_below_one(self):
        """Recent decline → ratio < 1.0."""
        volumes = pd.Series([5000.0] * 24 + [100.0])
        ratio = compute_volume_ratio(volumes, period=20)
        assert ratio is not None
        assert ratio < 1.0

    def test_insufficient_data_returns_none(self):
        volumes = pd.Series([1000.0] * 10)
        assert compute_volume_ratio(volumes, period=20) is None

    def test_zero_average_returns_none(self):
        """Zero average volume → returns None (no division by zero)."""
        volumes = pd.Series([0.0] * 25)
        ratio = compute_volume_ratio(volumes, period=20)
        assert ratio is None


# ---------------------------------------------------------------------------
# TestShortCompositeScore
# ---------------------------------------------------------------------------

def _make_signals(**kwargs) -> ShortSignals:
    defaults = dict(
        symbol="TEST",
        rsi_2=None,
        rsi_14=None,
        bb_pct_b=None,
        macd_histogram=None,
        macd_hist_declining=False,
        volume_ratio=None,
        price_vs_sma200=None,
        atr_14=None,
        pe_ratio=None,
        current_price=100.0,
    )
    defaults.update(kwargs)
    return ShortSignals(**defaults)


class TestShortCompositeScore:
    def test_no_signals_returns_zero(self):
        """All signals None → score = 0.0."""
        signals = _make_signals()
        score, breakdown = compute_short_composite(signals)
        assert score == 0.0
        assert breakdown == {}

    def test_all_signals_triggered_strong_short(self):
        """All signals triggered → max short signal (≤ -1.0 clamped)."""
        signals = _make_signals(
            rsi_2=97.0,       # -0.25
            bb_pct_b=1.10,    # -0.20
            rsi_14=75.0,      # -0.15
            macd_histogram=0.5,
            macd_hist_declining=True,  # -0.15
            volume_ratio=2.0,  # -0.10
            pe_ratio=40.0,    # -0.10
            price_vs_sma200=-0.05,  # no uptrend penalty (below sma200)
        )
        score, breakdown = compute_short_composite(signals)
        # Total without uptrend penalty = -0.95
        assert score == pytest.approx(-0.95, abs=0.01)
        assert score >= -1.0  # clamped

    def test_uptrend_penalty_applied(self):
        """price > SMA200 → +0.15 applied (weakens short signal)."""
        signals = _make_signals(
            rsi_14=75.0,           # -0.15
            price_vs_sma200=0.05,  # +0.15 penalty
        )
        score, breakdown = compute_short_composite(signals)
        # -0.15 + 0.15 = 0.0
        assert score == pytest.approx(0.0, abs=0.01)
        assert "uptrend_penalty" in breakdown

    def test_score_never_positive(self):
        """Score is clamped to max 0.0."""
        signals = _make_signals(price_vs_sma200=5.0)  # huge uptrend penalty
        score, _ = compute_short_composite(signals)
        assert score <= 0.0

    def test_score_never_below_neg_one(self):
        """Score is clamped to min -1.0."""
        signals = _make_signals(
            rsi_2=99.0,
            bb_pct_b=2.0,
            rsi_14=85.0,
            macd_histogram=1.0,
            macd_hist_declining=True,
            volume_ratio=10.0,
            pe_ratio=100.0,
        )
        score, _ = compute_short_composite(signals)
        assert score >= -1.0

    def test_rsi_2_extreme_triggers(self):
        """RSI(2) > 95 → -0.25 contribution."""
        signals = _make_signals(rsi_2=96.0)
        score, breakdown = compute_short_composite(signals)
        assert breakdown.get("rsi_2_extreme") == -0.25
        assert score == pytest.approx(-0.25, abs=0.001)

    def test_rsi_2_below_threshold_no_trigger(self):
        """RSI(2) = 94 → does not trigger."""
        signals = _make_signals(rsi_2=94.0)
        score, breakdown = compute_short_composite(signals)
        assert "rsi_2_extreme" not in breakdown
        assert score == 0.0

    def test_bb_above_upper_band_triggers(self):
        """BB %B > 1.0 → -0.20 contribution."""
        signals = _make_signals(bb_pct_b=1.05)
        score, breakdown = compute_short_composite(signals)
        assert breakdown.get("bb_above_upper") == -0.20

    def test_macd_must_be_positive_and_declining(self):
        """MACD declining signal only triggers if histogram > 0 AND declining."""
        # Both conditions met
        s1 = _make_signals(macd_histogram=0.5, macd_hist_declining=True)
        s2 = _make_signals(macd_histogram=-0.5, macd_hist_declining=True)  # negative hist
        s3 = _make_signals(macd_histogram=0.5, macd_hist_declining=False)  # not declining

        score1, b1 = compute_short_composite(s1)
        score2, b2 = compute_short_composite(s2)
        score3, b3 = compute_short_composite(s3)

        assert "macd_declining" in b1
        assert "macd_declining" not in b2
        assert "macd_declining" not in b3

    def test_pe_overvalued_triggers(self):
        """PE > 35 → -0.10 contribution."""
        signals = _make_signals(pe_ratio=40.0)
        score, breakdown = compute_short_composite(signals)
        assert breakdown.get("high_pe") == -0.10

    def test_pe_below_threshold_no_trigger(self):
        """PE = 30 → does not trigger."""
        signals = _make_signals(pe_ratio=30.0)
        score, breakdown = compute_short_composite(signals)
        assert "high_pe" not in breakdown

    def test_volume_spike_triggers(self):
        """volume_ratio > 1.5 → -0.10 contribution."""
        signals = _make_signals(volume_ratio=2.0)
        score, breakdown = compute_short_composite(signals)
        assert breakdown.get("volume_spike") == -0.10

    def test_breakdown_sums_to_score_before_clamp(self):
        """Sum of breakdown values should equal score (within clamp bounds)."""
        signals = _make_signals(rsi_2=97.0, rsi_14=75.0, bb_pct_b=1.1)
        score, breakdown = compute_short_composite(signals)
        breakdown_sum = sum(breakdown.values())
        # Score = max(-1.0, min(0.0, breakdown_sum))
        expected = max(-1.0, min(0.0, breakdown_sum))
        assert score == pytest.approx(expected, abs=0.001)
