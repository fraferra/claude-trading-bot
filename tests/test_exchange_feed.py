"""Tests for BinanceExchangeFeed."""

from __future__ import annotations

import time
from collections import deque

import pytest

from trading_bot.brokers.exchange_feed import (
    RECONNECT_DELAY_BASE,
    BinanceExchangeFeed,
    BookLevel,
    PricePoint,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_feed(symbols=None, history_seconds=60, ttl_seconds=5):
    symbols = symbols or ["BTCUSDT", "ETHUSDT"]
    return BinanceExchangeFeed(
        symbols=symbols,
        history_seconds=history_seconds,
        ttl_seconds=ttl_seconds,
    )


def _agg_trade(symbol: str, price: str, ts_ms: int) -> str:
    import json
    return json.dumps({
        "stream": f"{symbol.lower()}@aggtrade",
        "data": {
            "e": "aggTrade",
            "s": symbol.upper(),
            "p": price,
            "T": ts_ms,
        },
    })


def _depth5(symbol: str, bids: list, asks: list) -> str:
    import json
    return json.dumps({
        "stream": f"{symbol.lower()}@depth5",
        "data": {
            "bids": bids,
            "asks": asks,
        },
    })


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

class TestInit:
    def test_symbols_normalised_lower(self):
        feed = _make_feed(["BTCUSDT", "ETHUSDT"])
        assert "btcusdt" in feed.symbols
        assert "ethusdt" in feed.symbols

    def test_history_buffers_created(self):
        feed = _make_feed(["BTCUSDT"])
        assert "btcusdt" in feed._price_history
        assert isinstance(feed._price_history["btcusdt"], deque)

    def test_history_maxlen(self):
        feed = _make_feed(["BTCUSDT"], history_seconds=60)
        # maxlen should be history_seconds * 10
        assert feed._price_history["btcusdt"].maxlen == 600


# ---------------------------------------------------------------------------
# Message handling — aggTrade
# ---------------------------------------------------------------------------

class TestHandleAggTrade:
    def test_updates_price_history(self):
        feed = _make_feed(["BTCUSDT"])
        ts = int(time.time() * 1000)
        msg = _agg_trade("BTCUSDT", "70000.0", ts)
        feed._handle_message(msg)
        assert len(feed._price_history["btcusdt"]) == 1
        assert feed._price_history["btcusdt"][0].price == 70_000.0

    def test_updates_last_price(self):
        feed = _make_feed(["BTCUSDT"])
        ts = int(time.time() * 1000)
        feed._handle_message(_agg_trade("BTCUSDT", "70500.0", ts))
        assert feed._last_price.get("btcusdt") == pytest.approx(70_500.0)

    def test_unknown_symbol_ignored(self):
        feed = _make_feed(["BTCUSDT"])
        ts = int(time.time() * 1000)
        feed._handle_message(_agg_trade("XYZUSDT", "1.0", ts))
        assert len(feed._price_history.get("xyzusdt", [])) == 0

    def test_multiple_ticks_accumulate(self):
        feed = _make_feed(["BTCUSDT"])
        now_ms = int(time.time() * 1000)
        for i in range(5):
            feed._handle_message(_agg_trade("BTCUSDT", str(70_000 + i * 100), now_ms + i * 1000))
        assert len(feed._price_history["btcusdt"]) == 5
        assert feed._last_price["btcusdt"] == pytest.approx(70_400.0)

    def test_deque_trims_old_entries(self):
        feed = _make_feed(["BTCUSDT"], history_seconds=1)  # maxlen = 10
        now_ms = int(time.time() * 1000)
        for i in range(20):
            feed._handle_message(_agg_trade("BTCUSDT", str(70_000 + i), now_ms + i * 100))
        assert len(feed._price_history["btcusdt"]) <= 10

    def test_invalid_json_ignored(self):
        feed = _make_feed(["BTCUSDT"])
        feed._handle_message("not json{{{")  # should not raise
        assert len(feed._price_history["btcusdt"]) == 0


# ---------------------------------------------------------------------------
# Message handling — depth5
# ---------------------------------------------------------------------------

class TestHandleDepth:
    def test_updates_order_book(self):
        feed = _make_feed(["BTCUSDT"])
        msg = _depth5("BTCUSDT", [["69900.0", "1.5"], ["69800.0", "2.0"]], [["70000.0", "1.0"]])
        feed._handle_message(msg)
        bids, asks = feed.get_order_book("BTCUSDT")
        assert len(bids) == 2
        assert bids[0] == BookLevel(69_900.0, 1.5)
        assert asks[0] == BookLevel(70_000.0, 1.0)

    def test_unknown_symbol_no_crash(self):
        feed = _make_feed(["BTCUSDT"])
        msg = _depth5("XYZUSDT", [["1.0", "100"]], [["1.01", "100"]])
        feed._handle_message(msg)  # should not crash

    def test_empty_book(self):
        feed = _make_feed(["BTCUSDT"])
        msg = _depth5("BTCUSDT", [], [])
        feed._handle_message(msg)
        bids, asks = feed.get_order_book("BTCUSDT")
        assert bids == []
        assert asks == []


# ---------------------------------------------------------------------------
# get_current_price
# ---------------------------------------------------------------------------

class TestGetCurrentPrice:
    def test_returns_price_within_ttl(self):
        feed = _make_feed(["BTCUSDT"], ttl_seconds=10)
        ts = int(time.time() * 1000)
        feed._handle_message(_agg_trade("BTCUSDT", "70000.0", ts))
        assert feed.get_current_price("BTCUSDT") == pytest.approx(70_000.0)

    def test_returns_none_when_stale(self):
        feed = _make_feed(["BTCUSDT"], ttl_seconds=1)
        old_ts = int((time.time() - 10) * 1000)  # 10 seconds ago
        feed._last_price["btcusdt"] = 70_000.0
        feed._last_price_time["btcusdt"] = time.time() - 10  # 10s ago, TTL=1s → stale
        assert feed.get_current_price("BTCUSDT") is None

    def test_case_insensitive(self):
        feed = _make_feed(["BTCUSDT"], ttl_seconds=60)
        ts = int(time.time() * 1000)
        feed._handle_message(_agg_trade("BTCUSDT", "70000.0", ts))
        assert feed.get_current_price("btcusdt") == pytest.approx(70_000.0)
        assert feed.get_current_price("BTCUSDT") == pytest.approx(70_000.0)


# ---------------------------------------------------------------------------
# get_price_history
# ---------------------------------------------------------------------------

class TestGetPriceHistory:
    def test_filters_by_seconds(self):
        feed = _make_feed(["BTCUSDT"], ttl_seconds=60)
        now = time.time()
        # 5 old points (> 30s ago)
        for i in range(5):
            feed._price_history["btcusdt"].append(PricePoint(100.0, now - 60 + i))
        # 3 recent points (< 30s ago)
        for i in range(3):
            feed._price_history["btcusdt"].append(PricePoint(101.0, now - 10 + i))

        result = feed.get_price_history("BTCUSDT", seconds=30)
        assert len(result) == 3
        assert all(p.price == 101.0 for p in result)

    def test_empty_symbol(self):
        feed = _make_feed(["BTCUSDT"])
        result = feed.get_price_history("XYZUSDT", seconds=60)
        assert result == []

    def test_all_recent(self):
        feed = _make_feed(["BTCUSDT"])
        now = time.time()
        for i in range(5):
            feed._price_history["btcusdt"].append(PricePoint(100.0, now - i))
        result = feed.get_price_history("BTCUSDT", seconds=60)
        assert len(result) == 5


# ---------------------------------------------------------------------------
# WS URL construction
# ---------------------------------------------------------------------------

class TestBuildWsUrl:
    def test_contains_all_streams(self):
        feed = _make_feed(["BTCUSDT", "ETHUSDT", "SOLUSDT"])
        url = feed._build_ws_url()
        assert "btcusdt@aggTrade" in url
        assert "ethusdt@aggTrade" in url
        assert "solusdt@aggTrade" in url
        assert "btcusdt@depth5" in url
        assert "stream?" in url

    def test_single_symbol(self):
        feed = _make_feed(["BTCUSDT"])
        url = feed._build_ws_url()
        assert "btcusdt@aggTrade" in url
        assert "btcusdt@depth5" in url
