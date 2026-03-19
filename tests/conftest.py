"""Shared pytest fixtures for the trading-bot test suite."""

from __future__ import annotations

import pytest
import pytest_asyncio

from trading_bot.config import Config, RiskConfig
from trading_bot.db.database import Database
from trading_bot.db.repository import Repository
from trading_bot.models import (
    OrderResult,
    OrderStatus,
    Platform,
    PortfolioSummary,
    Position,
    Side,
)


# ---------------------------------------------------------------------------
# Config fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def minimal_config() -> Config:
    """Minimal Config suitable for unit tests (no real API keys needed)."""
    return Config()


@pytest.fixture
def risk_config() -> RiskConfig:
    return RiskConfig(
        max_position_pct=0.10,
        max_total_exposure_pct=0.80,
        daily_loss_limit_pct=0.03,
        min_confidence=0.60,
        max_trades_per_day=10,
    )


# ---------------------------------------------------------------------------
# Portfolio fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def portfolio_10k() -> PortfolioSummary:
    return PortfolioSummary(
        cash=10_000.0,
        equity=10_000.0,
        positions=[],
        daily_pnl=0.0,
        platform=Platform.ALPACA,
    )


@pytest.fixture
def portfolio_with_positions() -> PortfolioSummary:
    positions = [
        Position(
            symbol="AAPL",
            quantity=10.0,
            avg_entry_price=150.0,
            current_price=155.0,
            market_value=1_550.0,
            unrealized_pnl=50.0,
            platform=Platform.ALPACA,
        ),
        Position(
            symbol="MSFT",
            quantity=5.0,
            avg_entry_price=300.0,
            current_price=310.0,
            market_value=1_550.0,
            unrealized_pnl=50.0,
            platform=Platform.ALPACA,
        ),
    ]
    return PortfolioSummary(
        cash=5_000.0,
        equity=8_100.0,
        positions=positions,
        daily_pnl=100.0,
        platform=Platform.ALPACA,
    )


# ---------------------------------------------------------------------------
# Database fixtures (async, in-memory)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def in_memory_db():
    db = Database(":memory:")
    await db.connect()
    yield db
    await db.close()


@pytest_asyncio.fixture
async def repo(in_memory_db):
    return Repository(in_memory_db)


# ---------------------------------------------------------------------------
# Mock broker fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def filled_order_result():
    """A pre-built filled OrderResult for mock broker returns."""
    return OrderResult(
        order_id="test-order-001",
        symbol="test-token",
        side=Side.BUY,
        quantity=10.0,
        status=OrderStatus.FILLED,
        filled_price=0.50,
        platform=Platform.POLYMARKET,
    )
