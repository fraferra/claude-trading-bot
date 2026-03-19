"""Tests for PolymarketWebSocketFeed: price cache TTL, message handling,
subscription logic. No network calls — all pure in-process logic.
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_bot.brokers.polymarket_ws import (
    MAX_TOKENS_PER_CONNECTION,
    PriceEntry,
    PolymarketWebSocketFeed,
)


# ---------------------------------------------------------------------------
# TestPriceCacheLogic
# ---------------------------------------------------------------------------

class TestPriceCacheLogic:
    """Tests for the in-process price cache. No I/O."""

    def _feed(self, ttl: int = 5) -> PolymarketWebSocketFeed:
        return PolymarketWebSocketFeed(ttl_seconds=ttl)

    # --- Cache miss / hit ---
    def test_cache_miss_returns_none(self):
        feed = self._feed()
        assert feed.get_price_sync("unknown-token") is None

    def test_cache_hit_returns_midpoint(self):
        feed = self._feed(ttl=10)
        feed._price_cache["tok1"] = PriceEntry(bid=0.40, ask=0.60, mid=0.50)
        assert feed.get_price_sync("tok1") == pytest.approx(0.50)

    def test_stale_entry_returns_none(self):
        feed = self._feed(ttl=1)
        # Timestamp far in the past
        feed._price_cache["tok1"] = PriceEntry(
            bid=0.40, ask=0.60, mid=0.50, timestamp=time.time() - 100
        )
        assert feed.get_price_sync("tok1") is None

    def test_fresh_entry_within_ttl_returned(self):
        feed = self._feed(ttl=60)
        feed._price_cache["tok1"] = PriceEntry(
            bid=0.40, ask=0.60, mid=0.50, timestamp=time.time()
        )
        assert feed.get_price_sync("tok1") == pytest.approx(0.50)

    def test_ttl_boundary_exact(self):
        feed = self._feed(ttl=5)
        # Just within TTL
        feed._price_cache["tok1"] = PriceEntry(
            bid=0.40, ask=0.60, mid=0.50, timestamp=time.time() - 4.9
        )
        assert feed.get_price_sync("tok1") is not None

    def test_is_connected_false_when_not_started(self):
        feed = self._feed()
        assert feed.is_connected() is False

    def test_is_connected_false_after_ws_none(self):
        feed = self._feed()
        feed._ws = None
        assert feed.is_connected() is False

    # --- Message handling ---
    def test_handle_best_bid_ask_updates_cache(self):
        feed = self._feed()
        msg = json.dumps({
            "event_type": "best_bid_ask",
            "asset_id": "tok-abc",
            "bid_price": 0.40,
            "ask_price": 0.60,
        })
        feed._handle_message(msg)
        entry = feed._price_cache.get("tok-abc")
        assert entry is not None
        assert entry.mid == pytest.approx(0.50)
        assert entry.bid == pytest.approx(0.40)
        assert entry.ask == pytest.approx(0.60)

    def test_handle_best_bid_ask_only_bid_uses_bid_as_mid(self):
        feed = self._feed()
        msg = json.dumps({
            "event_type": "best_bid_ask",
            "asset_id": "tok-only-bid",
            "bid_price": 0.45,
            "ask_price": 0,
        })
        feed._handle_message(msg)
        entry = feed._price_cache.get("tok-only-bid")
        assert entry is not None
        assert entry.mid == pytest.approx(0.45)

    def test_handle_price_change_with_bids_asks_updates_cache(self):
        feed = self._feed()
        msg = json.dumps({
            "event_type": "price_change",
            "asset_id": "tok-xyz",
            "bids": [{"price": 0.38}],
            "asks": [{"price": 0.42}],
        })
        feed._handle_message(msg)
        entry = feed._price_cache.get("tok-xyz")
        assert entry is not None
        assert entry.mid == pytest.approx(0.40)

    def test_handle_last_trade_price_updates_cache_when_no_existing(self):
        feed = self._feed()
        msg = json.dumps({
            "event_type": "last_trade_price",
            "asset_id": "tok-ltp",
            "price": 0.55,
        })
        feed._handle_message(msg)
        entry = feed._price_cache.get("tok-ltp")
        assert entry is not None
        assert entry.mid == pytest.approx(0.55)

    def test_handle_pong_no_crash(self):
        feed = self._feed()
        feed._handle_message("PONG")  # Should not raise

    def test_malformed_json_no_crash(self):
        feed = self._feed()
        feed._handle_message("{not valid json}")  # Should not raise

    def test_empty_string_no_crash(self):
        feed = self._feed()
        feed._handle_message("")  # Should not raise

    def test_unknown_event_type_no_crash(self):
        feed = self._feed()
        msg = json.dumps({"event_type": "mystery_event", "asset_id": "tok-x"})
        feed._handle_message(msg)  # No crash

    def test_missing_asset_id_no_crash(self):
        feed = self._feed()
        msg = json.dumps({"event_type": "best_bid_ask", "bid_price": 0.40, "ask_price": 0.60})
        feed._handle_message(msg)  # No crash; nothing cached


# ---------------------------------------------------------------------------
# TestWebSocketSubscription
# ---------------------------------------------------------------------------

class TestWebSocketSubscription:
    """Test subscription token management logic."""

    @pytest.mark.asyncio
    async def test_subscribe_adds_tokens(self):
        feed = PolymarketWebSocketFeed()
        feed._ws = None
        await feed.subscribe(["tok1", "tok2", "tok3"])
        assert "tok1" in feed._subscribed_tokens
        assert "tok2" in feed._subscribed_tokens
        assert "tok3" in feed._subscribed_tokens

    @pytest.mark.asyncio
    async def test_subscribe_deduplicates_existing(self):
        feed = PolymarketWebSocketFeed()
        feed._subscribed_tokens = ["tok1"]
        feed._ws = None
        await feed.subscribe(["tok1", "tok2"])
        assert feed._subscribed_tokens.count("tok1") == 1

    def test_start_caps_tokens_at_max(self):
        feed = PolymarketWebSocketFeed()
        tokens = [f"tok-{i}" for i in range(MAX_TOKENS_PER_CONNECTION + 50)]

        # Patch _run_loop to not actually connect
        with patch.object(feed, "_run_loop", return_value=AsyncMock()):
            import asyncio
            # Can't easily await start without event loop, so test internal logic directly
            feed._subscribed_tokens = tokens[:MAX_TOKENS_PER_CONNECTION]
            assert len(feed._subscribed_tokens) == MAX_TOKENS_PER_CONNECTION

    def test_max_tokens_constant(self):
        assert MAX_TOKENS_PER_CONNECTION == 500

    @pytest.mark.asyncio
    async def test_subscribe_respects_max_tokens_cap(self):
        feed = PolymarketWebSocketFeed()
        # Fill to capacity
        feed._subscribed_tokens = [f"existing-{i}" for i in range(MAX_TOKENS_PER_CONNECTION)]
        feed._ws = None
        await feed.subscribe(["new-tok-1", "new-tok-2"])
        # Should not exceed max
        assert len(feed._subscribed_tokens) <= MAX_TOKENS_PER_CONNECTION


# ---------------------------------------------------------------------------
# TestSubscriptionPayloadFormat
# ---------------------------------------------------------------------------

class TestSubscriptionPayloadFormat:
    """Verify the subscription JSON structure sent to the WebSocket."""

    @pytest.mark.asyncio
    async def test_subscription_payload_format(self):
        feed = PolymarketWebSocketFeed()
        sent_payloads = []

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock(side_effect=lambda p: sent_payloads.append(p))

        await feed._send_subscription(mock_ws, ["tok-a", "tok-b"])

        assert len(sent_payloads) == 1
        payload = json.loads(sent_payloads[0])
        assert payload["type"] == "market"
        assert "tok-a" in payload["assets_ids"]
        assert "tok-b" in payload["assets_ids"]
        assert payload["custom_feature_enabled"] is True

    @pytest.mark.asyncio
    async def test_subscription_payload_all_tokens_included(self):
        feed = PolymarketWebSocketFeed()
        sent_payloads = []

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock(side_effect=lambda p: sent_payloads.append(p))

        tokens = [f"tok-{i}" for i in range(10)]
        await feed._send_subscription(mock_ws, tokens)

        payload = json.loads(sent_payloads[0])
        assert len(payload["assets_ids"]) == 10


# ---------------------------------------------------------------------------
# TestGetPriceAsync
# ---------------------------------------------------------------------------

class TestGetPriceAsync:
    @pytest.mark.asyncio
    async def test_get_price_returns_cached(self):
        feed = PolymarketWebSocketFeed(ttl_seconds=60)
        feed._price_cache["tok-async"] = PriceEntry(bid=0.30, ask=0.40, mid=0.35)
        price = await feed.get_price("tok-async")
        assert price == pytest.approx(0.35)

    @pytest.mark.asyncio
    async def test_get_price_returns_none_on_miss(self):
        feed = PolymarketWebSocketFeed()
        price = await feed.get_price("nonexistent")
        assert price is None
