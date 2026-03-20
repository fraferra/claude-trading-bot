from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# --- Enums ---

class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class Action(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class Platform(str, Enum):
    ALPACA = "alpaca"
    POLYMARKET = "polymarket"
    KALSHI = "kalshi"
    ALPACA_CRYPTO = "alpaca_crypto"


# --- LLM Output Models ---

class TradeDecision(BaseModel):
    action: Action
    symbol: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    suggested_position_pct: float = Field(
        ge=0.0, le=1.0, default=0.0,
        description="Suggested position as fraction of portfolio (for stocks)",
    )
    suggested_size_usd: float = Field(
        ge=0.0, default=0.0,
        description="Suggested size in USD (for polymarket)",
    )
    side: Side | None = Field(
        default=None,
        description="YES/NO side for polymarket (mapped to buy/sell)",
    )


# --- Order Models ---

class OrderRequest(BaseModel):
    symbol: str
    side: Side
    quantity: float
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    stop_price: float | None = None
    platform: Platform = Platform.ALPACA


class OrderResult(BaseModel):
    order_id: str
    symbol: str
    side: Side
    quantity: float
    status: OrderStatus
    filled_price: float | None = None
    filled_at: datetime | None = None
    platform: Platform


# --- Position & Portfolio Models ---

class Position(BaseModel):
    symbol: str
    quantity: float
    avg_entry_price: float
    current_price: float = 0.0
    market_value: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_intraday_pl: float = 0.0
    platform: Platform


class PortfolioSummary(BaseModel):
    cash: float
    equity: float
    positions: list[Position] = Field(default_factory=list)
    daily_pnl: float = 0.0
    platform: Platform


# --- Market Data Models ---

class StockData(BaseModel):
    symbol: str
    current_price: float
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: int = 0
    sma_20: float | None = None
    sma_50: float | None = None
    rsi_14: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    price_history: list[dict] = Field(default_factory=list)


class StockFundamentals(BaseModel):
    symbol: str
    market_cap: float | None = None
    pe_ratio: float | None = None
    forward_pe: float | None = None
    dividend_yield: float | None = None
    beta: float | None = None
    fifty_two_week_high: float | None = None
    fifty_two_week_low: float | None = None
    sector: str | None = None
    industry: str | None = None


class NewsItem(BaseModel):
    title: str
    source: str = ""
    published: str = ""
    url: str = ""


class PolymarketData(BaseModel):
    condition_id: str
    question: str
    yes_price: float
    no_price: float
    volume: float = 0.0
    liquidity: float = 0.0
    end_date: str | None = ""
    description: str | None = ""
    tokens: list[dict] = Field(default_factory=list)


# --- Strategy Models ---

class MarketOutcome(BaseModel):
    """A single outcome within a multi-outcome Polymarket event."""
    condition_id: str
    question: str
    outcome_label: str = ""
    yes_price: float
    no_price: float
    token_id: str = ""
    liquidity: float = 0.0


class EventData(BaseModel):
    """A Polymarket event containing multiple market outcomes."""
    event_id: str
    title: str
    slug: str = ""
    outcomes: list[MarketOutcome] = Field(default_factory=list)
    end_date: str = ""


class ArbitrageOpportunity(BaseModel):
    """A detected multi-outcome arbitrage opportunity."""
    event_id: str
    event_title: str
    outcomes: list[MarketOutcome]
    price_sum: float = Field(description="Sum of YES prices across all outcomes")
    edge_pct: float = Field(description="Edge as percentage after fees")
    direction: str = Field(description="'buy_all' if sum < 1.0, 'sell_all' if sum > 1.0")
    estimated_profit_per_dollar: float = 0.0
    fee_estimate_pct: float = 0.01
    timestamp: datetime = Field(default_factory=datetime.now)


class LogicalRelationship(BaseModel):
    """A logical relationship between two Polymarket markets."""
    relationship_type: str = Field(
        description="'entailment' | 'mutual_exclusion' | 'subset' | 'conditional'"
    )
    market_a_id: str
    market_a_question: str
    market_b_id: str
    market_b_question: str
    explanation: str = ""
    constraint: str = Field(
        default="",
        description="Human-readable constraint, e.g., 'P(A) <= P(B)'"
    )


class CrossMarketOpportunity(BaseModel):
    """A detected cross-market logical arbitrage opportunity."""
    relationship: LogicalRelationship
    market_a_price: float
    market_b_price: float
    expected_constraint_price: float = Field(
        default=0.0,
        description="What market B's price should be given market A"
    )
    edge_pct: float
    suggested_trades: list[TradeDecision] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    reasoning: str = ""


class ProbabilityEstimate(BaseModel):
    """An LLM-generated probability estimate for a market."""
    condition_id: str
    question: str
    market_price: float = Field(description="Current YES price")
    ai_probability: float = Field(ge=0.0, le=1.0, description="AI-estimated true probability")
    confidence_interval_low: float = Field(ge=0.0, le=1.0, default=0.0)
    confidence_interval_high: float = Field(ge=0.0, le=1.0, default=1.0)
    edge_pct: float = Field(description="ai_probability - market_price")
    kelly_fraction: float = Field(ge=0.0, le=1.0, default=0.0)
    suggested_side: Side | None = None
    reasoning: str = ""
    signals_used: list[str] = Field(default_factory=list)


class StrategyResult(BaseModel):
    """Unified result from any strategy execution."""
    strategy_name: str
    decisions: list[TradeDecision] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.now)


# --- Stock Scoring Models ---

class MarketRegime(str, Enum):
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    MEAN_REVERTING = "mean_reverting"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"


class TechnicalScore(BaseModel):
    symbol: str
    sma_trend: float = Field(ge=-1.0, le=1.0, default=0.0)
    rsi_signal: float = Field(ge=-1.0, le=1.0, default=0.0)
    macd_signal: float = Field(ge=-1.0, le=1.0, default=0.0)
    momentum_score: float = Field(ge=-1.0, le=1.0, default=0.0)
    composite: float = Field(ge=-1.0, le=1.0, default=0.0)


class FundamentalScore(BaseModel):
    symbol: str
    pe_vs_sector: float = Field(ge=-1.0, le=1.0, default=0.0)
    growth_score: float = Field(ge=-1.0, le=1.0, default=0.0)
    quality_score: float = Field(ge=-1.0, le=1.0, default=0.0)
    composite: float = Field(ge=-1.0, le=1.0, default=0.0)


class SentimentScore(BaseModel):
    symbol: str
    sentiment: float = Field(ge=-1.0, le=1.0, default=0.0)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    key_factors: list[str] = Field(default_factory=list)


class StockCompositeScore(BaseModel):
    symbol: str
    technical: TechnicalScore
    fundamental: FundamentalScore
    sentiment: SentimentScore
    regime: MarketRegime = MarketRegime.LOW_VOLATILITY
    composite_score: float = Field(ge=-1.0, le=1.0, default=0.0)
    signal_weights: dict[str, float] = Field(default_factory=dict)
    suggested_action: Action = Action.HOLD
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    reasoning: str = ""
    timestamp: datetime = Field(default_factory=datetime.now)


class StockRanking(BaseModel):
    rankings: list[StockCompositeScore] = Field(default_factory=list)
    regime: MarketRegime = MarketRegime.LOW_VOLATILITY
    timestamp: datetime = Field(default_factory=datetime.now)


# --- Monitor Models ---

class MonitorStatus(str, Enum):
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


class MonitorState(BaseModel):
    monitor_id: str
    monitor_type: str
    status: MonitorStatus = MonitorStatus.STOPPED
    last_run: datetime | None = None
    total_trades: int = 0
    total_pnl: float = 0.0
    win_rate: float = 0.0
    current_position_scale: float = 1.0
    current_min_edge: float = 0.0
    error_message: str = ""


# --- WebSocket Models ---

class WSEventType(str, Enum):
    PORTFOLIO_UPDATE = "portfolio_update"
    TRADE_EXECUTED = "trade_executed"
    STRATEGY_SIGNAL = "strategy_signal"
    MONITOR_STATUS = "monitor_status"
    SHORT_PROPOSAL = "short_proposal"
    REGIME_UPDATE = "regime_update"
    ERROR = "error"


class WSEvent(BaseModel):
    type: WSEventType
    data: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.now)


# --- Risk Models ---

class RiskCheckResult(BaseModel):
    approved: bool
    reason: str = ""
    adjusted_quantity: float | None = None


# --- Research Agent Models ---

class DimensionScores(BaseModel):
    """6-dimensional stock scoring (1-10 scale, per 3S-Trader)."""
    financial_health: float = Field(ge=1.0, le=10.0, default=5.0)
    growth_potential: float = Field(ge=1.0, le=10.0, default=5.0)
    news_sentiment: float = Field(ge=1.0, le=10.0, default=5.0)
    news_impact: float = Field(ge=1.0, le=10.0, default=5.0)
    price_momentum: float = Field(ge=1.0, le=10.0, default=5.0)
    volatility_risk: float = Field(ge=1.0, le=10.0, default=5.0)
    reasoning: dict[str, str] = Field(default_factory=dict)


class ResearchReport(BaseModel):
    """Complete research output for a single stock."""
    symbol: str
    company_name: str = ""
    sector: str = ""
    dimension_scores: DimensionScores = Field(default_factory=DimensionScores)
    composite_score: float = Field(ge=1.0, le=10.0, default=5.0)
    technical: TechnicalScore | None = None
    fundamental: FundamentalScore | None = None
    sentiment: SentimentScore | None = None
    regime: MarketRegime = MarketRegime.LOW_VOLATILITY
    catalysts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    llm_recommendation: str = "hold"
    target_weight: float = Field(ge=0.0, le=1.0, default=0.0)
    timestamp: datetime = Field(default_factory=datetime.now)


class AllocationEntry(BaseModel):
    symbol: str
    target_weight: float = 0.0
    current_weight: float = 0.0
    research_score: float = 0.0
    action: str = "hold"


class PortfolioAllocation(BaseModel):
    entries: list[AllocationEntry] = Field(default_factory=list)
    cash_reserve: float = 0.20
    total_positions: int = 0
    rebalance_needed: bool = False
    reasoning: str = ""
    timestamp: datetime = Field(default_factory=datetime.now)


# --- Kalshi Models ---

class KalshiMarketData(BaseModel):
    """Data for a single Kalshi market."""
    ticker: str
    event_ticker: str
    title: str
    subtitle: str = ""
    yes_price: float = Field(ge=0.0, le=1.0, description="YES price in decimal (converted from cents)")
    no_price: float = Field(ge=0.0, le=1.0)
    volume: int = 0
    open_interest: int = 0
    open_time: str = ""
    close_time: str = ""
    result: str = ""
    category: str = ""
    status: str = ""


class KalshiEventData(BaseModel):
    """A Kalshi event containing multiple markets."""
    event_ticker: str
    title: str
    category: str = ""
    markets: list[KalshiMarketData] = Field(default_factory=list)


class KalshiProbabilityEstimate(BaseModel):
    """AI probability estimate for a Kalshi market."""
    ticker: str
    title: str
    market_price: float = Field(description="Current YES price (decimal)")
    ai_probability: float = Field(ge=0.0, le=1.0)
    confidence_interval_low: float = Field(ge=0.0, le=1.0, default=0.0)
    confidence_interval_high: float = Field(ge=0.0, le=1.0, default=1.0)
    edge_pct: float
    kelly_fraction: float = Field(ge=0.0, le=1.0, default=0.0)
    suggested_side: Side | None = None
    reasoning: str = ""
    category: str = ""


# --- Crypto Models ---

class CryptoBarData(BaseModel):
    """Aggregated bar data for a crypto pair."""
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float = 0.0


class CryptoTechnicalSignals(BaseModel):
    """Technical indicator signals for a crypto pair."""
    symbol: str
    rsi_14: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_histogram: float | None = None
    bb_upper: float | None = None
    bb_middle: float | None = None
    bb_lower: float | None = None
    bb_pct_b: float | None = None
    momentum_score: float = Field(ge=-1.0, le=1.0, default=0.0)
    mean_reversion_score: float = Field(ge=-1.0, le=1.0, default=0.0)
    composite_signal: float = Field(ge=-1.0, le=1.0, default=0.0)
    signal_direction: Action = Action.HOLD
    current_price: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.now)


class CryptoTradeDecision(BaseModel):
    """Trade decision specific to crypto with extra context."""
    symbol: str
    action: Action
    confidence: float = Field(ge=0.0, le=1.0)
    technical_signals: CryptoTechnicalSignals
    llm_override: bool = False
    llm_reasoning: str = ""
    suggested_size_usd: float = 0.0
    order_type: OrderType = OrderType.LIMIT
    limit_price: float | None = None


# --- Short Selling Models ---

class ShortSignals(BaseModel):
    """Technical signals used for short candidate scoring."""
    symbol: str
    rsi_2: float | None = None
    rsi_14: float | None = None
    bb_pct_b: float | None = None
    macd_histogram: float | None = None
    macd_hist_declining: bool = False
    volume_ratio: float | None = None
    price_vs_sma200: float | None = None
    atr_14: float | None = None
    pe_ratio: float | None = None
    current_price: float = 0.0
    short_score: float = 0.0
    signal_breakdown: dict[str, float] = Field(default_factory=dict)


class StrategyMemo(BaseModel):
    """Weekly strategy review output."""
    period_start: datetime = Field(default_factory=datetime.now)
    period_end: datetime = Field(default_factory=datetime.now)
    total_return_pct: float = 0.0
    win_rate: float = 0.0
    best_trade: str = ""
    worst_trade: str = ""
    lessons: list[str] = Field(default_factory=list)
    parameter_changes: dict[str, Any] = Field(default_factory=dict)
    next_week_focus: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.now)


# --- Temporal Momentum Arbitrage Models ---

class MomentumSignal(BaseModel):
    """Real-time spot price momentum signal from Binance."""
    symbol: str                       # "BTC", "ETH", "SOL"
    current_price: float
    change_1m_pct: float              # (current - 1m_ago) / 1m_ago
    change_3m_pct: float
    change_5m_pct: float
    velocity: float = 0.0             # second derivative of price (acceleration)
    rsi_fast: float | None = None     # RSI(3) on 10-second bars
    direction: str = "flat"           # "up", "down", "flat"
    strength: float = 0.0             # 0.0–1.0 composite momentum score
    timestamp: datetime = Field(default_factory=datetime.now)


class TemporalArbOpportunity(BaseModel):
    """A Polymarket binary crypto market that lags confirmed spot momentum."""
    condition_id: str
    token_id_yes: str
    token_id_no: str
    question: str
    market_yes_price: float           # Current Polymarket YES price
    market_no_price: float
    momentum_signal: MomentumSignal
    estimated_true_prob: float        # Our model's estimate of true YES probability
    edge_pct: float                   # |estimated_true_prob - market_price| for chosen side
    suggested_side: str               # "yes" or "no"
    minutes_to_expiry: float
    kelly_fraction: float
    suggested_size_usd: float
    timestamp: datetime = Field(default_factory=datetime.now)


class OrderBookFrontRunSignal(BaseModel):
    """Detected large incoming order in the CLOB order book."""
    token_id: str
    question: str
    current_best_ask: float
    large_order_size_usd: float       # Size of incoming order detected
    estimated_price_impact: float     # How much the large order will move price
    suggested_entry_price: float
    suggested_size_usd: float
    timestamp: datetime = Field(default_factory=datetime.now)
