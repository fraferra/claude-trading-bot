"""Tests for the Research Agent Monitor and integration."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_bot.agents.strategist import StrategistAgent, _validate_params
from trading_bot.config import Config, ResearchAgentConfig, StocksConfig
from trading_bot.db.database import Database
from trading_bot.db.repository import Repository
from trading_bot.models import (
    AllocationEntry,
    DimensionScores,
    OrderResult,
    OrderStatus,
    Platform,
    PortfolioAllocation,
    PortfolioSummary,
    Position,
    ResearchReport,
    Side,
    StrategyMemo,
)
from trading_bot.monitors.base import EventBus


def _make_config(**ra_kwargs) -> Config:
    cfg = Config()
    cfg.anthropic_api_key = "test-key"
    cfg.stocks = StocksConfig(watchlist=["AAPL", "MSFT"])
    cfg.research_agent = ResearchAgentConfig(**ra_kwargs)
    return cfg


@pytest.fixture
async def db():
    database = Database(":memory:")
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def repo(db):
    return Repository(db)


class TestValidateParams:
    def test_valid_params(self):
        result = _validate_params({"technical_weight": 0.4, "min_research_score": 6.0})
        assert result["technical_weight"] == 0.4
        assert result["min_research_score"] == 6.0

    def test_clamps_out_of_range(self):
        result = _validate_params({"technical_weight": 0.9, "min_research_score": 1.0})
        assert result["technical_weight"] == 0.6
        assert result["min_research_score"] == 3.0

    def test_ignores_unknown_params(self):
        result = _validate_params({"unknown_param": 999, "technical_weight": 0.3})
        assert "unknown_param" not in result
        assert result["technical_weight"] == 0.3

    def test_empty_changes(self):
        assert _validate_params({}) == {}


class TestStrategistApplyChanges:
    def test_applies_weight_changes(self):
        config = _make_config()
        repo = MagicMock()
        strategist = StrategistAgent(config, repo)

        memo = StrategyMemo(
            parameter_changes={"technical_weight": 0.40, "sentiment_weight": 0.25}
        )
        strategist.apply_changes(memo)

        assert config.stock_scorer.technical_weight == 0.40
        assert config.stock_scorer.sentiment_weight == 0.25

    def test_applies_research_agent_changes(self):
        config = _make_config()
        repo = MagicMock()
        strategist = StrategistAgent(config, repo)

        memo = StrategyMemo(
            parameter_changes={"min_research_score": 6.5, "max_single_position_pct": 0.12}
        )
        strategist.apply_changes(memo)

        assert config.research_agent.min_research_score == 6.5
        assert config.research_agent.max_single_position_pct == 0.12

    def test_no_changes(self):
        config = _make_config()
        repo = MagicMock()
        strategist = StrategistAgent(config, repo)
        original_weight = config.stock_scorer.technical_weight

        memo = StrategyMemo(parameter_changes={})
        strategist.apply_changes(memo)

        assert config.stock_scorer.technical_weight == original_weight


class TestRepositoryResearch:
    @pytest.mark.asyncio
    async def test_insert_and_get_research_reports(self, repo):
        rid = await repo.insert_research_report(
            symbol="AAPL",
            company_name="Apple Inc.",
            sector="Technology",
            composite_score=7.5,
            dimension_scores_json='{"financial_health": 8}',
            recommendation="buy",
            target_weight=0.10,
        )
        assert rid > 0

        reports = await repo.get_research_reports(symbol="AAPL")
        assert len(reports) == 1
        assert reports[0]["symbol"] == "AAPL"
        assert reports[0]["composite_score"] == 7.5

    @pytest.mark.asyncio
    async def test_insert_and_get_portfolio_allocations(self, repo):
        aid = await repo.insert_portfolio_allocation(
            entries_json='[{"symbol": "AAPL", "target_weight": 0.10}]',
            cash_reserve=0.30,
            rebalance_needed=True,
            reasoning="Test allocation",
        )
        assert aid > 0

        allocations = await repo.get_portfolio_allocations()
        assert len(allocations) == 1
        assert allocations[0]["cash_reserve"] == 0.30

    @pytest.mark.asyncio
    async def test_insert_and_get_strategy_memos(self, repo):
        mid = await repo.insert_strategy_memo(
            period_start="2024-01-01",
            period_end="2024-01-07",
            total_return_pct=2.5,
            win_rate=0.6,
            lessons_json='["Lesson 1"]',
            parameter_changes_json='{"technical_weight": 0.4}',
        )
        assert mid > 0

        memos = await repo.get_strategy_memos()
        assert len(memos) == 1
        assert memos[0]["total_return_pct"] == 2.5

    @pytest.mark.asyncio
    async def test_insert_and_get_discovery_runs(self, repo):
        did = await repo.insert_discovery_run(
            candidates_json='[{"symbol": "AAPL", "reason": "test"}]',
            source_queries_json='["stock market movers"]',
            num_candidates=1,
        )
        assert did > 0

        runs = await repo.get_discovery_runs()
        assert len(runs) == 1
        assert runs[0]["num_candidates"] == 1


class TestResearchAgentMonitor:
    @pytest.mark.asyncio
    async def test_run_cycle_full_pipeline(self, repo):
        """Test the full pipeline: discovery → research → selection → execution."""
        from trading_bot.monitors.research_agent import ResearchAgentMonitor

        config = _make_config(min_research_score=5.0)

        # Mock broker
        mock_broker = AsyncMock()
        mock_broker.get_account.return_value = PortfolioSummary(
            cash=50000, equity=50000, positions=[], daily_pnl=0, platform=Platform.ALPACA
        )
        mock_broker.get_positions.return_value = []
        mock_broker.get_quote.return_value = 150.0
        mock_broker.submit_order.return_value = OrderResult(
            order_id="test-123", symbol="AAPL", side=Side.BUY,
            quantity=10, status=OrderStatus.FILLED, filled_price=150.0,
            platform=Platform.ALPACA,
        )

        brokers = {"alpaca": mock_broker}
        event_bus = EventBus()
        risk_manager = MagicMock()
        risk_manager.check_order.return_value = MagicMock(approved=True, adjusted_quantity=None)
        risk_manager.check_decision.return_value = MagicMock(approved=True)

        await repo.upsert_monitor_state("test_research_1", "research_agent", "running")

        monitor = ResearchAgentMonitor(
            monitor_id="test_research_1",
            config=config,
            repo=repo,
            event_bus=event_bus,
            brokers=brokers,
            risk_manager=risk_manager,
        )

        # Mock the agents
        mock_report = ResearchReport(
            symbol="AAPL",
            company_name="Apple",
            sector="Tech",
            composite_score=8.0,
            dimension_scores=DimensionScores(
                financial_health=8, growth_potential=8, news_sentiment=7,
                news_impact=6, price_momentum=8, volatility_risk=7,
            ),
            llm_recommendation="buy",
            target_weight=0.10,
        )

        mock_allocation = PortfolioAllocation(
            entries=[AllocationEntry(
                symbol="AAPL", target_weight=0.10, current_weight=0.0,
                research_score=8.0, action="buy",
            )],
            cash_reserve=0.90,
            total_positions=1,
            rebalance_needed=True,
            reasoning="Test allocation",
        )

        with patch("trading_bot.monitors.research_agent.DiscoveryAgent") as MockDiscovery:
            with patch("trading_bot.monitors.research_agent.ResearchAgent") as MockResearcher:
                with patch("trading_bot.monitors.research_agent.SelectorAgent") as MockSelector:
                    with patch("trading_bot.monitors.research_agent.ExecutorAgent") as MockExecutor:
                        MockDiscovery.return_value.find_candidates = AsyncMock(return_value=[("AAPL", "Strong demand")])
                        MockDiscovery.return_value.source_queries = ["test query"]
                        MockResearcher.return_value.score = AsyncMock(return_value=mock_report)
                        MockSelector.return_value.build_allocation = AsyncMock(return_value=mock_allocation)
                        MockExecutor.return_value.rebalance = AsyncMock(return_value=[
                            OrderResult(
                                order_id="exec-1", symbol="AAPL", side=Side.BUY,
                                quantity=10, status=OrderStatus.FILLED, filled_price=150.0,
                                platform=Platform.ALPACA,
                            )
                        ])

                        await monitor.run_cycle()

        # Verify data was persisted
        discoveries = await repo.get_discovery_runs()
        assert len(discoveries) == 1

        reports = await repo.get_research_reports()
        assert len(reports) == 1
        assert reports[0]["symbol"] == "AAPL"

        allocations = await repo.get_portfolio_allocations()
        assert len(allocations) == 1
