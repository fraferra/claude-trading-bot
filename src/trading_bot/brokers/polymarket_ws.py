"""Polymarket WebSocket price feed.

Maintains a persistent connection to the Polymarket CLOB WebSocket market channel
and caches the latest best-bid/ask midpoint for subscribed token IDs.

This reduces arb detection latency from 5-minute polling to sub-second.

Usage:
    feed = PolymarketWebSocketFeed(ttl_seconds=5)
    await feed.start(token_ids=["tok1", "tok2", ...])
    price = await feed.get_price("tok1")  # returns cached midpoint or None
    await feed.stop()
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field

from trading_bot.utils.logging import log

WS_MARKET_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
HEARTBEAT_INTERVAL = 10  # seconds
MAX_TOKENS_PER_CONNECTION = 500
RECONNECT_DELAY_BASE = 2.0  # seconds, doubles on each retry up to 60s


@dataclass
class PriceEntry:
    bid: float
    ask: float
    mid: float
    timestamp: float = field(default_factory=time.time)


class PolymarketWebSocketFeed:
    """Live order book price feed via Polymarket WebSocket.

    Thread-safe for read access. Write access is single-threaded (asyncio loop).
    """

    def __init__(self, ttl_seconds: int = 5) -> None:
        self.ttl_seconds = ttl_seconds
        self._price_cache: dict[str, PriceEntry] = {}
        self._subscribed_tokens: list[str] = []
        self._task: asyncio.Task | None = None
        self._ws = None
        self._running = False
        self._reconnect_delay = RECONNECT_DELAY_BASE

    async def start(self, token_ids: list[str]) -> None:
        """Start the WebSocket feed subscribing to given token IDs."""
        self._subscribed_tokens = list(token_ids[:MAX_TOKENS_PER_CONNECTION])
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="polymarket_ws_feed")
        log.info(
            f"PolymarketWebSocketFeed: starting for {len(self._subscribed_tokens)} tokens"
        )

    async def stop(self) -> None:
        """Stop the WebSocket feed."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("PolymarketWebSocketFeed: stopped")

    async def subscribe(self, token_ids: list[str]) -> None:
        """Add more token IDs to the subscription."""
        new_tokens = [t for t in token_ids if t not in self._subscribed_tokens]
        if not new_tokens:
            return
        space = MAX_TOKENS_PER_CONNECTION - len(self._subscribed_tokens)
        self._subscribed_tokens.extend(new_tokens[:space])
        if self._ws and not self._ws.closed:
            await self._send_subscription(self._ws, new_tokens[:space])

    def get_price_sync(self, token_id: str) -> float | None:
        """Get cached midpoint price synchronously (returns None if stale or missing)."""
        entry = self._price_cache.get(token_id)
        if entry and (time.time() - entry.timestamp) < self.ttl_seconds:
            return entry.mid
        return None

    async def get_price(self, token_id: str) -> float | None:
        """Get cached midpoint price (async wrapper)."""
        return self.get_price_sync(token_id)

    def is_connected(self) -> bool:
        return self._ws is not None and not getattr(self._ws, "closed", True)

    async def _run_loop(self) -> None:
        """Main connection loop with auto-reconnect."""
        while self._running:
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.warning(f"PolymarketWebSocketFeed: connection error: {e}")

            if not self._running:
                break

            log.info(
                f"PolymarketWebSocketFeed: reconnecting in {self._reconnect_delay:.1f}s"
            )
            await asyncio.sleep(self._reconnect_delay)
            self._reconnect_delay = min(self._reconnect_delay * 2, 60.0)

    async def _connect_and_listen(self) -> None:
        """Establish connection, subscribe, and listen for messages."""
        try:
            import websockets
        except ImportError:
            log.error("PolymarketWebSocketFeed: websockets package not installed")
            return

        async with websockets.connect(
            WS_MARKET_URL,
            ping_interval=None,  # We handle heartbeat manually
            close_timeout=5,
        ) as ws:
            self._ws = ws
            self._reconnect_delay = RECONNECT_DELAY_BASE  # reset on success
            log.info("PolymarketWebSocketFeed: connected")

            # Subscribe to all tokens
            if self._subscribed_tokens:
                await self._send_subscription(ws, self._subscribed_tokens)

            # Start heartbeat task
            heartbeat_task = asyncio.create_task(self._heartbeat(ws))

            try:
                async for raw_msg in ws:
                    if not self._running:
                        break
                    try:
                        self._handle_message(raw_msg)
                    except Exception as e:
                        log.debug(f"PolymarketWebSocketFeed: parse error: {e}")
            finally:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

        self._ws = None

    async def _send_subscription(self, ws, token_ids: list[str]) -> None:
        """Send subscription payload for given token IDs."""
        payload = json.dumps({
            "type": "market",
            "assets_ids": token_ids,
            "custom_feature_enabled": True,
        })
        await ws.send(payload)
        log.debug(f"PolymarketWebSocketFeed: subscribed to {len(token_ids)} tokens")

    async def _heartbeat(self, ws) -> None:
        """Send PING every HEARTBEAT_INTERVAL seconds to keep connection alive."""
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            try:
                await ws.send("PING")
            except Exception:
                break

    def _handle_message(self, raw_msg: str) -> None:
        """Parse incoming WebSocket messages and update price cache."""
        if raw_msg == "PONG":
            return

        try:
            msg = json.loads(raw_msg)
        except (json.JSONDecodeError, TypeError):
            return

        event_type = msg.get("event_type", msg.get("type", ""))

        if event_type == "best_bid_ask":
            token_id = msg.get("asset_id", "")
            bid = float(msg.get("bid_price", 0) or 0)
            ask = float(msg.get("ask_price", 0) or 0)
            if token_id and (bid > 0 or ask > 0):
                mid = (bid + ask) / 2 if (bid > 0 and ask > 0) else (bid or ask)
                self._price_cache[token_id] = PriceEntry(bid=bid, ask=ask, mid=mid)

        elif event_type in ("price_change", "book"):
            # Update from full order book or price change event
            token_id = msg.get("asset_id", "")
            if not token_id:
                return
            # Extract best bid/ask from the book if available
            bids = msg.get("bids", [])
            asks = msg.get("asks", [])
            if bids and asks:
                best_bid = float(bids[0].get("price", 0) if isinstance(bids[0], dict) else bids[0])
                best_ask = float(asks[0].get("price", 0) if isinstance(asks[0], dict) else asks[0])
                if best_bid > 0 and best_ask > 0:
                    mid = (best_bid + best_ask) / 2
                    self._price_cache[token_id] = PriceEntry(
                        bid=best_bid, ask=best_ask, mid=mid
                    )

        elif event_type == "last_trade_price":
            # Update last traded price as a proxy when no book data
            token_id = msg.get("asset_id", "")
            price = float(msg.get("price", 0) or 0)
            if token_id and price > 0:
                existing = self._price_cache.get(token_id)
                if not existing or (time.time() - existing.timestamp) > self.ttl_seconds:
                    self._price_cache[token_id] = PriceEntry(bid=price, ask=price, mid=price)
