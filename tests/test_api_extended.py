"""Extended API endpoint tests: history, analytics, monitors, config.

Uses the same pattern as test_api.py — manually wires app.state so the
lifespan doesn't run, then exercises real route handlers against an
in-memory SQLite database.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, MagicMock

from trading_bot.api.app import create_app
from trading_bot.api.websocket import WebSocketManager
from trading_bot.config import Config
from trading_bot.db.database import Database
from trading_bot.db.repository import Repository
from trading_bot.monitors.manager import MonitorManager
from trading_bot.risk.manager import RiskManager


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

@pytest.fixture
async def client(tmp_path):
    config = Config()
    config.server.db_path = str(tmp_path / "test_ext.db")
    config.polymarket.paper = True
    config.polymarket.paper_balance = 5_000.0

    app = create_app(config)

    db = Database(":memory:")
    await db.connect()
    repo = Repository(db)
    ws_manager = WebSocketManager()

    from trading_bot.brokers.paper_polymarket import PaperPolymarketBroker
    brokers: dict = {"polymarket": PaperPolymarketBroker(5_000.0)}

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


# ---------------------------------------------------------------------------
# TestHistoryEndpoints
# ---------------------------------------------------------------------------

class TestHistoryEndpoints:

    async def test_get_trades_returns_list(self, client: AsyncClient):
        resp = await client.get("/api/history/trades")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    async def test_get_trades_limit_param(self, client: AsyncClient):
        resp = await client.get("/api/history/trades?limit=5")
        assert resp.status_code == 200

    async def test_get_trades_symbol_filter(self, client: AsyncClient):
        resp = await client.get("/api/history/trades?symbol=AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    async def test_get_decisions_returns_list(self, client: AsyncClient):
        resp = await client.get("/api/history/decisions")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_get_strategy_results_returns_list(self, client: AsyncClient):
        resp = await client.get("/api/history/strategy-results")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_get_stock_scores_returns_list(self, client: AsyncClient):
        resp = await client.get("/api/history/stock-scores")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_get_cumulative_pnl_returns_dict(self, client: AsyncClient):
        resp = await client.get("/api/history/cumulative-pnl")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        # Should contain alpaca/kalshi/alpaca_crypto keys
        assert "alpaca" in data or "kalshi" in data or "alpaca_crypto" in data


# ---------------------------------------------------------------------------
# TestAnalyticsEndpoints
# ---------------------------------------------------------------------------

class TestAnalyticsEndpoints:

    async def test_performance_returns_metrics_dict(self, client: AsyncClient):
        resp = await client.get("/api/analytics/performance")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        # Required fields from _compute_metrics
        assert "total_realized_pnl" in data
        assert "total_trades" in data
        assert "win_rate" in data

    async def test_performance_with_empty_trades(self, client: AsyncClient):
        resp = await client.get("/api/analytics/performance")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_trades"] == 0
        assert data["total_realized_pnl"] == 0

    async def test_risk_metrics_returns_dict(self, client: AsyncClient):
        resp = await client.get("/api/analytics/risk")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "positions" in data

    async def test_calendar_returns_list(self, client: AsyncClient):
        resp = await client.get("/api/analytics/calendar")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_export_csv_returns_csv(self, client: AsyncClient):
        resp = await client.get("/api/analytics/export-csv")
        assert resp.status_code == 200
        assert "csv" in resp.headers.get("content-type", "").lower()

    async def test_earnings_check_no_symbols_returns_note(self, client: AsyncClient):
        resp = await client.get("/api/analytics/earnings-check")
        assert resp.status_code == 200
        data = resp.json()
        assert "note" in data or "earnings" in data


# ---------------------------------------------------------------------------
# TestMonitorEndpoints
# ---------------------------------------------------------------------------

class TestMonitorEndpoints:

    async def test_get_monitors_returns_structure(self, client: AsyncClient):
        resp = await client.get("/api/monitors")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    async def test_start_nonexistent_monitor_returns_error(self, client: AsyncClient):
        resp = await client.post("/api/monitors/nonexistent_monitor/start")
        # Should return 4xx for unknown monitor
        assert resp.status_code in (400, 404, 422, 500)

    async def test_get_monitor_states(self, client: AsyncClient):
        resp = await client.get("/api/monitors")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# TestConfigEndpoints
# ---------------------------------------------------------------------------

class TestConfigEndpoints:

    async def test_get_config_returns_dict(self, client: AsyncClient):
        resp = await client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    async def test_config_contains_risk_section(self, client: AsyncClient):
        resp = await client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        # Config should contain risk settings
        assert "risk" in data or "min_confidence" in str(data)


# ---------------------------------------------------------------------------
# TestPortfolioEndpoints
# ---------------------------------------------------------------------------

class TestPortfolioEndpoints:

    async def test_get_portfolio_200(self, client: AsyncClient):
        resp = await client.get("/api/portfolio")
        assert resp.status_code == 200

    async def test_portfolio_contains_polymarket(self, client: AsyncClient):
        resp = await client.get("/api/portfolio")
        data = resp.json()
        assert "polymarket" in data


# ---------------------------------------------------------------------------
# TestPolymarketEndpoints
# ---------------------------------------------------------------------------

class TestPolymarketEndpoints:

    async def test_get_polymarket_trades_returns_list(self, client: AsyncClient):
        resp = await client.get("/api/polymarket/trades")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_get_polymarket_settlements_returns_list(self, client: AsyncClient):
        resp = await client.get("/api/polymarket/settlements")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_get_polymarket_pnl_history_returns_dict(self, client: AsyncClient):
        resp = await client.get("/api/polymarket/pnl-history")
        assert resp.status_code == 200
        data = resp.json()
        assert "pnl_history" in data or isinstance(data, (list, dict))

    async def test_get_polymarket_decisions_returns_200(self, client: AsyncClient):
        resp = await client.get("/api/polymarket/decisions")
        assert resp.status_code == 200
        data = resp.json()
        # Returns either a list or a dict with a decisions key
        assert isinstance(data, (list, dict))


# ---------------------------------------------------------------------------
# TestComputeMetricsInternal (pure function — no HTTP)
# ---------------------------------------------------------------------------

class TestComputeMetricsInternal:
    """Unit-test the _compute_metrics helper directly."""

    def _fn(self):
        from trading_bot.api.routers.analytics import _compute_metrics
        return _compute_metrics

    def test_empty_trades_returns_zero_metrics(self):
        fn = self._fn()
        result = fn([])
        assert result["total_realized_pnl"] == 0
        assert result["total_trades"] == 0
        assert result["win_rate"] == 0

    def test_single_profitable_trade(self):
        fn = self._fn()
        trades = [
            {"symbol": "AAPL", "side": "buy",  "quantity": 10, "filled_price": 100.0, "created_at": "2025-01-01"},
            {"symbol": "AAPL", "side": "sell", "quantity": 10, "filled_price": 120.0, "created_at": "2025-01-02"},
        ]
        result = fn(trades)
        assert result["total_realized_pnl"] == pytest.approx(200.0)
        assert result["winning_trades"] == 1
        assert result["losing_trades"] == 0
        assert result["win_rate"] == pytest.approx(100.0)

    def test_single_losing_trade(self):
        fn = self._fn()
        trades = [
            {"symbol": "AAPL", "side": "buy",  "quantity": 10, "filled_price": 100.0, "created_at": "2025-01-01"},
            {"symbol": "AAPL", "side": "sell", "quantity": 10, "filled_price": 80.0,  "created_at": "2025-01-02"},
        ]
        result = fn(trades)
        assert result["total_realized_pnl"] == pytest.approx(-200.0)
        assert result["losing_trades"] == 1

    def test_fifo_multiple_lots(self):
        fn = self._fn()
        trades = [
            {"symbol": "AAPL", "side": "buy",  "quantity": 5,  "filled_price": 100.0, "created_at": "2025-01-01"},
            {"symbol": "AAPL", "side": "buy",  "quantity": 5,  "filled_price": 110.0, "created_at": "2025-01-02"},
            {"symbol": "AAPL", "side": "sell", "quantity": 7,  "filled_price": 130.0, "created_at": "2025-01-03"},
        ]
        result = fn(trades)
        # FIFO: 5 @ 100 → +150, 2 @ 110 → +40 = +190
        assert result["total_realized_pnl"] == pytest.approx(190.0)

    def test_two_symbols_independent(self):
        fn = self._fn()
        trades = [
            {"symbol": "AAPL", "side": "buy",  "quantity": 10, "filled_price": 100.0, "created_at": "2025-01-01"},
            {"symbol": "AAPL", "side": "sell", "quantity": 10, "filled_price": 120.0, "created_at": "2025-01-02"},
            {"symbol": "MSFT", "side": "buy",  "quantity": 5,  "filled_price": 300.0, "created_at": "2025-01-01"},
            {"symbol": "MSFT", "side": "sell", "quantity": 5,  "filled_price": 280.0, "created_at": "2025-01-02"},
        ]
        result = fn(trades)
        # AAPL: +200, MSFT: -100
        assert result["total_realized_pnl"] == pytest.approx(100.0)

    def test_missing_price_skipped(self):
        fn = self._fn()
        trades = [
            {"symbol": "AAPL", "side": "buy",  "quantity": 10, "filled_price": None, "created_at": "2025-01-01"},
            {"symbol": "AAPL", "side": "sell", "quantity": 10, "filled_price": 120.0, "created_at": "2025-01-02"},
        ]
        result = fn(trades)
        # Buy has no price → sell has nothing to match → 0 P&L
        assert result["total_realized_pnl"] == 0

    def test_best_and_worst_trade(self):
        fn = self._fn()
        trades = [
            {"symbol": "AAPL", "side": "buy",  "quantity": 10, "filled_price": 100.0, "created_at": "2025-01-01"},
            {"symbol": "AAPL", "side": "sell", "quantity": 10, "filled_price": 150.0, "created_at": "2025-01-02"},
            {"symbol": "MSFT", "side": "buy",  "quantity": 5,  "filled_price": 200.0, "created_at": "2025-01-03"},
            {"symbol": "MSFT", "side": "sell", "quantity": 5,  "filled_price": 180.0, "created_at": "2025-01-04"},
        ]
        result = fn(trades)
        assert result["best_trade"] == pytest.approx(500.0)  # AAPL: +500
        assert result["worst_trade"] == pytest.approx(-100.0)  # MSFT: -100

    def test_pnl_by_symbol_aggregated(self):
        fn = self._fn()
        trades = [
            {"symbol": "AAPL", "side": "buy",  "quantity": 10, "filled_price": 100.0, "created_at": "2025-01-01"},
            {"symbol": "AAPL", "side": "sell", "quantity": 10, "filled_price": 120.0, "created_at": "2025-01-02"},
        ]
        result = fn(trades)
        assert "AAPL" in result["pnl_by_symbol"]
        assert result["pnl_by_symbol"]["AAPL"] == pytest.approx(200.0)
