"""Tests for ArbitrageScanner._check_event() math."""

from __future__ import annotations

import pytest

from trading_bot.config import ArbitrageConfig, Config, StrategiesConfig
from trading_bot.models import EventData, MarketOutcome
from trading_bot.strategies.arbitrage import ArbitrageScanner


def _make_config(**arb_overrides) -> Config:
    """Create a minimal Config with custom ArbitrageConfig."""
    config = Config()
    arb = ArbitrageConfig(**arb_overrides)
    config.strategies = StrategiesConfig(arbitrage=arb)
    return config


def _make_event(prices: list[float], liquidity: float = 100.0) -> EventData:
    """Create a test EventData with given YES prices."""
    outcomes = [
        MarketOutcome(
            condition_id=f"cond_{i}",
            question=f"Outcome {i}",
            outcome_label=f"opt_{i}",
            yes_price=p,
            no_price=round(1.0 - p, 4),
            liquidity=liquidity,
        )
        for i, p in enumerate(prices)
    ]
    return EventData(
        event_id="evt_test",
        title="Test Event",
        outcomes=outcomes,
    )


class TestCheckEvent:
    def test_no_opportunity_fair_prices(self):
        """Sum = 1.0: no arbitrage edge."""
        config = _make_config(min_edge_pct=0.02, fee_estimate_pct=0.01)
        scanner = ArbitrageScanner(config)

        event = _make_event([0.50, 0.50])
        assert scanner._check_event(event) is None

    def test_buy_all_opportunity(self):
        """Sum < 1.0: buy all YES to guarantee profit."""
        config = _make_config(min_edge_pct=0.02, fee_estimate_pct=0.01)
        scanner = ArbitrageScanner(config)

        # sum = 0.90, raw_edge = 0.10, fees = 0.01*2 = 0.02, net = 0.08
        event = _make_event([0.30, 0.30, 0.30])
        opp = scanner._check_event(event)
        assert opp is not None
        assert opp.direction == "buy_all"
        assert opp.price_sum == pytest.approx(0.90, abs=0.001)
        assert opp.edge_pct > 0.02

    def test_sell_all_opportunity(self):
        """Sum > 1.0: sell all YES to profit."""
        config = _make_config(min_edge_pct=0.02, fee_estimate_pct=0.01)
        scanner = ArbitrageScanner(config)

        # sum = 1.20, raw_edge = 0.20, fees = 0.01*3 = 0.03, net = 0.17
        event = _make_event([0.40, 0.40, 0.40])
        opp = scanner._check_event(event)
        assert opp is not None
        assert opp.direction == "sell_all"
        assert opp.edge_pct > 0.10

    def test_edge_below_threshold(self):
        """Small edge eaten by fees → no opportunity."""
        config = _make_config(min_edge_pct=0.02, fee_estimate_pct=0.01)
        scanner = ArbitrageScanner(config)

        # sum = 0.99, raw_edge = 0.01, fees = 0.01*2 = 0.02, net = -0.01
        event = _make_event([0.49, 0.50])
        assert scanner._check_event(event) is None

    def test_too_few_outcomes(self):
        """Events with fewer than min_outcomes are skipped."""
        config = _make_config(min_outcomes=2)
        scanner = ArbitrageScanner(config)

        event = _make_event([0.50])
        assert scanner._check_event(event) is None

    def test_too_many_outcomes(self):
        """Events with more than max_outcomes are skipped."""
        config = _make_config(max_outcomes=3)
        scanner = ArbitrageScanner(config)

        event = _make_event([0.20, 0.20, 0.20, 0.20])
        assert scanner._check_event(event) is None

    def test_zero_liquidity_filtered(self):
        """Outcomes with zero liquidity are excluded from the sum."""
        config = _make_config(min_edge_pct=0.02, fee_estimate_pct=0.01)
        scanner = ArbitrageScanner(config)

        outcomes = [
            MarketOutcome(condition_id="c0", question="Q0", yes_price=0.40, no_price=0.60, liquidity=100),
            MarketOutcome(condition_id="c1", question="Q1", yes_price=0.40, no_price=0.60, liquidity=100),
            MarketOutcome(condition_id="c2", question="Q2", yes_price=0.10, no_price=0.90, liquidity=0),
        ]
        event = EventData(event_id="e1", title="Test", outcomes=outcomes)
        opp = scanner._check_event(event)
        # Only c0 and c1 are valid → sum = 0.80, raw_edge=0.20, fees=0.02, net=0.18
        assert opp is not None
        assert len(opp.outcomes) == 2
        assert opp.price_sum == pytest.approx(0.80, abs=0.001)

    def test_opportunity_to_decisions(self):
        """Verify trade decisions are generated correctly from an opportunity."""
        config = _make_config(max_size_per_leg_usd=200.0)
        scanner = ArbitrageScanner(config)

        event = _make_event([0.25, 0.25, 0.25])
        opp = scanner._check_event(event)
        assert opp is not None

        decisions = scanner._opportunity_to_decisions(opp)
        assert len(decisions) == 3
        for d in decisions:
            assert d.action.value == "buy"
            assert d.suggested_size_usd == 200.0
            assert d.confidence > 0.5

    def test_fee_impact_on_many_legs(self):
        """More legs = more fees; verify large leg count kills marginal edge."""
        config = _make_config(min_edge_pct=0.02, fee_estimate_pct=0.01)
        scanner = ArbitrageScanner(config)

        # 10 outcomes at 0.092 each: sum = 0.92, raw_edge = 0.08, fees = 0.01*10 = 0.10
        # net = 0.08 - 0.10 = -0.02 → should be rejected
        event = _make_event([0.092] * 10)
        assert scanner._check_event(event) is None
