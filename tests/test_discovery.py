"""Tests for the Discovery Agent."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from trading_bot.agents.discovery import DiscoveryAgent, _strip_markdown
from trading_bot.config import Config, ResearchAgentConfig, StocksConfig
from trading_bot.models import NewsItem


def _make_config(**kwargs) -> Config:
    cfg = Config()
    cfg.anthropic_api_key = "test-key"
    cfg.stocks = StocksConfig(watchlist=["AAPL", "MSFT"])
    cfg.research_agent = ResearchAgentConfig(**kwargs)
    return cfg


class TestStripMarkdown:
    def test_no_fences(self):
        assert _strip_markdown('{"foo": 1}') == '{"foo": 1}'

    def test_with_fences(self):
        text = '```json\n{"foo": 1}\n```'
        assert _strip_markdown(text) == '{"foo": 1}'

    def test_with_fences_no_trailing(self):
        text = '```json\n{"foo": 1}'
        assert _strip_markdown(text) == '{"foo": 1}'


class TestDiscoveryAgent:
    @pytest.mark.asyncio
    async def test_find_candidates_success(self):
        """Discovery agent returns parsed candidates from LLM."""
        config = _make_config(max_candidates=10)
        agent = DiscoveryAgent(config)

        llm_response = json.dumps({
            "candidates": [
                {"symbol": "NVDA", "reason": "Strong AI demand"},
                {"symbol": "TSLA", "reason": "Record deliveries"},
                {"symbol": "AMD", "reason": "New chip launch"},
            ]
        })

        news_items = [NewsItem(title="Market rallies on tech", source="Reuters")]

        with patch.object(agent.analyst, "_call_llm_raw", new_callable=AsyncMock, return_value=llm_response):
            with patch("trading_bot.agents.discovery.get_news", new_callable=AsyncMock, return_value=news_items):
                candidates = await agent.find_candidates()

        # Should have LLM candidates + watchlist not already included
        symbols = [c[0] for c in candidates]
        assert "NVDA" in symbols
        assert "TSLA" in symbols
        assert "AMD" in symbols
        assert "AAPL" in symbols  # from watchlist
        assert "MSFT" in symbols  # from watchlist

    @pytest.mark.asyncio
    async def test_find_candidates_deduplicates(self):
        """Watchlist symbols already in LLM output are not duplicated."""
        config = _make_config()
        agent = DiscoveryAgent(config)

        llm_response = json.dumps({
            "candidates": [
                {"symbol": "AAPL", "reason": "New iPhone launch"},
                {"symbol": "NVDA", "reason": "AI boom"},
            ]
        })

        with patch.object(agent.analyst, "_call_llm_raw", new_callable=AsyncMock, return_value=llm_response):
            with patch("trading_bot.agents.discovery.get_news", new_callable=AsyncMock, return_value=[]):
                candidates = await agent.find_candidates()

        symbols = [c[0] for c in candidates]
        assert symbols.count("AAPL") == 1  # Not duplicated

    @pytest.mark.asyncio
    async def test_find_candidates_respects_max(self):
        """Candidates are limited to max_candidates."""
        config = _make_config(max_candidates=3)
        agent = DiscoveryAgent(config)

        llm_response = json.dumps({
            "candidates": [
                {"symbol": f"SYM{i}", "reason": "test"} for i in range(10)
            ]
        })

        with patch.object(agent.analyst, "_call_llm_raw", new_callable=AsyncMock, return_value=llm_response):
            with patch("trading_bot.agents.discovery.get_news", new_callable=AsyncMock, return_value=[]):
                candidates = await agent.find_candidates()

        assert len(candidates) <= 3

    @pytest.mark.asyncio
    async def test_find_candidates_fallback_on_error(self):
        """Falls back to watchlist if LLM call fails."""
        config = _make_config()
        agent = DiscoveryAgent(config)

        with patch.object(agent.analyst, "_call_llm_raw", new_callable=AsyncMock, side_effect=Exception("API error")):
            with patch("trading_bot.agents.discovery.get_news", new_callable=AsyncMock, return_value=[]):
                candidates = await agent.find_candidates()

        symbols = [c[0] for c in candidates]
        assert "AAPL" in symbols
        assert "MSFT" in symbols

    def test_source_queries(self):
        config = _make_config()
        agent = DiscoveryAgent(config)
        assert len(agent.source_queries) == 3
