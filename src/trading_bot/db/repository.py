"""CRUD operations for the trading bot database."""

from __future__ import annotations

import json
from datetime import datetime

from trading_bot.db.database import Database


class Repository:
    """Data access layer for all database operations."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # --- Trades ---

    async def insert_trade(
        self,
        order_id: str,
        symbol: str,
        side: str,
        quantity: float,
        filled_price: float | None,
        platform: str,
        source: str,
        strategy_name: str | None = None,
        reasoning: str | None = None,
        confidence: float | None = None,
        status: str = "filled",
    ) -> int:
        cursor = await self._db.db.execute(
            """INSERT INTO trades (order_id, symbol, side, quantity, filled_price,
               platform, source, strategy_name, reasoning, confidence, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (order_id, symbol, side, quantity, filled_price, platform, source,
             strategy_name, reasoning, confidence, status),
        )
        await self._db.db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_trades(
        self, limit: int = 100, symbol: str | None = None, source: str | None = None,
        platform: str | None = None,
    ) -> list[dict]:
        query = "SELECT * FROM trades WHERE 1=1"
        params: list = []
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        if source:
            query += " AND source = ?"
            params.append(source)
        if platform:
            query += " AND platform = ?"
            params.append(platform)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cursor = await self._db.db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_trades_missing_price(self) -> list[dict]:
        """Get trades with NULL filled_price (for backfill)."""
        cursor = await self._db.db.execute(
            "SELECT * FROM trades WHERE filled_price IS NULL AND order_id IS NOT NULL"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def update_trade_price(self, trade_id: int, filled_price: float) -> None:
        """Update a trade's filled price."""
        await self._db.db.execute(
            "UPDATE trades SET filled_price = ? WHERE id = ?",
            (filled_price, trade_id),
        )
        await self._db.db.commit()

    # --- Portfolio Snapshots ---

    async def insert_snapshot(
        self, platform: str, cash: float, equity: float, daily_pnl: float, positions_json: str
    ) -> None:
        await self._db.db.execute(
            """INSERT INTO portfolio_snapshots (platform, cash, equity, daily_pnl, positions_json)
               VALUES (?, ?, ?, ?, ?)""",
            (platform, cash, equity, daily_pnl, positions_json),
        )
        await self._db.db.commit()

    async def get_snapshots(self, platform: str | None = None, limit: int = 500) -> list[dict]:
        query = "SELECT * FROM portfolio_snapshots"
        params: list = []
        if platform:
            query += " WHERE platform = ?"
            params.append(platform)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cursor = await self._db.db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # --- Strategy Results ---

    async def insert_strategy_result(
        self, strategy_name: str, decisions_json: str, metadata_json: str, source: str = "manual"
    ) -> int:
        cursor = await self._db.db.execute(
            """INSERT INTO strategy_results (strategy_name, decisions_json, metadata_json, source)
               VALUES (?, ?, ?, ?)""",
            (strategy_name, decisions_json, metadata_json, source),
        )
        await self._db.db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_strategy_results(
        self, strategy_name: str | None = None, limit: int = 50
    ) -> list[dict]:
        query = "SELECT * FROM strategy_results"
        params: list = []
        if strategy_name:
            query += " WHERE strategy_name = ?"
            params.append(strategy_name)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cursor = await self._db.db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # --- Monitor State ---

    async def upsert_monitor_state(
        self, monitor_id: str, monitor_type: str, status: str, config_json: str = "{}"
    ) -> None:
        await self._db.db.execute(
            """INSERT INTO monitor_state (monitor_id, monitor_type, status, config_json, updated_at)
               VALUES (?, ?, ?, ?, datetime('now'))
               ON CONFLICT(monitor_id) DO UPDATE SET
                   status = excluded.status,
                   config_json = excluded.config_json,
                   updated_at = datetime('now')""",
            (monitor_id, monitor_type, status, config_json),
        )
        await self._db.db.commit()

    async def get_monitor_state(self, monitor_id: str) -> dict | None:
        cursor = await self._db.db.execute(
            "SELECT * FROM monitor_state WHERE monitor_id = ?", (monitor_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_all_monitor_states(self) -> list[dict]:
        cursor = await self._db.db.execute("SELECT * FROM monitor_state ORDER BY monitor_id")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def update_monitor_status(self, monitor_id: str, status: str) -> None:
        await self._db.db.execute(
            "UPDATE monitor_state SET status = ?, updated_at = datetime('now') WHERE monitor_id = ?",
            (status, monitor_id),
        )
        await self._db.db.commit()

    async def update_monitor_last_run(self, monitor_id: str) -> None:
        await self._db.db.execute(
            "UPDATE monitor_state SET last_run = datetime('now'), updated_at = datetime('now') WHERE monitor_id = ?",
            (monitor_id,),
        )
        await self._db.db.commit()

    async def update_monitor_error(self, monitor_id: str, error: str) -> None:
        await self._db.db.execute(
            "UPDATE monitor_state SET status = 'error', error_message = ?, updated_at = datetime('now') WHERE monitor_id = ?",
            (error, monitor_id),
        )
        await self._db.db.commit()

    async def update_monitor_adaptation(
        self, monitor_id: str, position_scale: float, min_edge: float
    ) -> None:
        await self._db.db.execute(
            """UPDATE monitor_state
               SET current_position_scale = ?, current_min_edge = ?, updated_at = datetime('now')
               WHERE monitor_id = ?""",
            (position_scale, min_edge, monitor_id),
        )
        await self._db.db.commit()

    async def increment_monitor_trade(
        self, monitor_id: str, pnl: float | None = None
    ) -> None:
        win_clause = ", win_count = win_count + 1" if pnl and pnl > 0 else ""
        loss_clause = ", loss_count = loss_count + 1" if pnl and pnl < 0 else ""
        pnl_val = pnl or 0.0
        await self._db.db.execute(
            f"""UPDATE monitor_state
                SET total_trades = total_trades + 1,
                    total_pnl = total_pnl + ?{win_clause}{loss_clause},
                    updated_at = datetime('now')
                WHERE monitor_id = ?""",
            (pnl_val, monitor_id),
        )
        await self._db.db.commit()

    # --- Monitor Trades ---

    async def insert_monitor_trade(
        self, monitor_id: str, trade_id: int, entry_price: float, quantity: float = 1.0
    ) -> int:
        cursor = await self._db.db.execute(
            """INSERT INTO monitor_trades (monitor_id, trade_id, entry_price, quantity)
               VALUES (?, ?, ?, ?)""",
            (monitor_id, trade_id, entry_price, quantity),
        )
        await self._db.db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_recent_monitor_trades(
        self, monitor_id: str, limit: int = 20
    ) -> list[dict]:
        cursor = await self._db.db.execute(
            """SELECT mt.*, t.symbol, t.side, t.quantity as trade_quantity
               FROM monitor_trades mt
               JOIN trades t ON mt.trade_id = t.id
               WHERE mt.monitor_id = ?
               ORDER BY mt.created_at DESC LIMIT ?""",
            (monitor_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # --- Decisions ---

    async def insert_decision(
        self,
        symbol: str,
        action: str,
        confidence: float,
        reasoning: str | None,
        source: str,
        strategy_name: str | None = None,
        was_executed: bool = False,
    ) -> int:
        cursor = await self._db.db.execute(
            """INSERT INTO decisions (symbol, action, confidence, reasoning, source, strategy_name, was_executed)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (symbol, action, confidence, reasoning, source, strategy_name, int(was_executed)),
        )
        await self._db.db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_decisions(self, limit: int = 100) -> list[dict]:
        cursor = await self._db.db.execute(
            "SELECT * FROM decisions ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # --- Stock Scores ---

    async def insert_stock_score(
        self,
        symbol: str,
        technical_score: float,
        fundamental_score: float,
        sentiment_score: float,
        composite_score: float,
        regime: str,
        signal_weights_json: str,
        suggested_action: str,
    ) -> int:
        cursor = await self._db.db.execute(
            """INSERT INTO stock_scores (symbol, technical_score, fundamental_score,
               sentiment_score, composite_score, regime, signal_weights_json, suggested_action)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (symbol, technical_score, fundamental_score, sentiment_score,
             composite_score, regime, signal_weights_json, suggested_action),
        )
        await self._db.db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_stock_scores(
        self, symbol: str | None = None, limit: int = 50
    ) -> list[dict]:
        query = "SELECT * FROM stock_scores"
        params: list = []
        if symbol:
            query += " WHERE symbol = ?"
            params.append(symbol)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cursor = await self._db.db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # --- Research Reports ---

    async def insert_research_report(
        self,
        symbol: str,
        company_name: str,
        sector: str,
        composite_score: float,
        dimension_scores_json: str,
        recommendation: str,
        target_weight: float,
        catalysts_json: str = "[]",
        risks_json: str = "[]",
    ) -> int:
        cursor = await self._db.db.execute(
            """INSERT INTO research_reports (symbol, company_name, sector, composite_score,
               dimension_scores_json, recommendation, target_weight, catalysts_json, risks_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (symbol, company_name, sector, composite_score,
             dimension_scores_json, recommendation, target_weight, catalysts_json, risks_json),
        )
        await self._db.db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_research_reports(
        self, symbol: str | None = None, limit: int = 50
    ) -> list[dict]:
        query = "SELECT * FROM research_reports"
        params: list = []
        if symbol:
            query += " WHERE symbol = ?"
            params.append(symbol)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cursor = await self._db.db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # --- Portfolio Allocations ---

    async def insert_portfolio_allocation(
        self,
        entries_json: str,
        cash_reserve: float,
        rebalance_needed: bool,
        reasoning: str = "",
    ) -> int:
        cursor = await self._db.db.execute(
            """INSERT INTO portfolio_allocations (entries_json, cash_reserve, rebalance_needed, reasoning)
               VALUES (?, ?, ?, ?)""",
            (entries_json, cash_reserve, int(rebalance_needed), reasoning),
        )
        await self._db.db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_portfolio_allocations(self, limit: int = 20) -> list[dict]:
        cursor = await self._db.db.execute(
            "SELECT * FROM portfolio_allocations ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # --- Strategy Memos ---

    async def insert_strategy_memo(
        self,
        period_start: str,
        period_end: str,
        total_return_pct: float,
        win_rate: float,
        lessons_json: str = "[]",
        parameter_changes_json: str = "{}",
        next_week_focus_json: str = "[]",
    ) -> int:
        cursor = await self._db.db.execute(
            """INSERT INTO strategy_memos (period_start, period_end, total_return_pct,
               win_rate, lessons_json, parameter_changes_json, next_week_focus_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (period_start, period_end, total_return_pct, win_rate,
             lessons_json, parameter_changes_json, next_week_focus_json),
        )
        await self._db.db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_strategy_memos(self, limit: int = 20) -> list[dict]:
        cursor = await self._db.db.execute(
            "SELECT * FROM strategy_memos ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # --- Discovery Runs ---

    async def insert_discovery_run(
        self,
        candidates_json: str,
        source_queries_json: str,
        num_candidates: int,
    ) -> int:
        cursor = await self._db.db.execute(
            """INSERT INTO discovery_runs (candidates_json, source_queries_json, num_candidates)
               VALUES (?, ?, ?)""",
            (candidates_json, source_queries_json, num_candidates),
        )
        await self._db.db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_discovery_runs(self, limit: int = 20) -> list[dict]:
        cursor = await self._db.db.execute(
            "SELECT * FROM discovery_runs ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # --- Kalshi Estimates ---

    async def insert_kalshi_estimate(
        self,
        ticker: str,
        title: str,
        market_price: float,
        ai_probability: float,
        edge_pct: float,
        kelly_fraction: float = 0.0,
        suggested_side: str | None = None,
        reasoning: str = "",
        category: str = "",
    ) -> int:
        cursor = await self._db.db.execute(
            """INSERT INTO kalshi_estimates (ticker, title, market_price, ai_probability,
               edge_pct, kelly_fraction, suggested_side, reasoning, category)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ticker, title, market_price, ai_probability, edge_pct,
             kelly_fraction, suggested_side, reasoning, category),
        )
        await self._db.db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_kalshi_estimates(
        self, ticker: str | None = None, limit: int = 50
    ) -> list[dict]:
        query = "SELECT * FROM kalshi_estimates"
        params: list = []
        if ticker:
            query += " WHERE ticker = ?"
            params.append(ticker)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cursor = await self._db.db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # --- Crypto Signals ---

    async def insert_crypto_signal(
        self,
        symbol: str,
        rsi_14: float | None = None,
        macd: float | None = None,
        macd_signal: float | None = None,
        bb_pct_b: float | None = None,
        momentum_score: float = 0.0,
        mean_reversion_score: float = 0.0,
        composite_signal: float = 0.0,
        signal_direction: str = "hold",
        current_price: float = 0.0,
        llm_override: bool = False,
        llm_reasoning: str = "",
    ) -> int:
        cursor = await self._db.db.execute(
            """INSERT INTO crypto_signals (symbol, rsi_14, macd, macd_signal, bb_pct_b,
               momentum_score, mean_reversion_score, composite_signal, signal_direction,
               current_price, llm_override, llm_reasoning)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (symbol, rsi_14, macd, macd_signal, bb_pct_b,
             momentum_score, mean_reversion_score, composite_signal,
             signal_direction, current_price, int(llm_override), llm_reasoning),
        )
        await self._db.db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_crypto_signals(
        self, symbol: str | None = None, limit: int = 50
    ) -> list[dict]:
        query = "SELECT * FROM crypto_signals"
        params: list = []
        if symbol:
            query += " WHERE symbol = ?"
            params.append(symbol)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cursor = await self._db.db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # --- Agent Decisions (unified decision log) ---

    async def insert_agent_decision(
        self,
        agent_type: str,
        symbol: str,
        action: str,
        confidence: float | None = None,
        reasoning: str = "",
        signals_json: str = "{}",
        outcome: str = "executed",
        trade_id: int | None = None,
    ) -> int:
        cursor = await self._db.db.execute(
            """INSERT INTO agent_decisions (agent_type, symbol, action, confidence,
               reasoning, signals_json, outcome, trade_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (agent_type, symbol, action, confidence, reasoning,
             signals_json, outcome, trade_id),
        )
        await self._db.db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_agent_decisions(
        self, agent_type: str | None = None, limit: int = 50, symbol: str | None = None,
        outcome: str | None = None,
    ) -> list[dict]:
        query = "SELECT * FROM agent_decisions WHERE 1=1"
        params: list = []
        if agent_type:
            query += " AND agent_type = ?"
            params.append(agent_type)
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        if outcome:
            query += " AND outcome = ?"
            params.append(outcome)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cursor = await self._db.db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_agent_decision_by_id(self, decision_id: int) -> dict | None:
        cursor = await self._db.db.execute(
            "SELECT * FROM agent_decisions WHERE id = ?", (decision_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def update_agent_decision_outcome(
        self, decision_id: int, outcome: str, trade_id: int | None = None,
    ) -> None:
        if trade_id is not None:
            await self._db.db.execute(
                "UPDATE agent_decisions SET outcome = ?, trade_id = ? WHERE id = ?",
                (outcome, trade_id, decision_id),
            )
        else:
            await self._db.db.execute(
                "UPDATE agent_decisions SET outcome = ? WHERE id = ?",
                (outcome, decision_id),
            )
        await self._db.db.commit()

    async def expire_old_proposals(self, agent_type: str, hours: int = 24) -> int:
        cursor = await self._db.db.execute(
            """UPDATE agent_decisions
               SET outcome = 'expired'
               WHERE agent_type = ? AND outcome = 'pending_approval'
               AND created_at < datetime('now', ?)""",
            (agent_type, f"-{hours} hours"),
        )
        await self._db.db.commit()
        return cursor.rowcount

    # --- Portfolio Drawdown Tracking ---

    async def insert_portfolio_drawdown(
        self,
        platform: str,
        equity: float,
        high_watermark: float,
        drawdown_pct: float,
    ) -> int:
        cursor = await self._db.db.execute(
            """INSERT INTO portfolio_drawdown (platform, equity, high_watermark, drawdown_pct)
               VALUES (?, ?, ?, ?)""",
            (platform, equity, high_watermark, drawdown_pct),
        )
        await self._db.db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_portfolio_drawdown(
        self, platform: str = "alpaca", limit: int = 100
    ) -> list[dict]:
        cursor = await self._db.db.execute(
            """SELECT * FROM portfolio_drawdown
               WHERE platform = ?
               ORDER BY created_at DESC LIMIT ?""",
            (platform, limit),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_high_watermark(self, platform: str = "alpaca") -> float:
        """Get the most recent high watermark for a platform."""
        cursor = await self._db.db.execute(
            """SELECT high_watermark FROM portfolio_drawdown
               WHERE platform = ?
               ORDER BY created_at DESC LIMIT 1""",
            (platform,),
        )
        row = await cursor.fetchone()
        return float(row["high_watermark"]) if row else 0.0

    async def get_last_buy_date(
        self, symbol: str, source_prefix: str = "monitor:drawdown"
    ) -> datetime | None:
        """Get the date of the most recent BUY trade for a symbol from a specific source."""
        cursor = await self._db.db.execute(
            """SELECT created_at FROM trades
               WHERE symbol = ? AND side = 'buy' AND source LIKE ?
               ORDER BY created_at DESC LIMIT 1""",
            (symbol, f"{source_prefix}%"),
        )
        row = await cursor.fetchone()
        if row:
            return datetime.fromisoformat(row["created_at"])
        return None

    async def get_strategy_total_value(
        self, source_prefix: str, symbols: list[str],
    ) -> float:
        """Get total market value of positions bought by a specific strategy.

        This sums up the net bought quantity * current filled price for each symbol.
        """
        if not symbols:
            return 0.0
        placeholders = ",".join("?" * len(symbols))
        cursor = await self._db.db.execute(
            f"""SELECT symbol,
                       SUM(CASE WHEN side = 'buy' THEN quantity ELSE -quantity END) as net_qty,
                       MAX(filled_price) as last_price
                FROM trades
                WHERE source LIKE ? AND symbol IN ({placeholders})
                GROUP BY symbol
                HAVING net_qty > 0""",
            [f"{source_prefix}%", *symbols],
        )
        rows = await cursor.fetchall()
        return sum(dict(r)["net_qty"] * dict(r)["last_price"] for r in rows if dict(r)["last_price"])

    # --- Kalshi Settlements ---

    async def insert_kalshi_settlement(
        self,
        trade_id: int,
        ticker: str,
        side: str,
        quantity: float,
        entry_price: float,
        result: str,
        payout_per_contract: float,
        total_pnl: float,
    ) -> int:
        cursor = await self._db.db.execute(
            """INSERT INTO kalshi_settlements
               (trade_id, ticker, side, quantity, entry_price, result, payout_per_contract, total_pnl)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (trade_id, ticker, side, quantity, entry_price, result, payout_per_contract, total_pnl),
        )
        await self._db.db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_kalshi_settlements(self, limit: int = 50) -> list[dict]:
        cursor = await self._db.db.execute(
            """SELECT ks.*, t.reasoning, t.source
               FROM kalshi_settlements ks
               JOIN trades t ON ks.trade_id = t.id
               ORDER BY ks.settled_at DESC LIMIT ?""",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_settled_trade_ids(self) -> set[int]:
        """Get trade IDs that have already been settled."""
        cursor = await self._db.db.execute(
            "SELECT trade_id FROM kalshi_settlements"
        )
        rows = await cursor.fetchall()
        return {row["trade_id"] for row in rows}

    async def get_unsettled_kalshi_trades(self) -> list[dict]:
        """Get all Kalshi trades that haven't been settled yet."""
        cursor = await self._db.db.execute(
            """SELECT t.* FROM trades t
               WHERE t.platform = 'kalshi'
               AND t.status = 'filled'
               AND t.id NOT IN (SELECT trade_id FROM kalshi_settlements)
               ORDER BY t.created_at ASC"""
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
