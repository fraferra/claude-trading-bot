"""FastAPI application factory with lifespan management."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from trading_bot.api.websocket import WebSocketManager
from trading_bot.config import Config, load_config
from trading_bot.db.database import Database
from trading_bot.db.repository import Repository
from trading_bot.monitors.manager import MonitorManager
from trading_bot.risk.manager import RiskManager
from trading_bot.utils.logging import log


def _build_brokers(config: Config) -> dict:
    brokers: dict = {}
    if config.alpaca.api_key:
        from trading_bot.brokers.alpaca_broker import AlpacaBroker
        brokers["alpaca"] = AlpacaBroker(config.alpaca)

    if config.polymarket.paper:
        from trading_bot.brokers.paper_polymarket import PaperPolymarketBroker
        brokers["polymarket"] = PaperPolymarketBroker(config.polymarket.paper_balance)
    elif config.polymarket.private_key:
        from trading_bot.brokers.polymarket_broker import PolymarketBroker
        brokers["polymarket"] = PolymarketBroker(config.polymarket)

    if config.kalshi.api_key_id and config.kalshi.private_key:
        from trading_bot.brokers.kalshi_broker import KalshiBroker
        brokers["kalshi"] = KalshiBroker(config.kalshi)

    return brokers


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup/shutdown of database, monitors, WebSocket."""
    config: Config = app.state.config

    # Database
    db = Database(config.server.db_path)
    await db.connect()
    repo = Repository(db)
    app.state.db = db
    app.state.repo = repo

    # WebSocket manager
    ws_manager = WebSocketManager()
    app.state.ws_manager = ws_manager

    # Brokers & risk
    brokers = _build_brokers(config)
    app.state.brokers = brokers
    app.state.risk_manager = RiskManager(config.risk)

    # Monitor manager
    monitor_manager = MonitorManager(config, repo, ws_manager, brokers, app.state.risk_manager)
    app.state.monitor_manager = monitor_manager
    await monitor_manager.restore_from_db()

    log.info("API started")
    yield

    # Shutdown
    await monitor_manager.shutdown()
    await db.close()
    log.info("API stopped")


def create_app(config: Config | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    if config is None:
        config = load_config()

    app = FastAPI(
        title="Claude Trading Bot",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.state.config = config

    # Basic Auth (only active when AUTH_USERNAME + AUTH_PASSWORD are set)
    if config.auth.username and config.auth.password:
        from trading_bot.api.middleware import BasicAuthMiddleware
        app.add_middleware(BasicAuthMiddleware, username=config.auth.username, password=config.auth.password)

    # CORS for frontend dev server
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    from trading_bot.api.routers import (
        analysis,
        config as config_router,
        history,
        market_data,
        monitors,
        portfolio,
        strategies,
        trade,
    )

    from trading_bot.api.routers import analytics, backtest, crypto, kalshi, research_agent, shorts
    from trading_bot.api.routers import polymarket

    app.include_router(portfolio.router, prefix="/api", tags=["portfolio"])
    app.include_router(analysis.router, prefix="/api", tags=["analysis"])
    app.include_router(trade.router, prefix="/api", tags=["trade"])
    app.include_router(strategies.router, prefix="/api", tags=["strategies"])
    app.include_router(monitors.router, prefix="/api", tags=["monitors"])
    app.include_router(market_data.router, prefix="/api", tags=["market_data"])
    app.include_router(history.router, prefix="/api", tags=["history"])
    app.include_router(config_router.router, prefix="/api", tags=["config"])
    app.include_router(research_agent.router, prefix="/api", tags=["research_agent"])
    app.include_router(kalshi.router, prefix="/api", tags=["kalshi"])
    app.include_router(crypto.router, prefix="/api", tags=["crypto"])
    app.include_router(shorts.router, prefix="/api", tags=["shorts"])
    app.include_router(analytics.router, prefix="/api", tags=["analytics"])
    app.include_router(backtest.router, prefix="/api", tags=["backtest"])
    app.include_router(polymarket.router, prefix="/api", tags=["polymarket"])

    # WebSocket endpoint
    from trading_bot.api.routers.ws import router as ws_router
    app.include_router(ws_router, prefix="/api", tags=["websocket"])

    # Serve frontend static files in production
    static_dir = Path(config.server.static_dir)
    if static_dir.exists():
        # Serve static assets (JS, CSS, images)
        app.mount("/assets", StaticFiles(directory=str(static_dir / "assets")), name="static-assets")

        # SPA catch-all: serve index.html for any non-API route
        index_html = static_dir / "index.html"

        @app.get("/{path:path}", include_in_schema=False)
        async def spa_fallback(request: Request, path: str):
            # Serve actual static files if they exist
            file_path = static_dir / path
            if path and file_path.is_file():
                return FileResponse(file_path)
            return FileResponse(index_html)

    return app
