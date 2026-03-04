"""WebSocket endpoint for real-time events."""

from __future__ import annotations

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from trading_bot.api.deps import get_ws_manager
from trading_bot.api.websocket import WebSocketManager

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    manager: WebSocketManager = ws.app.state.ws_manager
    await manager.connect(ws)
    try:
        while True:
            # Keep connection alive; client can send pings
            await ws.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(ws)
