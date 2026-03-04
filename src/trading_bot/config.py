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
    enabled: bool = True


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
    crypto: CryptoConfig = field(default_factory=CryptoConfig)
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

    if "crypto" in raw:
        for k, v in raw["crypto"].items():
            if hasattr(cfg.crypto, k):
                setattr(cfg.crypto, k, v)

    if "auth" in raw:
        for k, v in raw["auth"].items():
            if hasattr(cfg.auth, k):
                setattr(cfg.auth, k, v)

    if "server" in raw:
        for k, v in raw["server"].items():
            if hasattr(cfg.server, k):
                setattr(cfg.server, k, v)
