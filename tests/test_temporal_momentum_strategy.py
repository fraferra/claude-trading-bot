"""Tests for TemporalMomentumArbStrategy math helpers and strategy logic."""

from __future__ import annotations

import math
import time

import pytest

from trading_bot.brokers.exchange_feed import PricePoint
from trading_bot.config import TemporalMomentumConfig
from trading_bot.models import MomentumSignal
from trading_bot.strategies.temporal_momentum_arb import (
    calculate_edge,
    compute_fast_rsi,
    compute_momentum_strength,
    compute_price_change_pct,
    compute_velocity,
    determine_direction,
    estimate_true_probability,
    kelly_size,
    _parse_crypto_market,
)
from datetime import datetime, timezone, timedelta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_history(prices: list[float], base_ts: float | None = None) -> list[PricePoint]:
    """Create a price history with evenly spaced 5-second intervals."""
    now = base_ts or time.time()
    step = 5.0
    start = now - step * (len(prices) - 1)
    return [PricePoint(price=p, timestamp=start + i * step) for i, p in enumerate(prices)]


def _make_cfg(**kwargs) -> TemporalMomentumConfig:
    cfg = TemporalMomentumConfig()
    for k, v in kwargs.items():
        setattr(cfg, k, v)
    return cfg


def _make_signal(direction: str = "up", strength: float = 0.80, change_1m: float = 0.008) -> MomentumSignal:
    return MomentumSignal(
        symbol="BTC",
        current_price=70_000.0,
        change_1m_pct=change_1m if direction == "up" else -change_1m,
        change_3m_pct=change_1m * 1.5 if direction == "up" else -change_1m * 1.5,
        change_5m_pct=change_1m * 2.0 if direction == "up" else -change_1m * 2.0,
        velocity=0.001,
        direction=direction,
        strength=strength,
    )


# ---------------------------------------------------------------------------
# compute_price_change_pct
# ---------------------------------------------------------------------------

class TestComputePriceChangePct:
    def test_basic_increase(self):
        now = time.time()
        history = [
            PricePoint(price=100.0, timestamp=now - 90),
            PricePoint(price=101.0, timestamp=now - 60),
            PricePoint(price=102.0, timestamp=now),
        ]
        result = compute_price_change_pct(history, seconds_ago=60)
        assert result is not None
        assert abs(result - (102.0 - 101.0) / 101.0) < 0.001

    def test_basic_decrease(self):
        now = time.time()
        history = [
            PricePoint(price=100.0, timestamp=now - 90),
            PricePoint(price=100.0, timestamp=now - 60),
            PricePoint(price=95.0, timestamp=now),
        ]
        result = compute_price_change_pct(history, seconds_ago=60)
        assert result is not None
        assert result < 0

    def test_empty_history(self):
        assert compute_price_change_pct([], seconds_ago=60) is None

    def test_insufficient_history(self):
        # Only 1 point — can't compute lookback
        now = time.time()
        history = [PricePoint(price=100.0, timestamp=now)]
        # No point near 60s ago, so returns None
        result = compute_price_change_pct(history, seconds_ago=60)
        assert result is None

    def test_flat(self):
        now = time.time()
        history = [
            PricePoint(price=100.0, timestamp=now - 60),
            PricePoint(price=100.0, timestamp=now),
        ]
        result = compute_price_change_pct(history, seconds_ago=60)
        assert result == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# compute_momentum_strength
# ---------------------------------------------------------------------------

class TestComputeMomentumStrength:
    def test_range(self):
        for c1 in [-0.02, -0.01, 0.0, 0.003, 0.01, 0.02]:
            for c3 in [-0.02, -0.01, 0.0, 0.003, 0.01, 0.02]:
                s = compute_momentum_strength(c1, c3, c3 * 1.5)
                assert 0.0 <= s <= 1.0, f"Out of range: {s}"

    def test_strong_move_higher_than_weak(self):
        strong = compute_momentum_strength(0.02, 0.03, 0.04)
        weak = compute_momentum_strength(0.001, 0.001, 0.001)
        assert strong > weak

    def test_all_none(self):
        assert compute_momentum_strength(None, None, None) == 0.0

    def test_partial_none(self):
        # Should still produce a valid score from the non-None components
        s = compute_momentum_strength(0.01, None, None)
        assert 0.0 <= s <= 1.0


# ---------------------------------------------------------------------------
# determine_direction
# ---------------------------------------------------------------------------

class TestDetermineDirection:
    def test_both_up(self):
        assert determine_direction(0.005, 0.008) == "up"

    def test_both_down(self):
        assert determine_direction(-0.005, -0.008) == "down"

    def test_conflict_returns_flat(self):
        assert determine_direction(0.005, -0.008) == "flat"
        assert determine_direction(-0.005, 0.008) == "flat"

    def test_none_returns_flat(self):
        assert determine_direction(None, 0.005) == "flat"
        assert determine_direction(0.005, None) == "flat"
        assert determine_direction(None, None) == "flat"

    def test_zero_values(self):
        # 0.0 is not > 0 so disagreement with positive → flat
        assert determine_direction(0.0, 0.005) == "flat"


# ---------------------------------------------------------------------------
# compute_velocity
# ---------------------------------------------------------------------------

class TestComputeVelocity:
    def test_accelerating(self):
        now = time.time()
        history = [
            PricePoint(100.0, now - 10),
            PricePoint(101.0, now - 5),
            PricePoint(103.0, now),
        ]
        v = compute_velocity(history)
        assert v > 0  # accelerating upward

    def test_decelerating(self):
        now = time.time()
        history = [
            PricePoint(103.0, now - 10),
            PricePoint(102.0, now - 5),
            PricePoint(100.0, now),
        ]
        v = compute_velocity(history)
        assert v < 0  # decelerating (or accelerating downward)

    def test_empty(self):
        assert compute_velocity([]) == 0.0

    def test_too_few(self):
        now = time.time()
        assert compute_velocity([PricePoint(100.0, now), PricePoint(101.0, now + 1)]) == 0.0


# ---------------------------------------------------------------------------
# compute_fast_rsi
# ---------------------------------------------------------------------------

class TestComputeFastRsi:
    def test_all_up_returns_100(self):
        now = time.time()
        prices = [100.0 + i for i in range(20)]
        history = _make_history(prices)
        rsi = compute_fast_rsi(history, period=3, bar_seconds=5)
        assert rsi is not None
        assert rsi >= 90.0  # all gains → RSI near 100

    def test_all_down_returns_near_zero(self):
        now = time.time()
        prices = [120.0 - i * 2 for i in range(20)]
        history = _make_history(prices)
        rsi = compute_fast_rsi(history, period=3, bar_seconds=5)
        assert rsi is not None
        assert rsi <= 10.0  # all losses → RSI near 0

    def test_insufficient_history(self):
        history = _make_history([100.0, 101.0])  # too few points
        assert compute_fast_rsi(history, period=3, bar_seconds=5) is None

    def test_empty(self):
        assert compute_fast_rsi([]) is None

    def test_range(self):
        history = _make_history([100, 102, 101, 103, 102, 104, 103, 105, 103, 104])
        rsi = compute_fast_rsi(history, period=3, bar_seconds=5)
        if rsi is not None:
            assert 0.0 <= rsi <= 100.0


# ---------------------------------------------------------------------------
# estimate_true_probability
# ---------------------------------------------------------------------------

class TestEstimateTrueProbability:
    def test_flat_returns_50(self):
        cfg = _make_cfg()
        sig = _make_signal(direction="flat", strength=0.0)
        assert estimate_true_probability(sig, cfg) == pytest.approx(0.50)

    def test_up_strong_returns_above_65(self):
        cfg = _make_cfg()
        sig = _make_signal(direction="up", strength=0.85)
        prob = estimate_true_probability(sig, cfg)
        assert prob > 0.65

    def test_down_strong_returns_below_35(self):
        cfg = _make_cfg()
        sig = _make_signal(direction="down", strength=0.85)
        prob = estimate_true_probability(sig, cfg)
        assert prob < 0.35

    def test_bounded(self):
        cfg = _make_cfg()
        for direction in ("up", "down", "flat"):
            sig = _make_signal(direction=direction, strength=1.0, change_1m=0.10)
            prob = estimate_true_probability(sig, cfg)
            assert 0.0 <= prob <= 1.0

    def test_up_stronger_than_weak(self):
        cfg = _make_cfg()
        strong = estimate_true_probability(_make_signal("up", strength=0.95), cfg)
        weak = estimate_true_probability(_make_signal("up", strength=0.60), cfg)
        assert strong > weak


# ---------------------------------------------------------------------------
# calculate_edge
# ---------------------------------------------------------------------------

class TestCalculateEdge:
    def test_buy_yes_when_underpriced(self):
        # True prob 0.70, market at 0.50 → buy YES
        side, edge = calculate_edge(0.70, 0.50, 0.50)
        assert side == "yes"
        assert edge == pytest.approx(0.20)

    def test_buy_no_when_no_underpriced(self):
        # True P(YES) = 0.30, market YES = 0.50, market NO = 0.50
        # P(NO) = 0.70, NO priced at 0.50 → NO edge = 0.20
        side, edge = calculate_edge(0.30, 0.50, 0.50)
        assert side == "no"
        assert edge == pytest.approx(0.20)

    def test_zero_edge(self):
        # Market is fairly priced
        side, edge = calculate_edge(0.50, 0.50, 0.50)
        assert edge == pytest.approx(0.0, abs=0.01)

    def test_both_sides_same(self):
        side, edge = calculate_edge(0.75, 0.50, 0.50)
        assert side == "yes"
        assert edge == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# kelly_size
# ---------------------------------------------------------------------------

class TestKellySize:
    def test_basic(self):
        # true_prob=0.70, market_price=0.50, available=10000, max=500
        size = kelly_size(0.70, 0.50, 0.25, 500.0, 10_000.0)
        assert size > 0
        assert size <= 500.0

    def test_capped_at_max(self):
        # Very strong edge should still be capped
        size = kelly_size(0.95, 0.50, 1.0, 200.0, 50_000.0)
        assert size <= 200.0

    def test_no_edge_returns_zero(self):
        # true_prob <= market_price → zero or near-zero kelly
        size = kelly_size(0.50, 0.50, 0.25, 500.0, 10_000.0)
        assert size == pytest.approx(0.0, abs=0.01)

    def test_invalid_market_price(self):
        assert kelly_size(0.70, 0.0, 0.25, 500.0, 10_000.0) == 0.0
        assert kelly_size(0.70, 1.0, 0.25, 500.0, 10_000.0) == 0.0

    def test_proportional_to_available(self):
        small = kelly_size(0.70, 0.50, 0.25, 500.0, 1_000.0)
        large = kelly_size(0.70, 0.50, 0.25, 500.0, 100_000.0)
        # Both capped by max_size_usd=500, but before cap larger cash → more
        assert large >= small


# ---------------------------------------------------------------------------
# _parse_crypto_market
# ---------------------------------------------------------------------------

class TestParseCryptoMarket:
    def _market(self, question: str, minutes_ahead: float = 10.0, volume: float = 10_000.0):
        """Build a minimal CLOB market dict."""
        from datetime import datetime, timezone, timedelta
        end_dt = datetime.now(timezone.utc) + timedelta(minutes=minutes_ahead)
        return {
            "question": question,
            "condition_id": "cond_test",
            "end_date_iso": end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tokens": [
                {"outcome": "Yes", "token_id": "tok_yes", "price": "0.52"},
                {"outcome": "No", "token_id": "tok_no", "price": "0.48"},
            ],
            "volume": str(volume),
        }

    def test_btc_15min_matches(self):
        cfg = _make_cfg()
        market = self._market("Will BTC be higher in 15 min?")
        result = _parse_crypto_market(market, datetime.now(timezone.utc), cfg)
        assert result is not None
        assert result["symbol"] == "BTC"
        assert result["token_id_yes"] == "tok_yes"

    def test_eth_matches(self):
        cfg = _make_cfg()
        market = self._market("Will ETH be higher in 5 min?")
        result = _parse_crypto_market(market, datetime.now(timezone.utc), cfg)
        assert result is not None
        assert result["symbol"] == "ETH"

    def test_sol_matches(self):
        cfg = _make_cfg()
        market = self._market("Will SOL be higher in 15 min?")
        result = _parse_crypto_market(market, datetime.now(timezone.utc), cfg)
        assert result is not None
        assert result["symbol"] == "SOL"

    def test_non_crypto_excluded(self):
        cfg = _make_cfg()
        market = self._market("Will it rain in NYC in 15 min?")
        assert _parse_crypto_market(market, datetime.now(timezone.utc), cfg) is None

    def test_too_soon_excluded(self):
        cfg = _make_cfg(min_minutes_to_expiry=2.0)
        market = self._market("Will BTC be higher in 15 min?", minutes_ahead=1.0)
        assert _parse_crypto_market(market, datetime.now(timezone.utc), cfg) is None

    def test_too_far_excluded(self):
        cfg = _make_cfg(max_minutes_to_expiry=20.0)
        market = self._market("Will BTC be higher in 15 min?", minutes_ahead=60.0)
        assert _parse_crypto_market(market, datetime.now(timezone.utc), cfg) is None

    def test_low_volume_excluded(self):
        cfg = _make_cfg(min_volume_usd=5_000.0)
        market = self._market("Will BTC be higher in 15 min?", volume=100.0)
        assert _parse_crypto_market(market, datetime.now(timezone.utc), cfg) is None

    def test_long_duration_excluded(self):
        cfg = _make_cfg()
        market = self._market("Will BTC reach 100k in 60 min?", minutes_ahead=10.0)
        result = _parse_crypto_market(market, datetime.now(timezone.utc), cfg)
        # 60 min exceeds ≤30 min filter
        assert result is None
