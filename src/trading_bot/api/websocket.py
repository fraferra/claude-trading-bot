"""WebSocket manager for real-time event broadcasting."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

from fastapi import WebSocket

from trading_bot.monitors.base import EventBus
from trading_bot.models import WSEvent


class WebSocketManager(EventBus):
    """Manages WebSocket connections and broadcasts events."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.append(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            if ws in self._connections:
                self._connections.remove(ws)

    async def broadcast(self, event: WSEvent) -> None:
        payload = json.dumps({
            "type": event.type.value,
            "data": event.data,
            "timestamp": event.timestamp.isoformat(),
        })
        async with self._lock:
            dead: list[WebSocket] = []
            for ws in self._connections:
                try:
                    await ws.send_text(payload)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._connections.remove(ws)

    async def broadcast_json(self, data: dict) -> None:
        """Broadcast raw JSON dict (convenience method)."""
        event = WSEvent(
            type=data.get("type", "error"),
            data=data.get("data", {}),
            timestamp=datetime.now(),
        )
        await self.broadcast(event)

    @property
    def connection_count(self) -> int:
        return len(self._connections)
