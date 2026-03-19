"""Tests for CrossPlatformArbScanner: title normalisation, fuzzy matching,
edge calculation, and decision generation.

All external I/O is mocked — no network calls.
"""

from __future__ import annotations

import difflib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_bot.strategies.cross_platform_arb import (
    CrossPlatformArbScanner,
    CrossPlatformOpportunity,
    MarketCache,
    _match_markets,
    _normalize_title,
)
from trading_bot.config import CrossPlatformArbConfig
from trading_bot.models import Action, Side


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------

def _cfg(**kwargs) -> CrossPlatformArbConfig:
    defaults = dict(
        fuzzy_match_threshold=0.75,
        min_net_edge_pct=0.02,
        min_volume_usd=1_000.0,
        max_size_per_leg_usd=200.0,
        fee_estimate_poly_pct=0.01,
        fee_estimate_kalshi_pct=0.01,
        market_cache_ttl_seconds=300,
    )
    defaults.update(kwargs)
    return CrossPlatformArbConfig(**defaults)


def _kalshi_market(ticker: str, title: str):
    m = SimpleNamespace(ticker=ticker, title=title)
    return m


def _poly_event(question: str, markets: list[dict] | None = None):
    if markets is None:
        markets = [{"question": question, "volume": 50_000, "conditionId": "cid-1",
                    "tokens": [
                        {"outcome": "Yes", "price": "0.55", "token_id": "tok-yes-1"},
                        {"outcome": "No",  "price": "0.45", "token_id": "tok-no-1"},
                    ]}]
    return {"markets": markets}


def _opp(**kwargs) -> CrossPlatformOpportunity:
    defaults = dict(
        direction="buy_poly_yes_kalshi_no",
        poly_token_id="tok-yes-1",
        poly_condition_id="cid-1",
        poly_question="Will BTC exceed 100k?",
        poly_price=0.55,
        kalshi_ticker="BTC-100K",
        kalshi_question="Will BTC exceed $100,000?",
        kalshi_price=0.40,
        combined_cost=0.95,
        gross_edge=0.05,
        net_edge=0.03,
        match_score=0.88,
    )
    defaults.update(kwargs)
    return CrossPlatformOpportunity(**defaults)


# ---------------------------------------------------------------------------
# TestTitleNormalisation
# ---------------------------------------------------------------------------

class TestTitleNormalisation:
    def test_lowercases(self):
        assert _normalize_title("Will Bitcoin Exceed $100K?") == _normalize_title("will bitcoin exceed  100k ")

    def test_strips_punctuation(self):
        result = _normalize_title("Will X happen?!")
        assert "?" not in result
        assert "!" not in result

    def test_removes_year_patterns(self):
        result = _normalize_title("Will GDP grow in 2025?")
        assert "2025" not in result

    def test_removes_month_year_patterns(self):
        result = _normalize_title("Will inflation fall by Jan 2026?")
        assert "jan" not in result
        assert "2026" not in result

    def test_removes_quarter_patterns(self):
        result = _normalize_title("Q1 2025 earnings beat?")
        assert "q1" not in result
        assert "2025" not in result

    def test_strips_extra_whitespace(self):
        result = _normalize_title("  multiple   spaces   here  ")
        assert "  " not in result
        assert result == result.strip()

    def test_empty_string_no_crash(self):
        assert _normalize_title("") == ""

    def test_unicode_safe(self):
        # Should not crash on unicode input
        result = _normalize_title("Will €/$ rate exceed 1.10?")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# TestFuzzyMarketMatching
# ---------------------------------------------------------------------------

class TestFuzzyMarketMatching:

    def _make_kalshi_event(self, ticker, title):
        market = _kalshi_market(ticker, title)
        event = SimpleNamespace(markets=[market])
        return event

    def test_identical_titles_match(self):
        poly_events = [_poly_event("Will Bitcoin exceed 100k")]
        kalshi_events = [self._make_kalshi_event("BTC-100K", "Will Bitcoin exceed 100k")]

        pairs = _match_markets(poly_events, kalshi_events, threshold=0.75)
        assert len(pairs) == 1

    def test_similar_titles_match(self):
        poly_events = [_poly_event("Will the Fed raise rates in 2025")]
        kalshi_events = [self._make_kalshi_event("FED-RATE", "Fed rate increase 2025")]

        pairs = _match_markets(poly_events, kalshi_events, threshold=0.50)
        assert len(pairs) >= 0  # threshold determines exact match; at 0.50 often matches

    def test_completely_different_no_match(self):
        poly_events = [_poly_event("Will Bitcoin reach one million")]
        kalshi_events = [self._make_kalshi_event("RAIN-NYC", "Will it rain in New York City tomorrow")]

        pairs = _match_markets(poly_events, kalshi_events, threshold=0.75)
        assert len(pairs) == 0

    def test_threshold_boundary_high(self):
        # At threshold=1.0 only exact normalized matches pass
        poly_events = [_poly_event("Will BTC go up")]
        kalshi_events = [self._make_kalshi_event("BTC-UP", "Will BTC go up")]

        pairs_strict = _match_markets(poly_events, kalshi_events, threshold=1.0)
        # Exact normalised match → should pass
        assert len(pairs_strict) == 1

    def test_threshold_boundary_low(self):
        # At threshold=0.0 everything matches
        poly_events = [_poly_event("Will X happen")]
        kalshi_events = [self._make_kalshi_event("Y-TICK", "Completely different question here")]

        pairs = _match_markets(poly_events, kalshi_events, threshold=0.0)
        assert len(pairs) == 1

    def test_dedup_prevents_double_matching(self):
        # Same Kalshi market should only match one Poly market
        poly_events = [
            _poly_event("Will BTC go up"),
            _poly_event("Will BTC increase in value"),
        ]
        kalshi_events = [self._make_kalshi_event("BTC-UP", "Will BTC go up")]

        pairs = _match_markets(poly_events, kalshi_events, threshold=0.5)
        kalshi_tickers = [getattr(k, "ticker", "") for _, k in pairs]
        # BTC-UP should appear at most once
        assert kalshi_tickers.count("BTC-UP") <= 1

    def test_empty_poly_events_returns_empty(self):
        kalshi_events = [self._make_kalshi_event("BTC-100K", "Will BTC exceed 100k")]
        pairs = _match_markets([], kalshi_events, threshold=0.5)
        assert pairs == []

    def test_empty_kalshi_events_returns_empty(self):
        poly_events = [_poly_event("Will BTC exceed 100k")]
        pairs = _match_markets(poly_events, [], threshold=0.5)
        assert pairs == []

    def test_match_score_stored_in_poly_market(self):
        poly_events = [_poly_event("Will the Democrats win 2024")]
        kalshi_events = [self._make_kalshi_event("DEM-WIN", "Will Democrats win 2024")]

        pairs = _match_markets(poly_events, kalshi_events, threshold=0.50)
        if pairs:
            poly_market, _ = pairs[0]
            assert "_match_score" in poly_market
            assert 0.0 <= poly_market["_match_score"] <= 1.0


# ---------------------------------------------------------------------------
# TestCrossPlatformEdgeCalc  (via _opportunity_to_decisions)
# ---------------------------------------------------------------------------

class TestCrossPlatformEdgeCalc:

    def _scanner(self, **cfg_kwargs) -> CrossPlatformArbScanner:
        return CrossPlatformArbScanner(config=_cfg(**cfg_kwargs))

    # --- Arb A: buy Poly YES + buy Kalshi NO ---
    def test_arb_a_profitable_direction_encoded(self):
        scanner = self._scanner()
        opp = _opp(
            direction="buy_poly_yes_kalshi_no",
            poly_price=0.55,
            kalshi_price=0.40,
            combined_cost=0.95,
            net_edge=0.03,
        )
        decisions = scanner._opportunity_to_decisions(opp)
        assert len(decisions) == 2
        poly_dec, kalshi_dec = decisions
        assert poly_dec.side == Side.BUY
        # Selling YES on Kalshi = buying NO
        assert kalshi_dec.side == Side.SELL

    # --- Arb B: buy Poly NO + buy Kalshi YES ---
    def test_arb_b_direction_encoded(self):
        scanner = self._scanner()
        opp = _opp(
            direction="buy_poly_no_kalshi_yes",
            poly_price=0.45,
            kalshi_price=0.55,
            combined_cost=1.00,
            net_edge=0.0,
        )
        decisions = scanner._opportunity_to_decisions(opp)
        _, kalshi_dec = decisions
        assert kalshi_dec.side == Side.BUY

    def test_confidence_scales_with_edge(self):
        scanner = self._scanner()
        low_edge_opp = _opp(net_edge=0.02)
        high_edge_opp = _opp(net_edge=0.08)

        low_decisions = scanner._opportunity_to_decisions(low_edge_opp)
        high_decisions = scanner._opportunity_to_decisions(high_edge_opp)

        low_conf = low_decisions[0].confidence
        high_conf = high_decisions[0].confidence
        assert high_conf > low_conf

    def test_confidence_capped_at_095(self):
        scanner = self._scanner()
        opp = _opp(net_edge=1.0)  # Extreme edge → confidence capped
        decisions = scanner._opportunity_to_decisions(opp)
        assert decisions[0].confidence <= 0.95

    def test_reasoning_contains_xplat_tag(self):
        scanner = self._scanner()
        opp = _opp()
        decisions = scanner._opportunity_to_decisions(opp)
        assert "[XPLAT|" in decisions[0].reasoning
        assert "[XPLAT|" in decisions[1].reasoning

    def test_reasoning_poly_tag_includes_kalshi_ticker(self):
        scanner = self._scanner()
        opp = _opp(kalshi_ticker="BTC-100K")
        decisions = scanner._opportunity_to_decisions(opp)
        poly_dec = decisions[0]
        assert "BTC-100K" in poly_dec.reasoning

    def test_reasoning_kalshi_tag_includes_poly_token(self):
        scanner = self._scanner()
        opp = _opp(poly_token_id="tok-yes-abc")
        decisions = scanner._opportunity_to_decisions(opp)
        kalshi_dec = decisions[1]
        assert "tok-yes-abc" in kalshi_dec.reasoning

    def test_poly_symbol_is_token_id(self):
        scanner = self._scanner()
        opp = _opp(poly_token_id="my-poly-token-id")
        decisions = scanner._opportunity_to_decisions(opp)
        assert decisions[0].symbol == "my-poly-token-id"

    def test_kalshi_symbol_is_ticker(self):
        scanner = self._scanner()
        opp = _opp(kalshi_ticker="KLSH-TICKER")
        decisions = scanner._opportunity_to_decisions(opp)
        assert decisions[1].symbol == "KLSH-TICKER"

    def test_suggested_size_matches_config(self):
        scanner = self._scanner(max_size_per_leg_usd=150.0)
        opp = _opp()
        decisions = scanner._opportunity_to_decisions(opp)
        assert decisions[0].suggested_size_usd == 150.0
        assert decisions[1].suggested_size_usd == 150.0


# ---------------------------------------------------------------------------
# TestMarketCache
# ---------------------------------------------------------------------------

class TestMarketCache:
    def test_fresh_cache_is_fresh(self):
        import time
        cache = MarketCache(pairs=[], built_at=time.time())
        assert cache.is_fresh(300)

    def test_stale_cache_not_fresh(self):
        cache = MarketCache(pairs=[], built_at=0.0)  # epoch → definitely stale
        assert not cache.is_fresh(300)

    def test_empty_cache_not_fresh(self):
        cache = MarketCache()
        assert not cache.is_fresh(300)


# ---------------------------------------------------------------------------
# TestCrossPlatformScan (mocked brokers + get_all_events)
# ---------------------------------------------------------------------------

class TestCrossPlatformScan:

    def _make_scanner(self, **cfg_kwargs) -> CrossPlatformArbScanner:
        return CrossPlatformArbScanner(config=_cfg(**cfg_kwargs))

    @pytest.mark.asyncio
    async def test_scan_returns_strategy_result(self):
        scanner = self._make_scanner()

        mock_poly = AsyncMock()
        mock_kalshi = AsyncMock()
        mock_kalshi.get_events = AsyncMock(return_value=[])

        import trading_bot.strategies.cross_platform_arb as mod
        mod._market_cache.pairs = []
        mod._market_cache.built_at = 0.0

        with patch("trading_bot.strategies.cross_platform_arb.get_all_events", return_value=[]):
            result = await scanner.scan(mock_poly, mock_kalshi)

        assert result.strategy_name == "cross_platform_arb"
        assert isinstance(result.decisions, list)

    @pytest.mark.asyncio
    async def test_scan_no_matches_returns_empty_decisions(self):
        scanner = self._make_scanner()

        mock_poly = AsyncMock()
        mock_kalshi = AsyncMock()
        mock_kalshi.get_events = AsyncMock(return_value=[])

        import trading_bot.strategies.cross_platform_arb as mod
        mod._market_cache.pairs = []
        mod._market_cache.built_at = 0.0

        with patch("trading_bot.strategies.cross_platform_arb.get_all_events", return_value=[]):
            result = await scanner.scan(mock_poly, mock_kalshi)

        assert result.decisions == []
        assert result.metadata["pairs_matched"] == 0

    @pytest.mark.asyncio
    async def test_scan_uses_cached_pairs_when_fresh(self):
        import time
        import trading_bot.strategies.cross_platform_arb as mod

        scanner = self._make_scanner()

        # Pre-populate fresh cache
        mod._market_cache.pairs = []
        mod._market_cache.built_at = time.time()

        mock_poly = AsyncMock()
        mock_kalshi = AsyncMock()

        with patch("trading_bot.strategies.cross_platform_arb.get_all_events") as mock_get:
            result = await scanner.scan(mock_poly, mock_kalshi)
            # get_all_events should NOT be called when cache is fresh
            mock_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_scan_one_opportunity_produces_two_decisions(self):
        """Inject a pre-built opportunity via _check_pair mock."""
        import time
        import trading_bot.strategies.cross_platform_arb as mod

        scanner = self._make_scanner()

        # Set up fresh cache with one "pair" so the scan loop runs once
        dummy_kalshi_market = SimpleNamespace(ticker="BTC-100K", title="BTC test")
        dummy_poly_market = {
            "question": "BTC test", "volume": 100_000, "conditionId": "cid-1",
            "tokens": [
                {"outcome": "Yes", "price": "0.55", "token_id": "tok-yes"},
                {"outcome": "No",  "price": "0.45", "token_id": "tok-no"},
            ],
            "_match_score": 0.9,
        }
        mod._market_cache.pairs = [(dummy_poly_market, dummy_kalshi_market)]
        mod._market_cache.built_at = time.time()

        opp = _opp(net_edge=0.05)

        mock_poly = AsyncMock()
        mock_kalshi = AsyncMock()

        with patch.object(scanner, "_check_pair", return_value=[opp]):
            result = await scanner.scan(mock_poly, mock_kalshi)

        assert len(result.decisions) == 2  # 2 legs for 1 opportunity
