"""Tests for the Selector Agent."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from trading_bot.agents.selector import SelectorAgent, _compute_current_weights, _determine_action
from trading_bot.config import Config, ResearchAgentConfig
from trading_bot.models import (
    DimensionScores,
    Platform,
    Position,
    ResearchReport,
)


def _make_config(**kwargs) -> Config:
    cfg = Config()
    cfg.anthropic_api_key = "test-key"
    cfg.research_agent = ResearchAgentConfig(**kwargs)
    return cfg


def _make_report(symbol: str, score: float, **kwargs) -> ResearchReport:
    return ResearchReport(
        symbol=symbol,
        composite_score=score,
        dimension_scores=DimensionScores(),
        **kwargs,
    )


class TestDetermineAction:
    def test_new_buy(self):
        assert _determine_action(0.0, 0.10, 0.05) == "buy"

    def test_sell_all(self):
        assert _determine_action(0.10, 0.0, 0.05) == "sell"

    def test_add(self):
        assert _determine_action(0.05, 0.12, 0.05) == "add"

    def test_trim(self):
        assert _determine_action(0.12, 0.05, 0.05) == "trim"

    def test_hold(self):
        assert _determine_action(0.10, 0.11, 0.05) == "hold"


class TestComputeCurrentWeights:
    def test_empty_portfolio(self):
        assert _compute_current_weights([], 100000) == {}

    def test_zero_equity(self):
        pos = [Position(symbol="AAPL", quantity=10, avg_entry_price=150, market_value=1500, platform=Platform.ALPACA)]
        assert _compute_current_weights(pos, 0) == {}

    def test_normal_weights(self):
        positions = [
            Position(symbol="AAPL", quantity=10, avg_entry_price=150, market_value=1500, platform=Platform.ALPACA),
            Position(symbol="MSFT", quantity=5, avg_entry_price=300, market_value=1500, platform=Platform.ALPACA),
        ]
        weights = _compute_current_weights(positions, 10000)
        assert weights["AAPL"] == 0.15
        assert weights["MSFT"] == 0.15


class TestSelectorAgent:
    @pytest.mark.asyncio
    async def test_build_allocation_basic(self):
        """Builds allocation from scored reports."""
        config = _make_config(max_positions=5, min_cash_reserve_pct=0.20, max_single_position_pct=0.40, min_research_score=5.0)
        agent = SelectorAgent(config)

        reports = [
            _make_report("AAPL", 8.0),
            _make_report("NVDA", 7.5),
            _make_report("MSFT", 6.0),
        ]

        # Mock the LLM review
        with patch.object(agent.analyst, "_call_llm_raw", new_callable=AsyncMock, return_value='{"overall_assessment": "Good", "concerns": [], "adjustments": []}'):
            allocation = await agent.build_allocation(reports, portfolio_equity=100000)

        assert allocation.total_positions == 3
        assert allocation.cash_reserve >= 0.19  # ~20% cash reserve (rounding)
        assert allocation.rebalance_needed is True

        # Higher score should get higher weight
        entries_by_sym = {e.symbol: e for e in allocation.entries}
        assert entries_by_sym["AAPL"].target_weight > entries_by_sym["MSFT"].target_weight

    @pytest.mark.asyncio
    async def test_build_allocation_filters_low_scores(self):
        """Reports below min_research_score are excluded."""
        config = _make_config(min_research_score=6.0)
        agent = SelectorAgent(config)

        reports = [
            _make_report("AAPL", 8.0),
            _make_report("BAD", 4.0),  # Below threshold
        ]

        with patch.object(agent.analyst, "_call_llm_raw", new_callable=AsyncMock, return_value='{"overall_assessment": "OK", "concerns": [], "adjustments": []}'):
            allocation = await agent.build_allocation(reports, portfolio_equity=100000)

        symbols = [e.symbol for e in allocation.entries]
        assert "AAPL" in symbols
        assert "BAD" not in symbols

    @pytest.mark.asyncio
    async def test_build_allocation_no_qualified(self):
        """Returns all-cash allocation when no stocks qualify."""
        config = _make_config(min_research_score=9.0)
        agent = SelectorAgent(config)

        reports = [_make_report("AAPL", 5.0)]

        allocation = await agent.build_allocation(reports, portfolio_equity=100000)
        assert allocation.cash_reserve == 1.0
        assert allocation.total_positions == 0
        assert allocation.rebalance_needed is False

    @pytest.mark.asyncio
    async def test_build_allocation_respects_max_position(self):
        """No single position exceeds max_single_position_pct."""
        config = _make_config(max_positions=2, max_single_position_pct=0.10, min_research_score=5.0)
        agent = SelectorAgent(config)

        # One stock with very high score relative to the other
        reports = [
            _make_report("AAPL", 9.5),
            _make_report("MSFT", 5.5),
        ]

        with patch.object(agent.analyst, "_call_llm_raw", new_callable=AsyncMock, return_value='{"overall_assessment": "OK", "concerns": [], "adjustments": []}'):
            allocation = await agent.build_allocation(reports, portfolio_equity=100000)

        for entry in allocation.entries:
            assert entry.target_weight <= 0.10

    @pytest.mark.asyncio
    async def test_build_allocation_identifies_sells(self):
        """Positions not in new allocation get sell action."""
        config = _make_config(min_research_score=5.0)
        agent = SelectorAgent(config)

        reports = [_make_report("AAPL", 8.0)]  # Only AAPL qualifies

        current_positions = [
            Position(symbol="AAPL", quantity=10, avg_entry_price=150, market_value=1500, platform=Platform.ALPACA),
            Position(symbol="OLD_STOCK", quantity=5, avg_entry_price=100, market_value=500, platform=Platform.ALPACA),
        ]

        with patch.object(agent.analyst, "_call_llm_raw", new_callable=AsyncMock, return_value='{"overall_assessment": "OK", "concerns": [], "adjustments": []}'):
            allocation = await agent.build_allocation(reports, current_positions, portfolio_equity=10000)

        entries_by_sym = {e.symbol: e for e in allocation.entries}
        assert entries_by_sym["OLD_STOCK"].action == "sell"
        assert entries_by_sym["OLD_STOCK"].target_weight == 0.0
