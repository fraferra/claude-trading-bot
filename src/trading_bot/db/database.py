"""Async SQLite database for trade history, monitor state, and portfolio snapshots."""

from __future__ import annotations

import aiosqlite

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity REAL NOT NULL,
    filled_price REAL,
    platform TEXT NOT NULL,
    source TEXT NOT NULL,
    strategy_name TEXT,
    reasoning TEXT,
    confidence REAL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    cash REAL NOT NULL,
    equity REAL NOT NULL,
    daily_pnl REAL NOT NULL DEFAULT 0.0,
    positions_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS strategy_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_name TEXT NOT NULL,
    decisions_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS monitor_state (
    monitor_id TEXT PRIMARY KEY,
    monitor_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'stopped',
    config_json TEXT NOT NULL DEFAULT '{}',
    last_run TEXT,
    total_trades INTEGER NOT NULL DEFAULT 0,
    total_pnl REAL NOT NULL DEFAULT 0.0,
    win_count INTEGER NOT NULL DEFAULT 0,
    loss_count INTEGER NOT NULL DEFAULT 0,
    current_min_edge REAL NOT NULL DEFAULT 0.0,
    current_position_scale REAL NOT NULL DEFAULT 1.0,
    error_message TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS monitor_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    monitor_id TEXT NOT NULL,
    trade_id INTEGER NOT NULL,
    entry_price REAL,
    exit_price REAL,
    quantity REAL DEFAULT 1.0,
    pnl REAL,
    is_closed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (monitor_id) REFERENCES monitor_state(monitor_id),
    FOREIGN KEY (trade_id) REFERENCES trades(id)
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL,
    confidence REAL NOT NULL,
    reasoning TEXT,
    source TEXT NOT NULL,
    strategy_name TEXT,
    was_executed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS stock_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    technical_score REAL,
    fundamental_score REAL,
    sentiment_score REAL,
    composite_score REAL,
    regime TEXT,
    signal_weights_json TEXT,
    suggested_action TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_created ON trades(created_at);
CREATE INDEX IF NOT EXISTS idx_trades_source ON trades(source);
CREATE INDEX IF NOT EXISTS idx_snapshots_created ON portfolio_snapshots(created_at);
CREATE INDEX IF NOT EXISTS idx_strategy_results_name ON strategy_results(strategy_name);
CREATE INDEX IF NOT EXISTS idx_monitor_trades_monitor ON monitor_trades(monitor_id);
CREATE INDEX IF NOT EXISTS idx_stock_scores_symbol ON stock_scores(symbol);
CREATE INDEX IF NOT EXISTS idx_decisions_created ON decisions(created_at);

CREATE TABLE IF NOT EXISTS research_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    company_name TEXT,
    sector TEXT,
    composite_score REAL,
    dimension_scores_json TEXT NOT NULL DEFAULT '{}',
    recommendation TEXT,
    target_weight REAL,
    catalysts_json TEXT NOT NULL DEFAULT '[]',
    risks_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS portfolio_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entries_json TEXT NOT NULL DEFAULT '[]',
    cash_reserve REAL NOT NULL DEFAULT 0.20,
    rebalance_needed INTEGER NOT NULL DEFAULT 0,
    reasoning TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS strategy_memos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period_start TEXT,
    period_end TEXT,
    total_return_pct REAL,
    win_rate REAL,
    lessons_json TEXT NOT NULL DEFAULT '[]',
    parameter_changes_json TEXT NOT NULL DEFAULT '{}',
    next_week_focus_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS discovery_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidates_json TEXT NOT NULL DEFAULT '[]',
    source_queries_json TEXT NOT NULL DEFAULT '[]',
    num_candidates INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_research_reports_symbol ON research_reports(symbol);
CREATE INDEX IF NOT EXISTS idx_research_reports_created ON research_reports(created_at);
CREATE INDEX IF NOT EXISTS idx_portfolio_allocations_created ON portfolio_allocations(created_at);
CREATE INDEX IF NOT EXISTS idx_strategy_memos_created ON strategy_memos(created_at);

-- Kalshi probability estimates log
CREATE TABLE IF NOT EXISTS kalshi_estimates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    title TEXT,
    market_price REAL NOT NULL,
    ai_probability REAL NOT NULL,
    edge_pct REAL NOT NULL,
    kelly_fraction REAL DEFAULT 0.0,
    suggested_side TEXT,
    reasoning TEXT,
    category TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_kalshi_estimates_ticker ON kalshi_estimates(ticker);
CREATE INDEX IF NOT EXISTS idx_kalshi_estimates_created ON kalshi_estimates(created_at);

-- Crypto technical signals log
CREATE TABLE IF NOT EXISTS crypto_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    rsi_14 REAL,
    macd REAL,
    macd_signal REAL,
    bb_pct_b REAL,
    momentum_score REAL,
    mean_reversion_score REAL,
    composite_signal REAL,
    signal_direction TEXT,
    current_price REAL,
    llm_override INTEGER DEFAULT 0,
    llm_reasoning TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_crypto_signals_symbol ON crypto_signals(symbol);
CREATE INDEX IF NOT EXISTS idx_crypto_signals_created ON crypto_signals(created_at);

-- Unified agent decision log for visibility into decision-making
CREATE TABLE IF NOT EXISTS agent_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_type TEXT NOT NULL,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL,
    confidence REAL,
    reasoning TEXT,
    signals_json TEXT,
    outcome TEXT,
    trade_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_agent_decisions_type ON agent_decisions(agent_type);
CREATE INDEX IF NOT EXISTS idx_agent_decisions_created ON agent_decisions(created_at);

-- Portfolio drawdown tracking (high watermark and drawdown history)
CREATE TABLE IF NOT EXISTS portfolio_drawdown (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL DEFAULT 'alpaca',
    equity REAL NOT NULL,
    high_watermark REAL NOT NULL,
    drawdown_pct REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_portfolio_drawdown_created ON portfolio_drawdown(created_at);

-- Kalshi settlement tracking for concluded bets
CREATE TABLE IF NOT EXISTS kalshi_settlements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity REAL NOT NULL,
    entry_price REAL NOT NULL,
    result TEXT NOT NULL,
    payout_per_contract REAL NOT NULL,
    total_pnl REAL NOT NULL,
    settled_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (trade_id) REFERENCES trades(id)
);

CREATE INDEX IF NOT EXISTS idx_kalshi_settlements_ticker ON kalshi_settlements(ticker);
CREATE INDEX IF NOT EXISTS idx_kalshi_settlements_settled ON kalshi_settlements(settled_at);
CREATE INDEX IF NOT EXISTS idx_trades_platform ON trades(platform);
"""


class Database:
    """Async SQLite database wrapper."""

    def __init__(self, db_path: str = "trading_bot.db") -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._run_migrations()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def _run_migrations(self) -> None:
        assert self._db is not None
        await self._db.executescript(SCHEMA_SQL)
        await self._db.commit()

    @property
    def db(self) -> aiosqlite.Connection:
        assert self._db is not None, "Database not connected"
        return self._db
