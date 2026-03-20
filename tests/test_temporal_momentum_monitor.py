"""Tests for TemporalMomentumMonitor and TemporalMomentumArbStrategy.find_opportunities()."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_bot.brokers.exchange_feed import BinanceExchangeFeed, PricePoint
from trading_bot.config import Config, TemporalMomentumConfig
from trading_bot.models import MomentumSignal, PortfolioSummary, Platform
from trading_bot.strategies.temporal_momentum_arb import TemporalMomentumArbStrategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cfg(**kwargs) -> TemporalMomentumConfig:
    cfg = TemporalMomentumConfig()
    for k, v in kwargs.items():
        setattr(cfg, k, v)
    return cfg


def _make_signal(direction: str = "up", strength: float = 0.80) -> MomentumSignal:
    return MomentumSignal(
        symbol="BTC",
        current_price=70_000.0,
        change_1m_pct=0.005 if direction == "up" else -0.005,
        change_3m_pct=0.008 if direction == "up" else -0.008,
        change_5m_pct=0.012 if direction == "up" else -0.012,
        velocity=0.001,
        direction=direction,
        strength=strength,
    )


def _make_market(
    symbol: str = "BTC",
    yes_price: float = 0.52,
    minutes_remaining: float = 10.0,
    volume: float = 20_000.0,
) -> dict:
    end_dt = datetime.now(timezone.utc) + timedelta(minutes=minutes_remaining)
    return {
        "condition_id": "cond_test",
        "token_id_yes": "tok_yes",
        "token_id_no": "tok_no",
        "question": f"Will {symbol} be higher in 15 min?",
        "end_date": end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "minutes_remaining": minutes_remaining,
        "symbol": symbol,
        "yes_price": yes_price,
        "no_price": round(1.0 - yes_price, 4),
        "volume": volume,
    }


def _make_poly_feed(yes_price: float | None = None, no_price: float | None = None):
    """Create a mock PolymarketWebSocketFeed."""
    feed = MagicMock()
    feed.get_price_sync.side_effect = lambda token_id: (
        yes_price if "yes" in token_id else (no_price or (1.0 - yes_price if yes_price else None))
    )
    feed._price_cache = {}
    return feed


# ---------------------------------------------------------------------------
# find_opportunities
# ---------------------------------------------------------------------------

class TestFindOpportunities:
    def test_returns_empty_when_no_signal(self):
        cfg = _make_cfg()
        strategy = TemporalMomentumArbStrategy(cfg)
        poly_feed = _make_poly_feed(yes_price=0.52)
        market = _make_market()
        opps = strategy.find_opportunities({}, [market], poly_feed, 10_000.0)
        assert opps == []

    def test_flat_direction_excluded(self):
        cfg = _make_cfg()
        strategy = TemporalMomentumArbStrategy(cfg)
        poly_feed = _make_poly_feed(yes_price=0.52)
        signal = _make_signal(direction="flat")
        market = _make_market()
        opps = strategy.find_opportunities({"BTC": signal}, [market], poly_feed, 10_000.0)
        assert opps == []

    def test_weak_strength_excluded(self):
        cfg = _make_cfg(momentum_strength_threshold=0.80)
        strategy = TemporalMomentumArbStrategy(cfg)
        poly_feed = _make_poly_feed(yes_price=0.52)
        signal = _make_signal(direction="up", strength=0.50)  # below threshold
        market = _make_market()
        opps = strategy.find_opportunities({"BTC": signal}, [market], poly_feed, 10_000.0)
        assert opps == []

    def test_expired_market_excluded(self):
        cfg = _make_cfg(min_minutes_to_expiry=2.0)
        strategy = TemporalMomentumArbStrategy(cfg)
        poly_feed = _make_poly_feed(yes_price=0.52)
        signal = _make_signal(direction="up", strength=0.90)
        market = _make_market(minutes_remaining=0.5)  # expires in 30s
        opps = strategy.find_opportunities({"BTC": signal}, [market], poly_feed, 10_000.0)
        assert opps == []

    def test_already_priced_in_excluded(self):
        cfg = _make_cfg()
        strategy = TemporalMomentumArbStrategy(cfg)
        poly_feed = _make_poly_feed(yes_price=0.95)  # already near certain
        signal = _make_signal(direction="up", strength=0.90)
        market = _make_market(yes_price=0.95)
        opps = strategy.find_opportunities({"BTC": signal}, [market], poly_feed, 10_000.0)
        assert opps == []

    def test_below_min_edge_excluded(self):
        cfg = _make_cfg(min_edge_pct=0.30)  # require very large edge
        strategy = TemporalMomentumArbStrategy(cfg)
        poly_feed = _make_poly_feed(yes_price=0.52)
        signal = _make_signal(direction="up", strength=0.70)  # moderate signal
        market = _make_market(yes_price=0.52)
        opps = strategy.find_opportunities({"BTC": signal}, [market], poly_feed, 10_000.0)
        assert opps == []

    def test_valid_opportunity_found(self):
        cfg = _make_cfg(min_edge_pct=0.10, momentum_strength_threshold=0.65)
        strategy = TemporalMomentumArbStrategy(cfg)
        poly_feed = _make_poly_feed(yes_price=0.50)
        signal = _make_signal(direction="up", strength=0.90)  # strong signal
        market = _make_market(yes_price=0.50)
        opps = strategy.find_opportunities({"BTC": signal}, [market], poly_feed, 10_000.0)
        assert len(opps) >= 1
        opp = opps[0]
        assert opp.suggested_side in ("yes", "no")
        assert opp.edge_pct >= 0.10
        assert opp.suggested_size_usd > 0

    def test_sorted_by_edge_descending(self):
        cfg = _make_cfg(min_edge_pct=0.05, momentum_strength_threshold=0.65)
        strategy = TemporalMomentumArbStrategy(cfg)
        poly_feed = _make_poly_feed(yes_price=0.50)
        signal_strong = _make_signal(direction="up", strength=0.95)
        signal_moderate = _make_signal(direction="up", strength=0.70)

        market_btc = _make_market("BTC", yes_price=0.50)
        market_eth = _make_market("ETH", yes_price=0.50)

        opps = strategy.find_opportunities(
            {"BTC": signal_strong, "ETH": signal_moderate},
            [market_btc, market_eth],
            poly_feed,
            10_000.0,
        )
        if len(opps) > 1:
            for i in range(len(opps) - 1):
                assert opps[i].edge_pct >= opps[i + 1].edge_pct

    def test_max_exposure_respected(self):
        """Kelly sizing should never exceed max_size_usd."""
        cfg = _make_cfg(max_size_usd=100.0, min_edge_pct=0.05, momentum_strength_threshold=0.65)
        strategy = TemporalMomentumArbStrategy(cfg)
        poly_feed = _make_poly_feed(yes_price=0.50)
        signal = _make_signal(direction="up", strength=0.90)
        market = _make_market(yes_price=0.50)
        opps = strategy.find_opportunities({"BTC": signal}, [market], poly_feed, 10_000.0)
        for opp in opps:
            assert opp.suggested_size_usd <= 100.0


# ---------------------------------------------------------------------------
# Monitor registration
# ---------------------------------------------------------------------------

class TestMonitorRegistration:
    def test_temporal_momentum_in_monitor_types(self):
        from trading_bot.monitors.manager import MONITOR_TYPES
        from trading_bot.monitors.temporal_momentum_monitor import TemporalMomentumMonitor
        assert "temporal_momentum" in MONITOR_TYPES
        assert MONITOR_TYPES["temporal_momentum"] is TemporalMomentumMonitor


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class TestConfig:
    def test_temporal_momentum_config_defaults(self):
        cfg = Config()
        assert cfg.temporal_momentum.scan_interval_seconds == 2
        assert cfg.temporal_momentum.min_edge_pct == 0.15
        assert cfg.temporal_momentum.paper is True

    def test_config_yaml_override(self):
        from trading_bot.config import _apply_yaml
        cfg = Config()
        _apply_yaml(cfg, {"temporal_momentum": {"min_edge_pct": 0.20, "max_size_usd": 300.0}})
        assert cfg.temporal_momentum.min_edge_pct == pytest.approx(0.20)
        assert cfg.temporal_momentum.max_size_usd == pytest.approx(300.0)


# ---------------------------------------------------------------------------
# Monitor: run_cycle with no broker
# ---------------------------------------------------------------------------

class TestMonitorRunCycle:
    @pytest.mark.asyncio
    async def test_run_cycle_no_broker(self):
        """run_cycle should exit cleanly if no polymarket broker configured."""
        from trading_bot.monitors.temporal_momentum_monitor import TemporalMomentumMonitor
        from trading_bot.monitors.base import EventBus

        repo = AsyncMock()
        repo.update_monitor_last_run = AsyncMock()
        repo.update_monitor_status = AsyncMock()
        repo.update_monitor_error = AsyncMock()
        repo.get_monitor_state = AsyncMock(return_value=None)
        repo.get_all_monitor_states = AsyncMock(return_value=[])

        monitor = TemporalMomentumMonitor(
            monitor_id="test_1",
            config=Config(),
            repo=repo,
            event_bus=EventBus(),
            brokers={},  # no polymarket broker
            risk_manager=MagicMock(),
        )
        monitor._binance_feed = MagicMock()
        monitor._poly_ws = MagicMock()
        monitor._active_markets = [_make_market()]

        # Should return without raising
        await monitor.run_cycle()

    @pytest.mark.asyncio
    async def test_run_cycle_no_markets(self):
        """run_cycle should exit cleanly when no active markets."""
        from trading_bot.monitors.temporal_momentum_monitor import TemporalMomentumMonitor
        from trading_bot.monitors.base import EventBus

        repo = AsyncMock()
        repo.update_monitor_last_run = AsyncMock()
        repo.update_monitor_status = AsyncMock()

        monitor = TemporalMomentumMonitor(
            monitor_id="test_2",
            config=Config(),
            repo=repo,
            event_bus=EventBus(),
            brokers={"polymarket": MagicMock()},
            risk_manager=MagicMock(),
        )
        monitor._binance_feed = MagicMock()
        monitor._poly_ws = MagicMock()
        monitor._active_markets = []  # empty

        await monitor.run_cycle()  # should return immediately

    @pytest.mark.asyncio
    async def test_run_cycle_no_feed(self):
        """run_cycle should exit cleanly when feeds not initialised."""
        from trading_bot.monitors.temporal_momentum_monitor import TemporalMomentumMonitor
        from trading_bot.monitors.base import EventBus

        repo = AsyncMock()
        repo.update_monitor_last_run = AsyncMock()
        repo.update_monitor_status = AsyncMock()

        monitor = TemporalMomentumMonitor(
            monitor_id="test_3",
            config=Config(),
            repo=repo,
            event_bus=EventBus(),
            brokers={"polymarket": MagicMock()},
            risk_manager=MagicMock(),
        )
        # feeds not set (None)
        await monitor.run_cycle()
