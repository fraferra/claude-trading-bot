"""Tests for the Research Agent."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from trading_bot.agents.researcher import ResearchAgent, _clamp
from trading_bot.config import Config, ResearchAgentConfig, StocksConfig
from trading_bot.models import MarketRegime, NewsItem, StockData, StockFundamentals


def _make_config() -> Config:
    cfg = Config()
    cfg.anthropic_api_key = "test-key"
    cfg.stocks = StocksConfig(watchlist=["AAPL"])
    cfg.research_agent = ResearchAgentConfig()
    return cfg


def _make_stock_data(**kwargs) -> StockData:
    defaults = {
        "symbol": "AAPL",
        "current_price": 150.0,
        "open": 149.0,
        "high": 152.0,
        "low": 148.0,
        "volume": 5000000,
        "sma_20": 148.0,
        "sma_50": 145.0,
        "rsi_14": 55.0,
        "macd": 0.3,
        "macd_signal": 0.1,
        "price_history": [
            {"close": 140 + i, "date": f"2024-01-{i+1:02d}", "open": 139 + i,
             "high": 141 + i, "low": 138 + i, "volume": 1000000}
            for i in range(15)
        ],
    }
    defaults.update(kwargs)
    return StockData(**defaults)


def _make_fundamentals(**kwargs) -> StockFundamentals:
    defaults = {
        "symbol": "AAPL",
        "market_cap": 2.5e12,
        "pe_ratio": 28.0,
        "forward_pe": 25.0,
        "dividend_yield": 0.006,
        "beta": 1.2,
        "sector": "Technology",
        "fifty_two_week_high": 180.0,
        "fifty_two_week_low": 120.0,
    }
    defaults.update(kwargs)
    return StockFundamentals(**defaults)


class TestClamp:
    def test_within_range(self):
        assert _clamp(5.0, 1.0, 10.0) == 5.0

    def test_below_range(self):
        assert _clamp(-1.0, 1.0, 10.0) == 1.0

    def test_above_range(self):
        assert _clamp(15.0, 1.0, 10.0) == 10.0


class TestResearchAgent:
    @pytest.mark.asyncio
    async def test_score_success(self):
        """Research agent returns a complete report from LLM response."""
        config = _make_config()
        agent = ResearchAgent(config)

        llm_response = json.dumps({
            "financial_health": 7.5,
            "growth_potential": 8.0,
            "news_sentiment": 6.5,
            "news_impact": 5.0,
            "price_momentum": 7.0,
            "volatility_risk": 6.0,
            "reasoning": {
                "financial_health": "Strong balance sheet",
                "growth_potential": "AI revenue growing",
                "news_sentiment": "Positive coverage",
                "news_impact": "Moderate news flow",
                "price_momentum": "Above SMAs",
                "volatility_risk": "Normal range",
            },
            "catalysts": ["iPhone launch", "AI integration"],
            "risks": ["China slowdown", "Regulatory pressure"],
            "recommendation": "buy",
            "target_weight": 0.10,
            "company_name": "Apple Inc.",
            "sector": "Technology",
        })

        with patch("trading_bot.agents.researcher.get_stock_data", new_callable=AsyncMock, return_value=_make_stock_data()):
            with patch("trading_bot.agents.researcher.get_stock_fundamentals", new_callable=AsyncMock, return_value=_make_fundamentals()):
                with patch("trading_bot.agents.researcher.get_news", new_callable=AsyncMock, return_value=[]):
                    with patch.object(agent.analyst, "_call_llm_raw", new_callable=AsyncMock, return_value=llm_response):
                        report = await agent.score("AAPL", "Strong AI demand")

        assert report.symbol == "AAPL"
        assert report.company_name == "Apple Inc."
        assert report.dimension_scores.financial_health == 7.5
        assert report.dimension_scores.growth_potential == 8.0
        assert report.composite_score == pytest.approx(6.67, abs=0.1)
        assert report.llm_recommendation == "buy"
        assert report.target_weight == 0.10
        assert report.technical is not None
        assert report.fundamental is not None
        assert report.sentiment is not None
        assert len(report.catalysts) == 2

    @pytest.mark.asyncio
    async def test_score_fallback_on_error(self):
        """Falls back to neutral report with quant data if LLM fails."""
        config = _make_config()
        agent = ResearchAgent(config)

        with patch("trading_bot.agents.researcher.get_stock_data", new_callable=AsyncMock, return_value=_make_stock_data()):
            with patch("trading_bot.agents.researcher.get_stock_fundamentals", new_callable=AsyncMock, return_value=_make_fundamentals()):
                with patch("trading_bot.agents.researcher.get_news", new_callable=AsyncMock, return_value=[]):
                    with patch.object(agent.analyst, "_call_llm_raw", new_callable=AsyncMock, side_effect=Exception("API error")):
                        report = await agent.score("AAPL")

        assert report.symbol == "AAPL"
        assert report.composite_score == 5.0  # default neutral
        assert report.technical is not None  # quant data still present
        assert report.fundamental is not None

    @pytest.mark.asyncio
    async def test_score_clamps_dimensions(self):
        """Dimension scores are clamped to 1-10 range."""
        config = _make_config()
        agent = ResearchAgent(config)

        llm_response = json.dumps({
            "financial_health": 15.0,  # Over 10
            "growth_potential": -2.0,  # Under 1
            "news_sentiment": 5.0,
            "news_impact": 5.0,
            "price_momentum": 5.0,
            "volatility_risk": 5.0,
            "reasoning": {},
            "catalysts": [],
            "risks": [],
            "recommendation": "hold",
            "target_weight": 0.5,  # Over 0.15, should be clamped
            "company_name": "Test",
            "sector": "Tech",
        })

        with patch("trading_bot.agents.researcher.get_stock_data", new_callable=AsyncMock, return_value=_make_stock_data()):
            with patch("trading_bot.agents.researcher.get_stock_fundamentals", new_callable=AsyncMock, return_value=_make_fundamentals()):
                with patch("trading_bot.agents.researcher.get_news", new_callable=AsyncMock, return_value=[]):
                    with patch.object(agent.analyst, "_call_llm_raw", new_callable=AsyncMock, return_value=llm_response):
                        report = await agent.score("AAPL")

        assert report.dimension_scores.financial_health == 10.0
        assert report.dimension_scores.growth_potential == 1.0
        assert report.target_weight == 0.15
