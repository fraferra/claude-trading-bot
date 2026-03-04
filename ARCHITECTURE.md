# Claude Trading Bot — Architecture Guide

## Table of Contents

1. [System Overview](#system-overview)
2. [High-Level Architecture](#high-level-architecture)
3. [Research Agent Pipeline](#research-agent-pipeline)
4. [Monitor System](#monitor-system)
5. [Data Flow](#data-flow)
6. [LLM Integration](#llm-integration)
7. [Broker Integration](#broker-integration)
8. [Database Schema](#database-schema)
9. [API & Frontend](#api--frontend)
10. [Configuration](#configuration)
11. [Deployment](#deployment)

---

## System Overview

An autonomous trading bot that uses Claude LLMs to discover, research, and trade stocks via Alpaca, plus analyze prediction markets on Polymarket. The system runs continuously, making trading decisions every 4 hours with weekly self-optimization.

```
+------------------------------------------------------------------+
|                        Trading Bot                                |
|                                                                   |
|  +-------------------+    +-------------------+    +----------+   |
|  | Research Agent    |    | Strategy Monitors  |    | FastAPI  |   |
|  | Pipeline          |    | (Polymarket, etc.) |    | + React  |   |
|  | (every 4 hours)   |    | (5-60 min cycles)  |    | Dashboard|   |
|  +--------+----------+    +--------+----------+    +-----+----+   |
|           |                        |                      |       |
|  +--------v------------------------v----------------------v---+   |
|  |              Core Services                                 |   |
|  |  LLM Analyst | Risk Manager | Market Data | WebSocket     |   |
|  +--------+------------------------+----------------------+---+   |
|           |                        |                      |       |
|  +--------v----------+    +--------v----------+    +------v---+   |
|  | Alpaca Broker     |    | Polymarket Broker |    | SQLite   |   |
|  | (Stocks)          |    | (Predictions)     |    | Database |   |
|  +-------------------+    +-------------------+    +----------+   |
+------------------------------------------------------------------+
```

---

## High-Level Architecture

### Directory Structure

```
src/trading_bot/
  agents/             # Autonomous research agent pipeline (5 agents)
    discovery.py        Discovery Agent — finds candidate stocks from news
    researcher.py       Research Agent — 6-dimensional stock scoring
    selector.py         Selector Agent — portfolio allocation construction
    executor.py         Executor Agent — trade execution via Alpaca
    strategist.py       Strategist Agent — weekly self-review (uses Opus)
    prompts.py          All LLM prompt templates for agents
  analysis/           # Core analysis functions
    llm_analyst.py      Claude API wrapper (Sonnet default, Opus override)
    market_data.py      Market data fetchers (yfinance, RSS, Alpaca)
    prompts.py          LLM prompts for stock/polymarket analysis
  api/                # FastAPI backend
    app.py              App factory, lifespan, middleware
    middleware.py       HTTP Basic Auth middleware
    routers/            9 API route modules + WebSocket
    websocket.py        Real-time event broadcasting
  brokers/            # Trading platform integrations
    base.py             Abstract broker interface
    alpaca_broker.py    Alpaca (stocks) — paper & live
    polymarket_broker.py  Polymarket (predictions) — live
    paper_polymarket.py   Polymarket paper trading simulator
  db/                 # Persistence layer
    database.py         SQLite with WAL mode, schema management
    repository.py       CRUD operations for all tables
  monitors/           # Background task system
    base.py             BaseMonitor abstract class + EventBus
    manager.py          Monitor lifecycle management
    research_agent.py   Research pipeline monitor (4-hour loop)
    strategy_review.py  Weekly strategy review monitor
    stock_watchlist.py  Stock scoring & trading monitor
    polymarket_arb.py   Polymarket arbitrage scanner
    polymarket_probability.py  AI probability edge finder
    cross_market.py     Cross-market logical arbitrage
  risk/               # Risk management
    manager.py          Position limits, daily loss limits, trade throttling
  strategies/         # Trading strategies
    stock_scorer.py     Quantitative scoring (technical, fundamental, sentiment)
    arbitrage.py        Multi-outcome arbitrage detection
    cross_market.py     Cross-market divergence analysis
    probability_edge.py AI vs market probability comparison
  config.py           # Configuration (YAML + env vars)
  models.py           # Pydantic models for everything
  main.py             # CLI entry point (Click)
frontend/             # React + TypeScript dashboard
  src/
    pages/              Dashboard, ResearchAgent, Monitors, etc.
    api/client.ts       API client with all endpoints
    components/         Reusable UI components
```

---

## Research Agent Pipeline

The core autonomous system. Runs every 4 hours as a monitor.

```
                    +-----------------+
                    |   Google News   |
                    |   RSS Feeds     |
                    +--------+--------+
                             |
                    +--------v--------+
                    |   DISCOVERY     |   Sonnet
                    |   AGENT         |
                    |                 |
                    | Scans 3 feeds:  |
                    | - Market movers |
                    | - Earnings      |
                    | - Sector rotation|
                    | + Watchlist     |
                    +--------+--------+
                             |
                    Up to 20 candidate (symbol, reason) pairs
                             |
              +--------------+--------------+
              |              |              |
     +--------v---+ +--------v---+ +--------v---+
     | RESEARCH   | | RESEARCH   | | RESEARCH   |   Sonnet
     | AGENT      | | AGENT      | | AGENT      |   x15 parallel
     | (AAPL)     | | (NVDA)     | | (OUST)     |   (semaphore=5)
     +--------+---+ +--------+---+ +--------+---+
              |              |              |
              | ResearchReport per stock    |
              | (6-dim scores, catalysts,   |
              |  risks, recommendation)     |
              +--------------+--------------+
                             |
                    +--------v--------+
                    |   SELECTOR      |   Sonnet
                    |   AGENT         |
                    |                 |
                    | 1. Filter by    |
                    |    min score    |
                    | 2. Rank & weight|
                    |    proportional |
                    | 3. Cap at 15%  |
                    |    per position |
                    | 4. LLM review  |
                    |    for issues   |
                    +--------+--------+
                             |
                    PortfolioAllocation
                    (entries with target weights + actions)
                             |
                    +--------v--------+
                    |   EXECUTOR      |   No LLM
                    |   AGENT         |
                    |                 |
                    | 1. Sells first  |
                    |    (free cash)  |
                    | 2. Then buys    |
                    | 3. Risk check   |
                    |    each order   |
                    | 4. Submit via   |
                    |    Alpaca       |
                    +--------+--------+
                             |
                    Trades logged to DB
                    WebSocket events broadcast


         +------- Runs weekly (Sunday) -------+
         |                                     |
         |  +-----------------------------+    |
         |  |   STRATEGIST AGENT          |    |   Opus
         |  |                             |    |
         |  | 1. Fetch last 7 days trades |    |
         |  | 2. Analyze win rate, P&L    |    |
         |  | 3. Suggest param changes    |    |
         |  |    within safe bounds       |    |
         |  | 4. Apply validated changes  |    |
         |  +-----------------------------+    |
         +-------------------------------------+
```

### 6-Dimensional Scoring (Research Agent)

Each stock gets scored 1-10 on six dimensions by the LLM, informed by quantitative data:

```
                        Financial Health ──── 8.2
                       /
                      /   Growth Potential ── 7.5
                     /   /
     Composite ─────+───+── News Sentiment ── 6.8
     Score: 7.1      \   \
                      \   News Impact ─────── 7.3
                       \
                        Price Momentum ────── 5.9
                         \
                          Volatility Risk ─── 6.9

     Inputs to LLM:
     ├── Technical indicators (SMA, RSI, MACD, regime)
     ├── Fundamentals (P/E, market cap, beta, sector)
     ├── Recent news headlines (8 articles)
     ├── Price history (last 10 days OHLCV)
     └── Quantitative composite scores from pure functions
```

### Selector: Weight Allocation

```
     Ranked by composite score:
     ┌──────────┬───────┬────────────┬──────────────────┐
     │ Symbol   │ Score │ Raw Weight │ Capped at 15%    │
     ├──────────┼───────┼────────────┼──────────────────┤
     │ NVDA     │ 8.1   │ 18.2%      │ 15.0%            │
     │ AAPL     │ 7.5   │ 16.8%      │ 15.0%            │
     │ GOOGL    │ 7.2   │ 16.1%      │ 15.0%            │
     │ MSFT     │ 6.9   │ 15.5%      │ 15.0%            │
     │ OUST     │ 6.4   │ 14.3%      │ 14.3%            │
     │ ...      │ ...   │ ...        │ ...              │
     ├──────────┼───────┼────────────┼──────────────────┤
     │ CASH     │ —     │ —          │ 20.0% (reserved) │
     └──────────┴───────┴────────────┴──────────────────┘

     Constraints:
     • max_positions = 10
     • max_single_position_pct = 15%
     • min_cash_reserve_pct = 20%
     • rebalance_drift_threshold = 5%
```

---

## Monitor System

Monitors are background async loops that execute strategies at configurable intervals.

```
     MonitorManager
     ├── Manages lifecycle: start, stop, pause, resume
     ├── Persists state to DB (survives restarts)
     └── restore_from_db() on startup
           │
           ├── ResearchAgentMonitor ──── every 4 hours
           │   └── Runs: Discovery → Research → Selector → Executor
           │
           ├── StrategyReviewMonitor ─── every 7 days
           │   └── Runs: Strategist weekly_review + apply_changes
           │
           ├── StockWatchlistMonitor ─── every 30 min
           │   └── Scores watchlist stocks, executes strong signals
           │
           ├── PolymarketArbMonitor ──── every 5 min
           │   └── Scans for multi-outcome arbitrage
           │
           ├── ProbabilityEdgeMonitor ── every 60 min
           │   └── AI probability vs market price comparison
           │
           └── CrossMarketMonitor ────── every 15 min
               └── Logical arbitrage between related markets

     Each monitor inherits from BaseMonitor:
     ┌─────────────────────────────────────────┐
     │ BaseMonitor                             │
     │   monitor_id: str                       │
     │   status: running | paused | stopped    │
     │   _task: asyncio.Task                   │
     │                                         │
     │   start() → creates async loop task     │
     │   stop()  → cancels task, saves state   │
     │   pause() → sets flag, loop sleeps      │
     │   resume()→ clears flag                 │
     │                                         │
     │   abstract run_cycle() → subclass impl  │
     │   abstract get_interval_seconds()       │
     └─────────────────────────────────────────┘
```

---

## Data Flow

### Single Pipeline Cycle (every 4 hours)

```
     Google News RSS ──────────────────────────────────────────────┐
     (3 feeds in parallel)                                         │
         │                                                         │
         v                                                         │
     ┌─────────────┐   ┌──────────────┐   ┌───────────────┐       │
     │ Discovery   │──>│ 15 symbols   │──>│ Research x15  │       │
     │ (Sonnet)    │   │ + reasons    │   │ (Sonnet, ||)  │       │
     └─────────────┘   └──────────────┘   └───────┬───────┘       │
                                                   │               │
     yfinance API ──── stock prices, fundamentals ─┘               │
                                                   │               │
                                           15 ResearchReports      │
                                                   │               │
                                          ┌────────v────────┐      │
     Alpaca API ──── positions, equity ──>│ Selector        │      │
                                          │ (Sonnet)        │      │
                                          └────────┬────────┘      │
                                                   │               │
                                          PortfolioAllocation      │
                                          (buys, sells, holds)     │
                                                   │               │
                                          ┌────────v────────┐      │
     Alpaca API <──── submit orders ──────│ Executor        │      │
                                          │ (no LLM)        │      │
                                          └────────┬────────┘      │
                                                   │               │
                                          ┌────────v────────┐      │
                                          │ SQLite DB       │      │
                                          │ - trades        │      │
                                          │ - reports       │      │
                                          │ - allocations   │      │
                                          └────────┬────────┘      │
                                                   │               │
                                          ┌────────v────────┐      │
                                          │ WebSocket       │      │
                                          │ (real-time UI)  │      │
                                          └─────────────────┘      │
                                                                   │
     Dashboard <───────────────────────────────────────────────────┘
```

---

## LLM Integration

### Model Assignment

```
     ┌───────────────────────────────────────────────────────┐
     │                    LLM Calls                          │
     ├────────────────────┬──────────────────┬───────────────┤
     │ Agent              │ Model            │ Calls/Cycle   │
     ├────────────────────┼──────────────────┼───────────────┤
     │ Discovery          │ Sonnet           │ 1             │
     │ Research (x15)     │ Sonnet           │ 15            │
     │ Selector           │ Sonnet           │ 1             │
     │ Executor           │ — (no LLM)       │ 0             │
     │ Strategist         │ Opus             │ 1/week        │
     │ Stock Watchlist    │ Sonnet           │ per stock     │
     │ Polymarket analysis│ Sonnet           │ per market    │
     ├────────────────────┼──────────────────┼───────────────┤
     │ Total per cycle    │                  │ ~17 calls     │
     │ Est. cost/month    │                  │ ~$12-15       │
     └────────────────────┴──────────────────┴───────────────┘
```

### Call Flow

```
     Agent ──> LLMAnalyst._call_llm_raw(system, user, model_override?)
                  │
                  ├── Uses model_override if provided (Opus for strategist)
                  ├── Otherwise uses config.llm.model (Sonnet)
                  │
                  v
              anthropic.Anthropic.messages.create(
                  model=...,
                  system=PROMPT_TEMPLATE,
                  messages=[{role: "user", content: FORMATTED_DATA}]
              )
                  │
                  v
              Raw text response ──> JSON.parse ──> Pydantic model
```

---

## Broker Integration

### Alpaca (Stocks)

```
     AlpacaBroker
     ├── Paper mode: trades execute against Alpaca's paper account
     ├── Live mode: real money (gated by config.alpaca.paper)
     │
     ├── get_account() ──────> PortfolioSummary (cash, equity, positions)
     ├── get_positions() ────> list[Position] (qty, price, P&L)
     ├── submit_order() ─────> OrderResult (fills, polls for price)
     │   └── Polls up to 5x (0.5s each) for fill confirmation
     ├── cancel_order() ─────> bool
     ├── get_order_status() ─> OrderStatus
     └── get_quote() ────────> float (mid-point of bid/ask)
```

### Polymarket (Predictions)

```
     PolymarketBroker / PaperPolymarketBroker
     ├── Paper mode: simulated order book with slippage
     ├── Live mode: CLOB API with real USDC
     │
     ├── get_account() ──────> PortfolioSummary
     ├── submit_order() ─────> OrderResult
     └── get_active_markets()> list of tradeable markets
```

---

## Database Schema

SQLite with WAL mode for concurrent reads. 14 tables total.

```
     ┌──────────────────┐     ┌──────────────────────┐
     │ trades           │     │ research_reports     │
     ├──────────────────┤     ├──────────────────────┤
     │ id               │     │ id                   │
     │ order_id         │     │ symbol               │
     │ symbol           │     │ company_name         │
     │ side (BUY/SELL)  │     │ sector               │
     │ quantity         │     │ composite_score      │
     │ filled_price     │     │ dimension_scores_json│
     │ platform         │     │ recommendation       │
     │ source           │     │ target_weight        │
     │ strategy_name    │     │ catalysts_json       │
     │ reasoning        │     │ risks_json           │
     │ confidence       │     │ created_at           │
     │ status           │     └──────────────────────┘
     │ created_at       │
     └──────────────────┘     ┌──────────────────────┐
                              │ portfolio_allocations│
     ┌──────────────────┐     ├──────────────────────┤
     │ monitor_state    │     │ id                   │
     ├──────────────────┤     │ entries_json         │
     │ monitor_id       │     │ cash_reserve         │
     │ monitor_type     │     │ rebalance_needed     │
     │ status           │     │ reasoning            │
     │ total_trades     │     │ created_at           │
     │ total_pnl        │     └──────────────────────┘
     │ current_scale    │
     │ updated_at       │     ┌──────────────────────┐
     └──────────────────┘     │ strategy_memos       │
                              ├──────────────────────┤
     ┌──────────────────┐     │ id                   │
     │ discovery_runs   │     │ period_start/end     │
     ├──────────────────┤     │ total_return_pct     │
     │ id               │     │ win_rate             │
     │ candidates_json  │     │ lessons_json         │
     │ source_queries   │     │ parameter_changes    │
     │ num_candidates   │     │ next_week_focus_json │
     │ created_at       │     │ created_at           │
     └──────────────────┘     └──────────────────────┘

     Other tables: portfolio_snapshots, strategy_results,
                   decisions, stock_scores
```

---

## API & Frontend

### API Endpoints

```
     /api
     ├── /portfolio          GET    Account summary + positions
     ├── /analysis
     │   ├── /stock/:sym     POST   Analyze a stock
     │   └── /polymarket/:id POST   Analyze a market
     ├── /trade
     │   ├── /stock          POST   Execute stock trade
     │   └── /polymarket     POST   Execute prediction trade
     ├── /strategies
     │   ├── /arbitrage      POST   Run arbitrage scan
     │   ├── /cross-market   POST   Run cross-market scan
     │   └── /probability    POST   Run probability edge scan
     ├── /monitors
     │   ├── /               GET    List active monitors
     │   ├── /:type/start    POST   Start a monitor
     │   ├── /:id/stop       POST   Stop a monitor
     │   ├── /:id/pause      POST   Pause a monitor
     │   └── /:id/resume     POST   Resume a monitor
     ├── /research
     │   ├── /status         GET    Agent config + active state
     │   ├── /reports        GET    Latest research reports
     │   ├── /reports/:sym   GET    Reports for a symbol
     │   ├── /allocation     GET    Current target allocation
     │   ├── /memos          GET    Strategy review memos
     │   ├── /discoveries    GET    Recent discovery runs
     │   ├── /run            POST   Trigger full pipeline now
     │   └── /discover       POST   Trigger discovery only
     ├── /history            GET    Trade history + decisions
     ├── /market-data        GET    Quotes, charts
     ├── /config             GET    Current configuration
     └── /ws                 WS     Real-time events
```

### Frontend Pages

```
     ┌─────────────────────────────────────────────────┐
     │  Trading Bot          [Connected]                │
     │                                                  │
     │  ┌──────────────┐  ┌─────────────────────────┐  │
     │  │ Navigation   │  │ Page Content             │  │
     │  │              │  │                          │  │
     │  │ Dashboard    │  │ Depends on selected page │  │
     │  │ Research ●   │  │                          │  │
     │  │ Strategies   │  │ Dashboard: portfolio     │  │
     │  │ Trade        │  │  summary, P&L chart      │  │
     │  │ Markets      │  │                          │  │
     │  │ Monitors     │  │ Research: reports table,  │  │
     │  │ Activity     │  │  allocation, discoveries  │  │
     │  │ Settings     │  │                          │  │
     │  │              │  │ Monitors: start/stop,     │  │
     │  │              │  │  active list, history     │  │
     │  │              │  │                          │  │
     │  └──────────────┘  └─────────────────────────┘  │
     └─────────────────────────────────────────────────┘
```

---

## Configuration

### Config Hierarchy (highest priority wins)

```
     Environment Variables     ← secrets (API keys, auth)
           │
           v
     config.yaml               ← tunable parameters
           │
           v
     Dataclass defaults        ← safe fallbacks
```

### Key Settings

```yaml
llm:
  model: claude-sonnet-4-5-20250929          # Default for all agents
  strategist_model: claude-opus-4-6  # Opus for weekly review only

research_agent:
  scan_interval_minutes: 240    # Pipeline runs every 4 hours
  max_candidates: 20            # Max stocks per discovery
  max_positions: 10             # Max portfolio positions
  max_single_position_pct: 0.15 # 15% max per stock
  min_cash_reserve_pct: 0.20    # Keep 20% cash
  min_research_score: 5.0       # Min score to consider (1-10)

risk:
  max_position_pct: 0.10        # Max 10% per position
  daily_loss_limit_pct: 0.03    # Stop if daily loss > 3%
  max_trades_per_day: 10
```

---

## Deployment

### Docker Architecture

```
     ┌─────────────────────────────────────────┐
     │  Docker Image (multi-stage build)       │
     │                                         │
     │  Stage 1: node:22-alpine                │
     │    └── npm install + npm run build       │
     │        (frontend/dist/)                  │
     │                                         │
     │  Stage 2: python:3.13-slim              │
     │    ├── pip install . (trading bot)       │
     │    ├── COPY frontend/dist from stage 1   │
     │    ├── config.yaml                       │
     │    └── CMD: trading-bot serve --host 0.0.0.0 │
     └─────────────────────────────────────────┘
```

### Railway Deployment

```
     Railway Project
     ├── Service: cozy-cooperation
     │   ├── Dockerfile build (auto)
     │   ├── Port: 8000
     │   └── Env vars: API keys + AUTH_USERNAME/PASSWORD
     │
     ├── Volume: /app/data
     │   └── trading_bot.db (persistent SQLite)
     │
     └── Domain: cozy-cooperation-production.up.railway.app
         └── Basic Auth → username/password required
```

### Auth Flow

```
     Browser ──> https://your-domain.up.railway.app
         │
         v
     BasicAuthMiddleware
         │
         ├── No credentials → 401 + WWW-Authenticate header
         │                     → Browser shows login dialog
         │
         ├── Wrong credentials → 401
         │
         └── Correct credentials → pass through
             │
             v
         FastAPI routes (API + frontend)
```

---

## Safety & Risk Management

### Trade Safety Chain

```
     Research Pipeline
         │
         v
     Selector: max 15% per position, 20% cash reserve
         │
         v
     Executor: RiskManager.check_order()
         ├── Position size within max_position_pct?
         ├── Total exposure within max_total_exposure_pct?
         ├── Daily loss limit not exceeded?
         ├── Max trades/day not exceeded?
         └── Adjusted quantity if needed
         │
         v
     Alpaca: DAY time-in-force (no overnight risk on pending)
```

### Strategist Safety Bounds

The weekly strategist can tune parameters, but only within safe ranges:

```
     Parameter                    Min     Max
     ─────────────────────────    ────    ────
     technical_weight             0.10    0.60
     fundamental_weight           0.10    0.60
     sentiment_weight             0.10    0.60
     min_research_score           3.0     8.0
     max_single_position_pct      0.05    0.20
     rebalance_drift_threshold    0.02    0.10
```

---

## Cost Estimate

Running 24/7 with research pipeline every 4 hours:

```
     Sonnet (discovery + research + selector):
       ~17 calls/cycle x 6 cycles/day x 30 days
       Input: ~7.7M tokens/mo × $3/M  = ~$23
       Output: ~2.1M tokens/mo × $15/M = ~$31
       Subtotal: ~$54/month

     Opus (strategist only):
       ~4 calls/month (weekly)
       Input: ~10K tokens × $15/M  = ~$0.15
       Output: ~3K tokens × $75/M  = ~$0.23
       Subtotal: ~$0.40/month

     Total: ~$55/month
```
