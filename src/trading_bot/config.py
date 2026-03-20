from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv


@dataclass
class LLMConfig:
    model: str = "claude-sonnet-4-5-20250929"
    strategist_model: str = "claude-opus-4-6"
    max_tokens: int = 4096


@dataclass
class RiskConfig:
    max_position_pct: float = 0.10
    max_total_exposure_pct: float = 0.80
    daily_loss_limit_pct: float = 0.03
    min_confidence: float = 0.60
    max_trades_per_day: int = 10


@dataclass
class AlpacaConfig:
    api_key: str = ""
    secret_key: str = ""
    paper: bool = True
    data_feed: str = "iex"


@dataclass
class PolymarketConfig:
    private_key: str = ""
    api_key: str = ""
    api_secret: str = ""
    api_passphrase: str = ""
    paper: bool = True
    paper_balance: float = 10_000.0
    ws_enabled: bool = False      # Enable real-time WebSocket price feed
    ws_top_markets: int = 200     # Subscribe to top N markets by volume
    ws_price_ttl_seconds: int = 5  # Cache expiry for WS prices


@dataclass
class StocksConfig:
    default_period: str = "3mo"
    watchlist: list[str] = field(default_factory=lambda: ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "SPY"])


@dataclass
class RunConfig:
    interval_minutes: int = 30
    auto_execute: bool = False


@dataclass
class ArbitrageConfig:
    min_edge_pct: float = 0.02
    fee_estimate_pct: float = 0.01
    max_events_to_scan: int = 200
    min_outcomes: int = 2
    max_outcomes: int = 20
    max_size_per_leg_usd: float = 500.0
    min_days_to_resolution: int = 0   # 0 = no minimum
    max_days_to_resolution: int = 0   # 0 = no maximum (set >0 to filter)


@dataclass
class WeatherArbConfig:
    """Weather forecast arbitrage: NOAA data vs Polymarket weather markets."""
    enabled: bool = True
    scan_interval_minutes: int = 30
    min_edge_pct: float = 0.08         # 8% edge between NOAA and market price
    max_days_to_resolution: int = 7    # Only trade markets expiring within 7 days
    min_days_to_resolution: int = 1    # Avoid markets expiring today
    max_size_usd: float = 100.0        # Max position per market
    max_total_exposure_usd: float = 500.0
    min_volume_usd: float = 1000.0     # Minimum market volume ($1K liquidity)
    cities: list[str] = field(default_factory=lambda: [
        "new york", "los angeles", "chicago", "houston", "phoenix",
        "seattle", "miami", "boston", "dallas", "denver",
        "san francisco", "atlanta", "washington dc",
    ])


@dataclass
class CrossMarketConfig:
    min_edge_pct: float = 0.03
    max_markets_per_batch: int = 20
    max_pairs_to_analyze: int = 50
    max_size_usd: float = 300.0


@dataclass
class ProbabilityEdgeConfig:
    min_edge_pct: float = 0.10
    kelly_fraction_cap: float = 0.25
    max_size_usd: float = 500.0
    track_accuracy: bool = True
    accuracy_log_file: str = "prediction_log.json"


@dataclass
class StockScorerConfig:
    technical_weight: float = 0.35
    fundamental_weight: float = 0.35
    sentiment_weight: float = 0.30
    min_composite_score: float = 0.3
    max_composite_score: float = -0.3


@dataclass
class MonitorConfig:
    stock_watchlist_interval_minutes: int = 30
    arb_scan_interval_minutes: int = 5
    probability_rescan_interval_minutes: int = 60
    cross_market_interval_minutes: int = 15
    adaptation_enabled: bool = True
    adaptation_lookback_trades: int = 20
    adaptation_loss_threshold: float = -0.05
    adaptation_win_threshold: float = 0.05
    adaptation_scale_step: float = 0.1
    adaptation_min_scale: float = 0.2
    adaptation_max_scale: float = 2.0


@dataclass
class ResearchAgentConfig:
    scan_interval_minutes: int = 240
    max_candidates: int = 20
    max_positions: int = 10
    max_single_position_pct: float = 0.15
    min_cash_reserve_pct: float = 0.20
    rebalance_drift_threshold: float = 0.05
    min_research_score: float = 5.0
    strategy_review_day: str = "sunday"
    enabled: bool = True


@dataclass
class KalshiConfig:
    api_key_id: str = ""
    private_key: str = ""
    demo: bool = True
    scan_interval_minutes: int = 45
    max_events_to_scan: int = 100
    min_edge_pct: float = 0.08
    kelly_fraction_cap: float = 0.20
    max_size_usd: float = 200.0
    max_total_exposure_usd: float = 2000.0
    max_positions: int = 15
    categories: list[str] = field(default_factory=lambda: [
        "politics", "economics", "science", "climate", "finance",
    ])
    max_days_until_close: int = 90  # Only trade markets closing within N days
    enabled: bool = True


@dataclass
class KalshiArbConfig:
    scan_interval_minutes: int = 10
    min_edge_pct: float = 0.03        # 3% net edge after fees
    fee_estimate_pct: float = 0.01    # 1% per leg
    max_events_to_scan: int = 200
    min_markets: int = 3              # Min legs for a MECE arb event
    max_markets: int = 15             # Skip events with too many buckets
    max_size_per_leg_usd: float = 50.0
    max_total_exposure_usd: float = 300.0
    enabled: bool = True


@dataclass
class ShortConfig:
    enabled: bool = True
    scan_interval_minutes: int = 60
    watchlist: list[str] = field(default_factory=list)  # empty = broad market scan
    min_short_score: float = -0.4
    max_short_exposure_pct: float = 0.30
    max_single_short_pct: float = 0.05
    risk_per_trade_pct: float = 0.005
    stop_atr_multiplier: float = 2.5
    proposal_expiry_hours: int = 24
    broad_market_scan: bool = True     # scan full market, not just watchlist
    prefilter_rsi_min: float = 65.0    # pre-filter: RSI(14) above this
    prefilter_near_high_pct: float = 0.95  # pre-filter: price > X% of 52w high
    max_prefilter_candidates: int = 40 # max candidates after pre-filter


@dataclass
class DrawdownAccumulationConfig:
    enabled: bool = True
    scan_interval_minutes: int = 60
    watchlist: list[str] = field(default_factory=lambda: ["TQQQ", "SOXL", "UPRO"])
    normal_buy_usd: float = 300.0           # DCA buy in normal conditions
    drawdown_buy_usd: float = 1500.0        # Aggressive buy during drawdowns
    drawdown_threshold_pct: float = 25.0     # Drawdown % to trigger aggressive buys
    min_days_between_buys: int = 7           # Cooldown: normal buys
    min_days_between_drawdown_buys: int = 5  # Cooldown: drawdown buys
    drawdown_lookback_days: int = 252        # Period for max drawdown calculation
    profit_take_pct: float = 50.0            # Sell partial when up this %
    profit_take_fraction: float = 0.25       # Sell this fraction on profit-take
    max_portfolio_pct: float = 0.30          # Max % of portfolio in this strategy


@dataclass
class RegimeConfig:
    """Configuration for the OU-based market regime classifier."""
    enabled: bool = True
    scan_interval_minutes: int = 60
    lookback_bars: int = 200            # Daily bars fetched (~6.5 months)
    autocorr_window: int = 60           # Bars used for lag-1 autocorrelation
    vol_window: int = 30                # Bars per rolling realized-vol estimate
    trend_threshold: float = 0.08       # Min |ρ| to declare trending/mean-reverting
    vol_high_pct: float = 0.75          # Vol-percentile threshold for HIGH_VOLATILITY
    vol_low_pct: float = 0.25           # Vol-percentile threshold for LOW_VOLATILITY
    # Empty list → falls back to crypto.watchlist
    symbols: list[str] = field(default_factory=list)


@dataclass
class CryptoConfig:
    scan_interval_minutes: int = 15
    watchlist: list[str] = field(default_factory=lambda: [
        "BTC/USD", "ETH/USD", "SOL/USD", "AVAX/USD", "LINK/USD",
    ])
    bar_timeframe: str = "15Min"
    lookback_bars: int = 100
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
    bb_period: int = 20
    bb_std: float = 2.0
    min_signal_score: float = 0.6
    max_position_pct: float = 0.08
    max_total_exposure_pct: float = 0.50
    max_size_usd: float = 1000.0
    llm_confirmation_enabled: bool = True
    enabled: bool = True


@dataclass
class PositionGuardConfig:
    enabled: bool = True
    scan_interval_minutes: int = 5
    stop_loss_pct: float = 8.0          # Sell if position down X%
    trailing_stop_pct: float = 12.0     # Trailing stop from peak
    take_profit_pct: float = 25.0       # Sell if position up X%
    partial_take_profit: bool = True    # Sell partial at TP instead of full
    partial_take_fraction: float = 0.50 # Fraction to sell at TP
    exclude_symbols: list[str] = field(default_factory=list)
    enable_for_shorts: bool = True


@dataclass
class TelegramConfig:
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""
    notify_trades: bool = True
    notify_errors: bool = True
    notify_stop_loss: bool = True
    daily_summary: bool = True
    daily_summary_hour: int = 17


@dataclass
class AuthConfig:
    username: str = ""
    password: str = ""


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8000
    db_path: str = "trading_bot.db"
    static_dir: str = "frontend/dist"


@dataclass
class TemporalMomentumConfig:
    """Temporal momentum arbitrage: Binance spot price lag vs Polymarket binary crypto markets."""
    enabled: bool = True
    scan_interval_seconds: int = 2
    binance_symbols: list[str] = field(default_factory=lambda: ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    price_history_seconds: int = 360          # 6 minutes of rolling price history
    # Momentum thresholds
    min_price_change_1m_pct: float = 0.003    # 0.3% in 1 minute to trigger signal
    momentum_strength_threshold: float = 0.65  # 0.0–1.0 composite score to enter
    # Market matching
    market_refresh_interval_seconds: int = 60  # How often to re-fetch active markets
    min_volume_usd: float = 5_000.0
    max_minutes_to_expiry: float = 20.0        # Only trade markets expiring within 20 min
    min_minutes_to_expiry: float = 2.0         # Not too close to expiry
    # Edge / execution
    min_edge_pct: float = 0.15                 # e.g. market at 50%, we think 65%+ → trade
    max_edge_pct: float = 0.48                 # Avoid near-certain markets (illiquid)
    kelly_fraction_cap: float = 0.25
    max_size_usd: float = 500.0
    max_total_exposure_usd: float = 3_000.0
    # Probability calibration
    prob_full_strength: float = 0.85           # Estimated true prob at max momentum strength
    # Order-book front-running
    frontrun_enabled: bool = True
    frontrun_min_order_size_usd: float = 10_000.0
    frontrun_max_size_usd: float = 200.0
    paper: bool = True


@dataclass
class CrossPlatformArbConfig:
    """Cross-platform arbitrage: Polymarket ↔ Kalshi price spread detection."""
    enabled: bool = True
    scan_interval_minutes: int = 2        # Scan every 2 minutes
    min_net_edge_pct: float = 0.02        # 2% net after fees
    min_volume_usd: float = 10_000.0      # Only trade high-volume markets
    max_size_per_leg_usd: float = 200.0
    max_total_exposure_usd: float = 2_000.0
    fuzzy_match_threshold: float = 0.75   # Market name similarity score
    market_cache_ttl_seconds: int = 3600  # Re-match markets hourly
    min_days_to_resolution: int = 1       # Avoid immediately expiring markets
    max_days_to_resolution: int = 60      # Avoid far-future markets (capital lockup)
    fee_estimate_poly_pct: float = 0.0    # Polymarket maker fee (0% by default)
    fee_estimate_kalshi_pct: float = 0.02 # Kalshi fee estimate (~2% at 50% probability)


@dataclass
class StrategiesConfig:
    arbitrage: ArbitrageConfig = field(default_factory=ArbitrageConfig)
    cross_market: CrossMarketConfig = field(default_factory=CrossMarketConfig)
    probability_edge: ProbabilityEdgeConfig = field(default_factory=ProbabilityEdgeConfig)


@dataclass
class Config:
    mode: str = "paper"
    llm: LLMConfig = field(default_factory=LLMConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    alpaca: AlpacaConfig = field(default_factory=AlpacaConfig)
    polymarket: PolymarketConfig = field(default_factory=PolymarketConfig)
    stocks: StocksConfig = field(default_factory=StocksConfig)
    run: RunConfig = field(default_factory=RunConfig)
    strategies: StrategiesConfig = field(default_factory=StrategiesConfig)
    stock_scorer: StockScorerConfig = field(default_factory=StockScorerConfig)
    monitors: MonitorConfig = field(default_factory=MonitorConfig)
    research_agent: ResearchAgentConfig = field(default_factory=ResearchAgentConfig)
    kalshi: KalshiConfig = field(default_factory=KalshiConfig)
    kalshi_arb: KalshiArbConfig = field(default_factory=KalshiArbConfig)
    crypto: CryptoConfig = field(default_factory=CryptoConfig)
    regime: RegimeConfig = field(default_factory=RegimeConfig)
    shorts: ShortConfig = field(default_factory=ShortConfig)
    drawdown_accumulation: DrawdownAccumulationConfig = field(default_factory=DrawdownAccumulationConfig)
    position_guard: PositionGuardConfig = field(default_factory=PositionGuardConfig)
    cross_platform_arb: CrossPlatformArbConfig = field(default_factory=CrossPlatformArbConfig)
    weather_arb: WeatherArbConfig = field(default_factory=WeatherArbConfig)
    temporal_momentum: TemporalMomentumConfig = field(default_factory=TemporalMomentumConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    anthropic_api_key: str = ""


def load_config(config_path: str | Path | None = None) -> Config:
    load_dotenv()

    cfg = Config()

    # Load YAML config if it exists
    if config_path is None:
        config_path = Path("config.yaml")
    else:
        config_path = Path(config_path)

    if config_path.exists():
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}
        _apply_yaml(cfg, raw)

    # Override with environment variables (secrets)
    cfg.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
    cfg.alpaca.api_key = os.getenv("ALPACA_API_KEY", "")
    cfg.alpaca.secret_key = os.getenv("ALPACA_SECRET_KEY", "") or os.getenv("ALPACA_API_SECRET", "")
    cfg.polymarket.private_key = os.getenv("POLYMARKET_PRIVATE_KEY", "")
    cfg.polymarket.api_key = os.getenv("POLYMARKET_API_KEY", "")
    cfg.polymarket.api_secret = os.getenv("POLYMARKET_API_SECRET", "")
    cfg.polymarket.api_passphrase = os.getenv("POLYMARKET_API_PASSPHRASE", "")

    cfg.kalshi.api_key_id = os.getenv("KALSHI_API_KEY_ID", "")
    cfg.kalshi.private_key = os.getenv("KALSHI_PRIVATE_KEY", "")
    if os.getenv("KALSHI_DEMO") is not None:
        cfg.kalshi.demo = os.getenv("KALSHI_DEMO", "true").lower() in ("true", "1", "yes")

    cfg.telegram.bot_token = os.getenv("TELEGRAM_BOT_TOKEN", cfg.telegram.bot_token)
    cfg.telegram.chat_id = os.getenv("TELEGRAM_CHAT_ID", cfg.telegram.chat_id)
    if cfg.telegram.bot_token and cfg.telegram.chat_id:
        cfg.telegram.enabled = True

    cfg.auth.username = os.getenv("AUTH_USERNAME", "")
    cfg.auth.password = os.getenv("AUTH_PASSWORD", "")

    if os.getenv("DB_PATH"):
        cfg.server.db_path = os.getenv("DB_PATH", cfg.server.db_path)

    return cfg


def _apply_yaml(cfg: Config, raw: dict) -> None:
    if "mode" in raw:
        cfg.mode = raw["mode"]

    if "llm" in raw:
        for k, v in raw["llm"].items():
            if hasattr(cfg.llm, k):
                setattr(cfg.llm, k, v)

    if "risk" in raw:
        for k, v in raw["risk"].items():
            if hasattr(cfg.risk, k):
                setattr(cfg.risk, k, v)

    if "alpaca" in raw:
        for k, v in raw["alpaca"].items():
            if hasattr(cfg.alpaca, k):
                setattr(cfg.alpaca, k, v)

    if "polymarket" in raw:
        for k, v in raw["polymarket"].items():
            if hasattr(cfg.polymarket, k):
                setattr(cfg.polymarket, k, v)

    if "stocks" in raw:
        for k, v in raw["stocks"].items():
            if hasattr(cfg.stocks, k):
                setattr(cfg.stocks, k, v)

    if "run" in raw:
        for k, v in raw["run"].items():
            if hasattr(cfg.run, k):
                setattr(cfg.run, k, v)

    if "strategies" in raw:
        s = raw["strategies"]
        if "arbitrage" in s:
            for k, v in s["arbitrage"].items():
                if hasattr(cfg.strategies.arbitrage, k):
                    setattr(cfg.strategies.arbitrage, k, v)
        if "cross_market" in s:
            for k, v in s["cross_market"].items():
                if hasattr(cfg.strategies.cross_market, k):
                    setattr(cfg.strategies.cross_market, k, v)
        if "probability_edge" in s:
            for k, v in s["probability_edge"].items():
                if hasattr(cfg.strategies.probability_edge, k):
                    setattr(cfg.strategies.probability_edge, k, v)

    if "stock_scorer" in raw:
        for k, v in raw["stock_scorer"].items():
            if hasattr(cfg.stock_scorer, k):
                setattr(cfg.stock_scorer, k, v)

    if "monitors" in raw:
        for k, v in raw["monitors"].items():
            if hasattr(cfg.monitors, k):
                setattr(cfg.monitors, k, v)

    if "research_agent" in raw:
        for k, v in raw["research_agent"].items():
            if hasattr(cfg.research_agent, k):
                setattr(cfg.research_agent, k, v)

    if "kalshi" in raw:
        for k, v in raw["kalshi"].items():
            if hasattr(cfg.kalshi, k):
                setattr(cfg.kalshi, k, v)

    if "kalshi_arb" in raw:
        for k, v in raw["kalshi_arb"].items():
            if hasattr(cfg.kalshi_arb, k):
                setattr(cfg.kalshi_arb, k, v)

    if "crypto" in raw:
        for k, v in raw["crypto"].items():
            if hasattr(cfg.crypto, k):
                setattr(cfg.crypto, k, v)

    if "regime" in raw:
        for k, v in raw["regime"].items():
            if hasattr(cfg.regime, k):
                setattr(cfg.regime, k, v)

    if "shorts" in raw:
        for k, v in raw["shorts"].items():
            if hasattr(cfg.shorts, k):
                setattr(cfg.shorts, k, v)

    if "drawdown_accumulation" in raw:
        for k, v in raw["drawdown_accumulation"].items():
            if hasattr(cfg.drawdown_accumulation, k):
                setattr(cfg.drawdown_accumulation, k, v)

    if "position_guard" in raw:
        for k, v in raw["position_guard"].items():
            if hasattr(cfg.position_guard, k):
                setattr(cfg.position_guard, k, v)

    if "cross_platform_arb" in raw:
        for k, v in raw["cross_platform_arb"].items():
            if hasattr(cfg.cross_platform_arb, k):
                setattr(cfg.cross_platform_arb, k, v)

    if "weather_arb" in raw:
        for k, v in raw["weather_arb"].items():
            if hasattr(cfg.weather_arb, k):
                setattr(cfg.weather_arb, k, v)

    if "temporal_momentum" in raw:
        for k, v in raw["temporal_momentum"].items():
            if hasattr(cfg.temporal_momentum, k):
                setattr(cfg.temporal_momentum, k, v)

    if "telegram" in raw:
        for k, v in raw["telegram"].items():
            if hasattr(cfg.telegram, k):
                setattr(cfg.telegram, k, v)

    if "auth" in raw:
        for k, v in raw["auth"].items():
            if hasattr(cfg.auth, k):
                setattr(cfg.auth, k, v)

    if "server" in raw:
        for k, v in raw["server"].items():
            if hasattr(cfg.server, k):
                setattr(cfg.server, k, v)
