"""Tests for Kelly Criterion and probability edge calculations."""

from __future__ import annotations

import pytest

from trading_bot.strategies.probability_edge import kelly_criterion


class TestKellyCriterion:
    def test_no_edge_returns_zero(self):
        """AI probability == market price → no edge → Kelly = 0."""
        f = kelly_criterion(0.60, 0.60)
        assert f == pytest.approx(0.0, abs=0.001)

    def test_positive_edge_buy_yes(self):
        """AI > market → buy YES side → positive fraction."""
        # AI says 70%, market at 50%
        # b = (1/0.5) - 1 = 1.0, p = 0.7, q = 0.3
        # f* = (0.7*1 - 0.3) / 1 = 0.4
        f = kelly_criterion(0.70, 0.50)
        assert f == pytest.approx(0.40, abs=0.01)

    def test_negative_edge_buy_no(self):
        """AI < market → buy NO side → Kelly based on NO odds."""
        # AI says 30%, market YES at 60%
        # Flip: p_no = 0.70, market_no = 0.40
        # b = (1/0.4) - 1 = 1.5, p = 0.7, q = 0.3
        # f* = (0.7*1.5 - 0.3) / 1.5 = (1.05-0.3)/1.5 = 0.5
        f = kelly_criterion(0.30, 0.60)
        assert f == pytest.approx(0.50, abs=0.01)

    def test_extreme_confidence(self):
        """Near-certain AI estimate → large Kelly fraction."""
        # AI says 95%, market at 50%
        # b = 1.0, f* = (0.95 - 0.05) / 1.0 = 0.9
        f = kelly_criterion(0.95, 0.50)
        assert f == pytest.approx(0.90, abs=0.01)

    def test_capped_at_one(self):
        """Kelly fraction should never exceed 1.0."""
        f = kelly_criterion(0.99, 0.01)
        assert f <= 1.0

    def test_floor_at_zero(self):
        """Kelly fraction should never be negative."""
        # AI agrees with market — no edge
        f = kelly_criterion(0.50, 0.50)
        assert f >= 0.0

    def test_market_price_zero(self):
        """Edge case: market price at 0 → return 0."""
        f = kelly_criterion(0.50, 0.0)
        assert f == 0.0

    def test_market_price_one(self):
        """Edge case: market price at 1.0 → return 0."""
        f = kelly_criterion(0.90, 1.0)
        assert f == 0.0

    def test_small_edge_small_fraction(self):
        """10% edge on 50% market → moderate Kelly."""
        # AI says 60%, market at 50%
        # b = 1.0, f* = (0.6*1 - 0.4)/1 = 0.2
        f = kelly_criterion(0.60, 0.50)
        assert f == pytest.approx(0.20, abs=0.01)

    def test_high_market_price_positive_edge(self):
        """Edge at high market price → smaller odds, smaller fraction."""
        # AI says 95%, market at 85%
        # b = (1/0.85) - 1 ≈ 0.1765
        # f* = (0.95*0.1765 - 0.05) / 0.1765 ≈ (0.1677-0.05)/0.1765 ≈ 0.667
        f = kelly_criterion(0.95, 0.85)
        assert 0.5 < f < 0.8

    def test_low_market_price_negative_edge(self):
        """AI thinks NO at cheap YES market."""
        # AI says 10%, market YES at 20%
        # Flip: p_no = 0.90, market_no = 0.80
        # b = (1/0.8) - 1 = 0.25
        # f* = (0.9*0.25 - 0.1) / 0.25 = (0.225-0.1)/0.25 = 0.5
        f = kelly_criterion(0.10, 0.20)
        assert f == pytest.approx(0.50, abs=0.01)
