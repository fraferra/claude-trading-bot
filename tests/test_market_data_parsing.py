"""Tests for market data parsing functions.

Tests parse_event_to_model, get_polymarket_data input validation,
and PolymarketData token extraction — all without network calls.
"""

from __future__ import annotations

import pytest

from trading_bot.analysis.market_data import parse_event_to_model
from trading_bot.models import EventData, MarketOutcome


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------

def _raw_event(**kwargs) -> dict:
    """Build a minimal Gamma API event dict."""
    base = {
        "id": "evt-001",
        "title": "Will BTC exceed $100k?",
        "slug": "btc-100k",
        "endDate": "2025-12-31",
        "markets": [
            {
                "conditionId": "cond-abc",
                "question": "Will BTC exceed $100k?",
                "groupItemTitle": "Yes",
                "liquidity": 50_000.0,
                "tokens": [
                    {"outcome": "Yes", "price": "0.55", "token_id": "tok-yes-abc"},
                    {"outcome": "No",  "price": "0.45", "token_id": "tok-no-abc"},
                ],
            }
        ],
    }
    base.update(kwargs)
    return base


def _raw_market(**kwargs) -> dict:
    base = {
        "conditionId": "cond-abc",
        "question": "Will BTC exceed $100k?",
        "groupItemTitle": "Yes",
        "liquidity": 50_000.0,
        "tokens": [
            {"outcome": "Yes", "price": "0.55", "token_id": "tok-yes-abc"},
            {"outcome": "No",  "price": "0.45", "token_id": "tok-no-abc"},
        ],
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# TestParseEventToModel
# ---------------------------------------------------------------------------

class TestParseEventToModel:

    def test_parse_basic_event_returns_event_data(self):
        event = parse_event_to_model(_raw_event())
        assert isinstance(event, EventData)

    def test_parse_event_id_mapped(self):
        event = parse_event_to_model(_raw_event(id="my-event-id"))
        assert event.event_id == "my-event-id"

    def test_parse_title_mapped(self):
        event = parse_event_to_model(_raw_event(title="Federal Reserve 2025"))
        assert event.title == "Federal Reserve 2025"

    def test_parse_slug_mapped(self):
        event = parse_event_to_model(_raw_event(slug="fed-2025"))
        assert event.slug == "fed-2025"

    def test_parse_end_date_mapped(self):
        event = parse_event_to_model(_raw_event(endDate="2025-06-30"))
        assert event.end_date == "2025-06-30"

    def test_parse_alternative_end_date_key(self):
        raw = _raw_event()
        raw.pop("endDate", None)
        raw["end_date"] = "2025-07-01"
        event = parse_event_to_model(raw)
        assert event.end_date == "2025-07-01"

    def test_parse_outcomes_count_matches_markets(self):
        event = parse_event_to_model(_raw_event())
        assert len(event.outcomes) == 1

    def test_parse_yes_price_from_tokens(self):
        event = parse_event_to_model(_raw_event())
        outcome = event.outcomes[0]
        assert outcome.yes_price == pytest.approx(0.55)

    def test_parse_no_price_from_tokens(self):
        event = parse_event_to_model(_raw_event())
        outcome = event.outcomes[0]
        assert outcome.no_price == pytest.approx(0.45)

    def test_parse_token_id_extracted_from_yes_token(self):
        event = parse_event_to_model(_raw_event())
        outcome = event.outcomes[0]
        assert outcome.token_id == "tok-yes-abc"

    def test_parse_condition_id_mapped(self):
        event = parse_event_to_model(_raw_event())
        outcome = event.outcomes[0]
        assert outcome.condition_id == "cond-abc"

    def test_parse_condition_id_alternate_key(self):
        raw = _raw_event(markets=[{
            "condition_id": "cond-alt",
            "question": "Alt question",
            "liquidity": 1000.0,
            "tokens": [
                {"outcome": "Yes", "price": "0.60", "token_id": "tok-y"},
                {"outcome": "No",  "price": "0.40", "token_id": "tok-n"},
            ],
        }])
        event = parse_event_to_model(raw)
        assert event.outcomes[0].condition_id == "cond-alt"

    def test_parse_liquidity_mapped(self):
        event = parse_event_to_model(_raw_event())
        outcome = event.outcomes[0]
        assert outcome.liquidity == pytest.approx(50_000.0)

    def test_missing_tokens_defaults_to_50_50(self):
        raw = _raw_event(markets=[{
            "conditionId": "cond-no-tokens",
            "question": "No tokens here",
            "liquidity": 0.0,
            "tokens": [],
        }])
        event = parse_event_to_model(raw)
        outcome = event.outcomes[0]
        assert outcome.yes_price == pytest.approx(0.5)
        assert outcome.no_price == pytest.approx(0.5)

    def test_empty_markets_returns_empty_outcomes(self):
        raw = _raw_event(markets=[])
        event = parse_event_to_model(raw)
        assert event.outcomes == []

    def test_multiple_markets_parsed(self):
        raw = _raw_event(markets=[
            _raw_market(conditionId="c1", question="Q1"),
            _raw_market(conditionId="c2", question="Q2"),
            _raw_market(conditionId="c3", question="Q3"),
        ])
        event = parse_event_to_model(raw)
        assert len(event.outcomes) == 3

    def test_multiple_markets_condition_ids_distinct(self):
        raw = _raw_event(markets=[
            _raw_market(conditionId="c1", question="Q1"),
            _raw_market(conditionId="c2", question="Q2"),
        ])
        event = parse_event_to_model(raw)
        condition_ids = {o.condition_id for o in event.outcomes}
        assert condition_ids == {"c1", "c2"}

    def test_missing_condition_id_becomes_empty_string(self):
        raw = _raw_event(markets=[{
            "question": "No condition ID",
            "liquidity": 0.0,
            "tokens": [],
        }])
        event = parse_event_to_model(raw)
        assert event.outcomes[0].condition_id == ""

    def test_price_rounded_to_four_decimals(self):
        raw = _raw_event(markets=[{
            "conditionId": "cond-x",
            "question": "Rounding test",
            "liquidity": 0.0,
            "tokens": [{"outcome": "Yes", "price": "0.333333333", "token_id": "t1"}],
        }])
        event = parse_event_to_model(raw)
        yes_price = event.outcomes[0].yes_price
        assert yes_price == round(yes_price, 4)

    def test_numeric_string_prices_parsed(self):
        raw = _raw_event(markets=[{
            "conditionId": "cond-y",
            "question": "String price",
            "liquidity": 0.0,
            "tokens": [
                {"outcome": "Yes", "price": "0.72", "token_id": "t-yes"},
                {"outcome": "No",  "price": "0.28", "token_id": "t-no"},
            ],
        }])
        event = parse_event_to_model(raw)
        assert event.outcomes[0].yes_price == pytest.approx(0.72)
        assert event.outcomes[0].no_price == pytest.approx(0.28)


# ---------------------------------------------------------------------------
# TestGetPolymarketDataValidation
# ---------------------------------------------------------------------------

class TestGetPolymarketDataValidation:
    """Test that get_polymarket_data raises on empty condition_id without network."""

    @pytest.mark.asyncio
    async def test_empty_condition_id_raises_value_error(self):
        from trading_bot.analysis.market_data import get_polymarket_data
        with pytest.raises(ValueError, match="condition_id must not be empty"):
            await get_polymarket_data("")

    @pytest.mark.asyncio
    async def test_none_condition_id_raises_value_error(self):
        from trading_bot.analysis.market_data import get_polymarket_data
        with pytest.raises((ValueError, TypeError)):
            await get_polymarket_data(None)  # type: ignore
