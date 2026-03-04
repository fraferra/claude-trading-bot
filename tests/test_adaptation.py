"""Tests for strategy adaptation logic."""

from __future__ import annotations

import pytest

from trading_bot.config import MonitorConfig
from trading_bot.db.database import Database
from trading_bot.db.repository import Repository
from trading_bot.monitors.adaptation import StrategyAdaptation


@pytest.fixture
async def setup(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    repo = Repository(db)
    config = MonitorConfig()
    adaptation = StrategyAdaptation(config, repo)

    # Create a monitor
    await repo.upsert_monitor_state("test_mon", "stock_watchlist", "running")

    yield adaptation, repo

    await db.close()


class TestAdaptation:
    async def test_not_enough_trades(self, setup):
        adaptation, repo = setup
        result = await adaptation.evaluate_and_adapt("test_mon")
        assert result["adapted"] is False
        assert result.get("reason") == "not_enough_trades"

    async def test_winning_increases_scale(self, setup):
        adaptation, repo = setup

        # Insert 6 winning trades with large enough PnL to exceed 5% threshold
        # entry_price=10, quantity=1 → cost per trade = 10, total_cost = 60
        # pnl=5 per trade → total_pnl=30, pnl_pct = 30/60 = 50% > 5%
        for i in range(6):
            tid = await repo.insert_trade(
                f"o{i}", "AAPL", "buy", 1, 10.0, "alpaca",
                "monitor:test_mon", status="filled",
            )
            await repo.insert_monitor_trade("test_mon", tid, 10.0, 1.0)
            await repo._db.db.execute(
                "UPDATE monitor_trades SET pnl = 5.0, is_closed = 1 WHERE trade_id = ?",
                (tid,),
            )
        await repo._db.db.commit()

        result = await adaptation.evaluate_and_adapt("test_mon")
        assert result["adapted"] is True
        assert result["pnl_pct"] > 0
        state = await repo.get_monitor_state("test_mon")
        assert state["current_position_scale"] > 1.0

    async def test_losing_decreases_scale(self, setup):
        adaptation, repo = setup

        # entry_price=10, quantity=1, pnl=-5 → pnl_pct = -30/60 = -50% < -5%
        for i in range(6):
            tid = await repo.insert_trade(
                f"o{i}", "AAPL", "buy", 1, 10.0, "alpaca",
                "monitor:test_mon", status="filled",
            )
            await repo.insert_monitor_trade("test_mon", tid, 10.0, 1.0)
            await repo._db.db.execute(
                "UPDATE monitor_trades SET pnl = -5.0, is_closed = 1 WHERE trade_id = ?",
                (tid,),
            )
        await repo._db.db.commit()

        result = await adaptation.evaluate_and_adapt("test_mon")
        assert result["adapted"] is True
        assert result["pnl_pct"] < 0
        state = await repo.get_monitor_state("test_mon")
        assert state["current_position_scale"] < 1.0

    async def test_adaptation_disabled(self, setup):
        adaptation, repo = setup
        adaptation.config.adaptation_enabled = False
        result = await adaptation.evaluate_and_adapt("test_mon")
        assert result["adapted"] is False

    async def test_low_win_rate_raises_edge(self, setup):
        adaptation, repo = setup

        # 1 win, 5 losses (win_rate ~17%)
        for i in range(6):
            tid = await repo.insert_trade(
                f"o{i}", "AAPL", "buy", 10, 100.0, "alpaca",
                "monitor:test_mon", status="filled",
            )
            await repo.insert_monitor_trade("test_mon", tid, 100.0, 10.0)
            pnl = 5.0 if i == 0 else -8.0
            await repo._db.db.execute(
                "UPDATE monitor_trades SET pnl = ?, is_closed = 1 WHERE trade_id = ?",
                (pnl, tid),
            )
        await repo._db.db.commit()

        result = await adaptation.evaluate_and_adapt("test_mon")
        state = await repo.get_monitor_state("test_mon")
        assert state["current_min_edge"] > 0
