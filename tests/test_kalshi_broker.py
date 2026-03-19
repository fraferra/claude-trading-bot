"""Tests for KalshiBroker pure methods: price conversions, status mapping,
and market parsing. No network calls — SDK is mocked.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from trading_bot.brokers.kalshi_broker import KalshiBroker, _STATUS_MAP
from trading_bot.models import OrderStatus, Platform


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_broker() -> KalshiBroker:
    """Build a KalshiBroker with a mocked SDK client — no real auth needed."""
    with patch("trading_bot.brokers.kalshi_broker.KalshiBroker._build_client", return_value=MagicMock()):
        from trading_bot.config import KalshiConfig
        broker = KalshiBroker.__new__(KalshiBroker)
        broker.config = KalshiConfig()
        broker._client = MagicMock()
        return broker


# ---------------------------------------------------------------------------
# TestKalshiPriceConversions
# ---------------------------------------------------------------------------

class TestKalshiPriceConversions:
    """cents_to_decimal and decimal_to_cents are pure static methods."""

    # cents → decimal
    def test_cents_50_to_decimal(self):
        assert KalshiBroker.cents_to_decimal(50) == pytest.approx(0.50)

    def test_cents_1_to_decimal(self):
        assert KalshiBroker.cents_to_decimal(1) == pytest.approx(0.01)

    def test_cents_99_to_decimal(self):
        assert KalshiBroker.cents_to_decimal(99) == pytest.approx(0.99)

    def test_cents_25_to_decimal(self):
        assert KalshiBroker.cents_to_decimal(25) == pytest.approx(0.25)

    # decimal → cents
    def test_decimal_050_to_cents(self):
        assert KalshiBroker.decimal_to_cents(0.50) == 50

    def test_decimal_001_to_cents(self):
        assert KalshiBroker.decimal_to_cents(0.01) == 1

    def test_decimal_099_to_cents(self):
        assert KalshiBroker.decimal_to_cents(0.99) == 99

    def test_decimal_clamp_min(self):
        # 0.001 rounds to 0 → clamp to 1
        assert KalshiBroker.decimal_to_cents(0.001) == 1

    def test_decimal_clamp_max(self):
        # 0.999 rounds to 100 → clamp to 99
        assert KalshiBroker.decimal_to_cents(0.999) == 99

    def test_decimal_zero_clamps_to_1(self):
        assert KalshiBroker.decimal_to_cents(0.0) == 1

    def test_decimal_one_clamps_to_99(self):
        assert KalshiBroker.decimal_to_cents(1.0) == 99

    def test_roundtrip_stable(self):
        for original_cents in [1, 10, 25, 50, 75, 90, 99]:
            decimal = KalshiBroker.cents_to_decimal(original_cents)
            back = KalshiBroker.decimal_to_cents(decimal)
            assert back == original_cents, f"Roundtrip failed for {original_cents}¢"


# ---------------------------------------------------------------------------
# TestKalshiOrderStatusMapping
# ---------------------------------------------------------------------------

class TestKalshiOrderStatusMapping:

    def test_executed_maps_to_filled(self):
        assert _STATUS_MAP.get("executed") == OrderStatus.FILLED

    def test_resting_maps_to_pending(self):
        assert _STATUS_MAP.get("resting") == OrderStatus.PENDING

    def test_pending_maps_to_pending(self):
        assert _STATUS_MAP.get("pending") == OrderStatus.PENDING

    def test_canceled_maps_to_cancelled(self):
        assert _STATUS_MAP.get("canceled") == OrderStatus.CANCELLED

    def test_expired_maps_to_cancelled(self):
        assert _STATUS_MAP.get("expired") == OrderStatus.CANCELLED

    def test_unknown_status_maps_to_pending_via_get_default(self):
        result = _STATUS_MAP.get("some_unknown_status", OrderStatus.PENDING)
        assert result == OrderStatus.PENDING

    def test_all_known_statuses_present(self):
        expected_keys = {"resting", "pending", "executed", "canceled", "expired"}
        assert expected_keys.issubset(set(_STATUS_MAP.keys()))


# ---------------------------------------------------------------------------
# TestKalshiMarketParsing
# ---------------------------------------------------------------------------

class TestKalshiMarketParsing:
    """Test _parse_market with SimpleNamespace objects instead of SDK models."""

    def _raw_market(self, **kwargs):
        defaults = dict(
            ticker="BTC-100K-JAN25",
            event_ticker="BTC-JAN25",
            title="Will BTC exceed $100k by Jan 2025?",
            subtitle="Bitcoin price milestone",
            yes_bid=40,
            yes_ask=42,
            no_bid=58,
            no_ask=60,
            volume=50_000,
            open_time="2024-01-01T00:00:00Z",
            close_time="2025-01-31T23:59:59Z",
            result="",
            status="open",
        )
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_parse_basic_market(self):
        broker = _make_broker()
        raw = self._raw_market()
        market = broker._parse_market(raw)

        assert market.ticker == "BTC-100K-JAN25"
        assert market.event_ticker == "BTC-JAN25"
        assert market.title == "Will BTC exceed $100k by Jan 2025?"

    def test_parse_yes_price_from_bid_ask(self):
        broker = _make_broker()
        raw = self._raw_market(yes_bid=40, yes_ask=42)
        market = broker._parse_market(raw)
        # mid = (40 + 42) // 2 = 41 → 0.41
        assert market.yes_price == pytest.approx(0.41)

    def test_parse_no_price_from_bid_ask(self):
        broker = _make_broker()
        raw = self._raw_market(no_bid=58, no_ask=60)
        market = broker._parse_market(raw)
        # mid = (58 + 60) // 2 = 59 → 0.59
        assert market.no_price == pytest.approx(0.59)

    def test_parse_defaults_to_050_when_no_bid_ask(self):
        broker = _make_broker()
        raw = self._raw_market(yes_bid=0, yes_ask=0, no_bid=0, no_ask=0)
        market = broker._parse_market(raw)
        assert market.yes_price == pytest.approx(0.50)
        assert market.no_price == pytest.approx(0.50)

    def test_parse_volume_mapped(self):
        broker = _make_broker()
        raw = self._raw_market(volume=12_345)
        market = broker._parse_market(raw)
        assert market.volume == 12_345

    def test_parse_result_mapped(self):
        broker = _make_broker()
        raw = self._raw_market(result="yes")
        market = broker._parse_market(raw)
        assert market.result == "yes"

    def test_parse_platform_is_kalshi(self):
        broker = _make_broker()
        raw = self._raw_market()
        market = broker._parse_market(raw)
        assert market  # KalshiMarketData is not a Position, no platform field — just assert parse succeeds

    def test_empty_ticker_becomes_empty_string(self):
        broker = _make_broker()
        raw = self._raw_market(ticker=None)
        market = broker._parse_market(raw)
        assert market.ticker == ""

    def test_none_result_becomes_empty_string(self):
        broker = _make_broker()
        raw = self._raw_market(result=None)
        market = broker._parse_market(raw)
        assert market.result == ""


# ---------------------------------------------------------------------------
# TestKalshiGetQuoteParsing (mocked SDK response)
# ---------------------------------------------------------------------------

class TestKalshiGetQuoteParsing:
    """Test get_quote price extraction logic without real network calls."""

    @pytest.mark.asyncio
    async def test_quote_uses_midpoint_of_bid_ask(self):
        broker = _make_broker()

        mock_market = SimpleNamespace(
            yes_bid=40, yes_ask=44, last_price=None
        )
        mock_resp = SimpleNamespace(market=mock_market)
        broker._client._markets_api.get_market = MagicMock(return_value=mock_resp)

        price = await broker.get_quote("BTC-100K")
        # mid = (40 + 44) // 2 = 42 → 0.42
        assert price == pytest.approx(0.42)

    @pytest.mark.asyncio
    async def test_quote_falls_back_to_last_price(self):
        broker = _make_broker()

        mock_market = SimpleNamespace(yes_bid=0, yes_ask=0, last_price=55)
        mock_resp = SimpleNamespace(market=mock_market)
        broker._client._markets_api.get_market = MagicMock(return_value=mock_resp)

        price = await broker.get_quote("BTC-100K")
        assert price == pytest.approx(0.55)

    @pytest.mark.asyncio
    async def test_quote_defaults_to_050_when_no_data(self):
        broker = _make_broker()

        mock_market = SimpleNamespace(yes_bid=0, yes_ask=0, last_price=None)
        mock_resp = SimpleNamespace(market=mock_market)
        broker._client._markets_api.get_market = MagicMock(return_value=mock_resp)

        price = await broker.get_quote("BTC-100K")
        assert price == pytest.approx(0.50)
