"""Tests for the FastAPI backend."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from trading_bot.api.app import create_app
from trading_bot.api.websocket import WebSocketManager
from trading_bot.config import Config
from trading_bot.db.database import Database
from trading_bot.db.repository import Repository
from trading_bot.monitors.manager import MonitorManager
from trading_bot.risk.manager import RiskManager


@pytest.fixture
async def client(tmp_path):
    config = Config()
    config.server.db_path = str(tmp_path / "test.db")
    config.polymarket.paper = True
    config.polymarket.paper_balance = 10_000.0

    app = create_app(config)

    # Manually set up app state (lifespan doesn't run with httpx ASGITransport)
    db = Database(config.server.db_path)
    await db.connect()
    repo = Repository(db)
    ws_manager = WebSocketManager()

    from trading_bot.brokers.paper_polymarket import PaperPolymarketBroker
    brokers = {"polymarket": PaperPolymarketBroker(config.polymarket.paper_balance)}

    risk_manager = RiskManager(config.risk)
    monitor_manager = MonitorManager(config, repo, ws_manager, brokers, risk_manager)

    app.state.config = config
    app.state.db = db
    app.state.repo = repo
    app.state.ws_manager = ws_manager
    app.state.brokers = brokers
    app.state.risk_manager = risk_manager
    app.state.monitor_manager = monitor_manager

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    await monitor_manager.shutdown()
    await db.close()


class TestPortfolio:
    async def test_get_portfolio(self, client: AsyncClient):
        resp = await client.get("/api/portfolio")
        assert resp.status_code == 200
        data = resp.json()
        assert "polymarket" in data

    async def test_get_positions(self, client: AsyncClient):
        resp = await client.get("/api/positions")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_get_snapshots(self, client: AsyncClient):
        resp = await client.get("/api/snapshots")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestMonitors:
    async def test_list_monitors(self, client: AsyncClient):
        resp = await client.get("/api/monitors")
        assert resp.status_code == 200
        data = resp.json()
        assert "active" in data
        assert "all_states" in data

    async def test_start_invalid_type(self, client: AsyncClient):
        resp = await client.post("/api/monitors/invalid_type/start")
        assert resp.status_code == 400

    async def test_stop_nonexistent(self, client: AsyncClient):
        resp = await client.post("/api/monitors/nonexistent/stop")
        assert resp.status_code == 404


class TestHistory:
    async def test_get_trades(self, client: AsyncClient):
        resp = await client.get("/api/history/trades")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_get_decisions(self, client: AsyncClient):
        resp = await client.get("/api/history/decisions")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_get_strategy_results(self, client: AsyncClient):
        resp = await client.get("/api/history/strategy-results")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_get_stock_scores(self, client: AsyncClient):
        resp = await client.get("/api/history/stock-scores")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestConfig:
    async def test_get_config(self, client: AsyncClient):
        resp = await client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "risk" in data
        assert "stocks" in data
        assert "monitors" in data
        # Secrets should be masked or empty
        assert data.get("anthropic_api_key", "") in ("", "***")

    async def test_update_config(self, client: AsyncClient):
        resp = await client.put("/api/config", json={
            "risk": {"max_trades_per_day": 20},
            "stocks": {"watchlist": ["AAPL", "TSLA"]},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["risk"]["max_trades_per_day"] == 20
        assert data["stocks"]["watchlist"] == ["AAPL", "TSLA"]


class TestTradePreview:
    async def test_preview(self, client: AsyncClient):
        resp = await client.post("/api/trade/preview", json={
            "symbol": "some_market",
            "side": "buy",
            "quantity": 10.0,
            "platform": "polymarket",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "approved" in data
        assert "current_price" in data


class TestAnalysis:
    async def test_analyze_stock_no_api_key(self, client: AsyncClient):
        resp = await client.post("/api/analyze/stock", json={"symbol": "AAPL"})
        assert resp.status_code == 500

    async def test_analyze_stock_missing_symbol(self, client: AsyncClient):
        resp = await client.post("/api/analyze/stock", json={})
        assert resp.status_code == 400

    async def test_analyze_market_missing_id(self, client: AsyncClient):
        resp = await client.post("/api/analyze/market", json={})
        assert resp.status_code == 400

    async def test_analyze_probability_missing_id(self, client: AsyncClient):
        resp = await client.post("/api/analyze/probability", json={})
        assert resp.status_code == 400
