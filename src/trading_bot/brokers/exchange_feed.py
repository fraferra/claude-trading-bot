"""Binance real-time price feed for temporal momentum arbitrage.

Maintains persistent WebSocket connections to Binance public market streams
(no API key required) and provides a rolling price history buffer plus
top-5 order book depth for front-running detection.

Streams used:
  <symbol>@aggTrade  — trade-by-trade price updates
  <symbol>@depth5    — top 5 bid/ask levels

Usage:
    feed = BinanceExchangeFeed(symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    await feed.start()
    history = feed.get_price_history("BTCUSDT", seconds=60)
    price = feed.get_current_price("BTCUSDT")
    bids, asks = feed.get_order_book("BTCUSDT")
    await feed.stop()
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from dataclasses import dataclass, field
from typing import NamedTuple

from trading_bot.utils.logging import log

BINANCE_WS_BASE = "wss://stream.binance.com:9443/stream"
HEARTBEAT_INTERVAL = 20    # seconds
RECONNECT_DELAY_BASE = 2.0  # doubles on retry, max 60s


@dataclass
class PricePoint:
    """A single price observation with a Unix timestamp."""
    price: float
    timestamp: float = field(default_factory=time.time)


class BookLevel(NamedTuple):
    """A single level in the order book."""
    price: float
    size: float   # in base asset (BTC, ETH, SOL)


class BinanceExchangeFeed:
    """Binance public WebSocket feed for spot price data.

    Thread-safe for read access (asyncio single-thread writes).
    All symbol keys are stored lower-case (e.g. "btcusdt").
    """

    def __init__(
        self,
        symbols: list[str],
        history_seconds: int = 360,
        ttl_seconds: int = 10,
    ) -> None:
        # Normalise to lower-case; used as dict keys and in WS stream names
        self.symbols = [s.lower() for s in symbols]
        self.history_seconds = history_seconds
        self.ttl_seconds = ttl_seconds

        # Rolling price history — max capacity = history_seconds * 10 ticks
        self._price_history: dict[str, deque[PricePoint]] = {
            s: deque(maxlen=history_seconds * 10) for s in self.symbols
        }
        self._last_price: dict[str, float] = {}
        self._last_price_time: dict[str, float] = {}

        # Order book — top 5 bids (desc) and asks (asc) per symbol
        self._bids: dict[str, list[BookLevel]] = {}
        self._asks: dict[str, list[BookLevel]] = {}

        self._task: asyncio.Task | None = None
        self._running = False
        self._reconnect_delay = RECONNECT_DELAY_BASE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the WebSocket feed in a background asyncio task."""
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="binance_exchange_feed")
        log.info(
            f"BinanceExchangeFeed: starting for {len(self.symbols)} symbols: {self.symbols}"
        )

    async def stop(self) -> None:
        """Stop the WebSocket feed gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("BinanceExchangeFeed: stopped")

    def get_current_price(self, symbol: str) -> float | None:
        """Return most recent trade price, or None if stale/missing."""
        sym = symbol.lower()
        t = self._last_price_time.get(sym, 0.0)
        if time.time() - t > self.ttl_seconds:
            return None
        return self._last_price.get(sym)

    def get_price_history(self, symbol: str, seconds: int) -> list[PricePoint]:
        """Return all price points recorded in the last `seconds`."""
        sym = symbol.lower()
        cutoff = time.time() - seconds
        buf = self._price_history.get(sym)
        if buf is None:
            return []
        return [p for p in buf if p.timestamp >= cutoff]

    def get_order_book(self, symbol: str) -> tuple[list[BookLevel], list[BookLevel]]:
        """Return (bids, asks) top-5 levels.  Empty lists if not yet received."""
        sym = symbol.lower()
        return self._bids.get(sym, []), self._asks.get(sym, [])

    def is_connected(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_ws_url(self) -> str:
        """Build the combined-stream URL for all symbols."""
        streams = []
        for sym in self.symbols:
            streams.append(f"{sym}@aggTrade")
            streams.append(f"{sym}@depth5")
        return f"{BINANCE_WS_BASE}?streams={'/'.join(streams)}"

    async def _run_loop(self) -> None:
        """Main connection loop with exponential-backoff reconnect."""
        while self._running:
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.warning(f"BinanceExchangeFeed: connection error: {e}")

            if not self._running:
                break

            log.info(f"BinanceExchangeFeed: reconnecting in {self._reconnect_delay:.1f}s")
            await asyncio.sleep(self._reconnect_delay)
            self._reconnect_delay = min(self._reconnect_delay * 2, 60.0)

    async def _connect_and_listen(self) -> None:
        """Establish connection and consume messages until disconnect."""
        try:
            import websockets
        except ImportError:
            log.error("BinanceExchangeFeed: websockets package not installed")
            return

        url = self._build_ws_url()
        log.debug(f"BinanceExchangeFeed: connecting to {url[:80]}…")

        async with websockets.connect(
            url,
            ping_interval=None,  # manual heartbeat below
            close_timeout=5,
        ) as ws:
            self._reconnect_delay = RECONNECT_DELAY_BASE  # reset on success
            log.info("BinanceExchangeFeed: connected")

            heartbeat_task = asyncio.create_task(self._heartbeat(ws))
            try:
                async for raw_msg in ws:
                    if not self._running:
                        break
                    try:
                        self._handle_message(raw_msg)
                    except Exception as e:
                        log.debug(f"BinanceExchangeFeed: parse error: {e}")
            finally:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

    async def _heartbeat(self, ws) -> None:
        """Binance combined streams stay alive without explicit pings,
        but we send a noop every HEARTBEAT_INTERVAL seconds to detect
        dead connections early."""
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            try:
                # Binance accepts pong frames to keep connection alive
                await ws.ping()
            except Exception:
                break

    def _handle_message(self, raw_msg: str) -> None:
        """Parse a combined-stream message and update internal caches."""
        try:
            outer = json.loads(raw_msg)
        except (json.JSONDecodeError, TypeError):
            return

        # Combined stream format: {"stream": "<sym>@<type>", "data": {...}}
        stream = outer.get("stream", "")
        data = outer.get("data", outer)  # fallback for single-stream frames

        if "@aggtrade" in stream.lower():
            self._handle_agg_trade(data)
        elif "@depth" in stream.lower():
            self._handle_depth(data, stream)

    def _handle_agg_trade(self, data: dict) -> None:
        """Process an aggTrade event: update price history and last price."""
        sym = data.get("s", "").lower()
        if sym not in self._price_history:
            return
        try:
            price = float(data["p"])
            ts = data.get("T", time.time() * 1000)
            point = PricePoint(price=price, timestamp=ts / 1000.0)
            self._price_history[sym].append(point)
            self._last_price[sym] = price
            self._last_price_time[sym] = point.timestamp
        except (KeyError, ValueError):
            pass

    def _handle_depth(self, data: dict, stream: str) -> None:
        """Process a depth5 event: update best 5 bid/ask levels."""
        # Extract symbol from stream name, e.g. "btcusdt@depth5"
        sym = stream.split("@")[0].lower()
        if sym not in self.symbols:
            return
        try:
            raw_bids = data.get("bids", [])
            raw_asks = data.get("asks", [])
            self._bids[sym] = [
                BookLevel(float(p), float(q)) for p, q in raw_bids
            ]
            self._asks[sym] = [
                BookLevel(float(p), float(q)) for p, q in raw_asks
            ]
        except (ValueError, TypeError):
            pass
