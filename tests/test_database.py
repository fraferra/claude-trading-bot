"""Tests for the database layer."""

from __future__ import annotations

import pytest

from trading_bot.db.database import Database
from trading_bot.db.repository import Repository


@pytest.fixture
async def repo(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    repo = Repository(db)
    yield repo
    await db.close()


class TestTrades:
    async def test_insert_and_get_trade(self, repo: Repository):
        trade_id = await repo.insert_trade(
            order_id="ord_1", symbol="AAPL", side="buy", quantity=10.0,
            filled_price=185.50, platform="alpaca", source="cli",
        )
        assert trade_id > 0

        trades = await repo.get_trades(limit=10)
        assert len(trades) == 1
        assert trades[0]["symbol"] == "AAPL"
        assert trades[0]["filled_price"] == 185.50

    async def test_filter_by_symbol(self, repo: Repository):
        await repo.insert_trade("o1", "AAPL", "buy", 10, 185, "alpaca", "cli")
        await repo.insert_trade("o2", "MSFT", "buy", 5, 400, "alpaca", "cli")

        aapl_trades = await repo.get_trades(symbol="AAPL")
        assert len(aapl_trades) == 1
        assert aapl_trades[0]["symbol"] == "AAPL"

    async def test_filter_by_source(self, repo: Repository):
        await repo.insert_trade("o1", "AAPL", "buy", 10, 185, "alpaca", "cli")
        await repo.insert_trade("o2", "AAPL", "buy", 5, 190, "alpaca", "monitor:stock")

        monitor_trades = await repo.get_trades(source="monitor:stock")
        assert len(monitor_trades) == 1


class TestSnapshots:
    async def test_insert_and_get_snapshot(self, repo: Repository):
        await repo.insert_snapshot("alpaca", 5000.0, 10000.0, 100.0, "[]")
        snapshots = await repo.get_snapshots()
        assert len(snapshots) == 1
        assert snapshots[0]["equity"] == 10000.0

    async def test_filter_by_platform(self, repo: Repository):
        await repo.insert_snapshot("alpaca", 5000, 10000, 100, "[]")
        await repo.insert_snapshot("polymarket", 8000, 9000, -50, "[]")

        alpaca = await repo.get_snapshots(platform="alpaca")
        assert len(alpaca) == 1
        assert alpaca[0]["platform"] == "alpaca"


class TestMonitorState:
    async def test_upsert_and_get(self, repo: Repository):
        await repo.upsert_monitor_state("mon_1", "stock_watchlist", "running")
        state = await repo.get_monitor_state("mon_1")
        assert state is not None
        assert state["status"] == "running"
        assert state["monitor_type"] == "stock_watchlist"

    async def test_update_status(self, repo: Repository):
        await repo.upsert_monitor_state("mon_1", "arb", "running")
        await repo.update_monitor_status("mon_1", "paused")
        state = await repo.get_monitor_state("mon_1")
        assert state["status"] == "paused"

    async def test_adaptation_update(self, repo: Repository):
        await repo.upsert_monitor_state("mon_1", "arb", "running")
        await repo.update_monitor_adaptation("mon_1", 0.8, 0.05)
        state = await repo.get_monitor_state("mon_1")
        assert state["current_position_scale"] == 0.8
        assert state["current_min_edge"] == 0.05

    async def test_increment_trade_win(self, repo: Repository):
        await repo.upsert_monitor_state("mon_1", "arb", "running")
        await repo.increment_monitor_trade("mon_1", pnl=50.0)
        state = await repo.get_monitor_state("mon_1")
        assert state["total_trades"] == 1
        assert state["total_pnl"] == 50.0
        assert state["win_count"] == 1

    async def test_get_all_states(self, repo: Repository):
        await repo.upsert_monitor_state("mon_1", "arb", "running")
        await repo.upsert_monitor_state("mon_2", "stock", "stopped")
        states = await repo.get_all_monitor_states()
        assert len(states) == 2


class TestDecisions:
    async def test_insert_and_get(self, repo: Repository):
        dec_id = await repo.insert_decision(
            "AAPL", "buy", 0.85, "Strong momentum", "cli", "stock_scorer", True,
        )
        assert dec_id > 0
        decisions = await repo.get_decisions(limit=10)
        assert len(decisions) == 1
        assert decisions[0]["symbol"] == "AAPL"
        assert decisions[0]["was_executed"] == 1


class TestStockScores:
    async def test_insert_and_get(self, repo: Repository):
        score_id = await repo.insert_stock_score(
            "AAPL", 0.6, 0.4, 0.7, 0.55, "trending_up", '{"tech": 0.4}', "buy",
        )
        assert score_id > 0
        scores = await repo.get_stock_scores(symbol="AAPL")
        assert len(scores) == 1
        assert scores[0]["composite_score"] == 0.55
