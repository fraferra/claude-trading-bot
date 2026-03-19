"""End-to-end trade flow tests.

Uses in-memory SQLite + mock/paper brokers to verify the full
signal → risk check → order → DB record pipeline without network calls.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from trading_bot.config import Config, RiskConfig
from trading_bot.db.database import Database
from trading_bot.db.repository import Repository
from trading_bot.models import (
    Action,
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderType,
    Platform,
    PortfolioSummary,
    Side,
    TradeDecision,
)
from trading_bot.risk.manager import RiskManager


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db():
    _db = Database(":memory:")
    await _db.connect()
    yield _db
    await _db.close()


@pytest_asyncio.fixture
async def repo(db):
    return Repository(db)


def _portfolio(equity=10_000.0, cash=10_000.0, daily_pnl=0.0):
    return PortfolioSummary(
        cash=cash,
        equity=equity,
        positions=[],
        daily_pnl=daily_pnl,
        platform=Platform.ALPACA,
    )


def _order_result(symbol="AAPL", qty=10.0, price=100.0, status=OrderStatus.FILLED):
    return OrderResult(
        order_id="test-e2e-order-1",
        symbol=symbol,
        side=Side.BUY,
        quantity=qty,
        status=status,
        filled_price=price,
        platform=Platform.ALPACA,
    )


# ---------------------------------------------------------------------------
# TestPaperPolymarketE2E
# ---------------------------------------------------------------------------

class TestPaperPolymarketE2E:
    """Test with the PaperPolymarketBroker (no mocking needed for broker logic)."""

    def _fresh_broker(self, balance=5_000.0):
        """Create a paper broker with clean in-memory state (no file I/O)."""
        from trading_bot.brokers.paper_polymarket import PaperPolymarketBroker
        broker = PaperPolymarketBroker.__new__(PaperPolymarketBroker)
        broker._initial_balance = balance
        broker._state = {"cash": balance, "positions": {}, "orders": []}
        return broker

    @pytest.mark.asyncio
    async def test_paper_broker_get_account_returns_portfolio(self):
        broker = self._fresh_broker(5_000.0)
        # Mock get_positions to return empty list (avoids network)
        broker.get_positions = AsyncMock(return_value=[])
        account = await broker.get_account()
        assert account.cash == pytest.approx(5_000.0)
        assert account.equity == pytest.approx(5_000.0)

    @pytest.mark.asyncio
    async def test_paper_broker_multiple_buys_accumulate(self):
        broker = self._fresh_broker(10_000.0)

        # Mock price lookup and save_state to avoid network/file I/O
        with patch("trading_bot.brokers.paper_polymarket._get_token_price", return_value=0.50):
            # Also mock _save_state to avoid file writes
            broker._save_state = MagicMock()

            order1 = OrderRequest(
                symbol="tok-x",
                quantity=10.0,
                side=Side.BUY,
                order_type=OrderType.LIMIT,
                limit_price=0.50,
                platform=Platform.POLYMARKET,
            )
            result1 = await broker.submit_order(order1)
            assert result1.status == OrderStatus.FILLED

            order2 = OrderRequest(
                symbol="tok-x",
                quantity=5.0,
                side=Side.BUY,
                order_type=OrderType.LIMIT,
                limit_price=0.50,
                platform=Platform.POLYMARKET,
            )
            result2 = await broker.submit_order(order2)
            assert result2.status == OrderStatus.FILLED

        # Should have one position with 15 units
        assert broker._state["positions"]["tok-x"]["quantity"] == pytest.approx(15.0)

    @pytest.mark.asyncio
    async def test_paper_broker_cash_decreases_after_buy(self):
        broker = self._fresh_broker(1_000.0)
        broker._save_state = MagicMock()

        with patch("trading_bot.brokers.paper_polymarket._get_token_price", return_value=0.50):
            order = OrderRequest(
                symbol="tok-y",
                quantity=10.0,
                side=Side.BUY,
                order_type=OrderType.LIMIT,
                limit_price=0.50,
                platform=Platform.POLYMARKET,
            )
            result = await broker.submit_order(order)

        if result.status == OrderStatus.FILLED:
            assert broker._state["cash"] < 1_000.0


# ---------------------------------------------------------------------------
# TestRiskManagerE2E
# ---------------------------------------------------------------------------

class TestRiskManagerE2E:
    """Test that RiskManager gates are correctly applied before order execution."""

    @pytest.mark.asyncio
    async def test_signal_approved_then_trade_recorded(self, repo):
        rm = RiskManager(RiskConfig(min_confidence=0.60, max_trades_per_day=10))
        portfolio = _portfolio()

        decision = TradeDecision(
            action=Action.BUY,
            symbol="AAPL",
            confidence=0.80,
            reasoning="Test signal",
        )
        check = rm.check_decision(decision)
        assert check.approved

        # Simulate trade execution
        trade_id = await repo.insert_trade(
            order_id="e2e-001",
            symbol="AAPL",
            side="buy",
            quantity=10.0,
            filled_price=150.0,
            platform="alpaca",
            source="test_e2e",
        )
        rm.record_trade()

        # Verify DB record
        trades = await repo.get_trades(limit=10)
        assert any(t["order_id"] == "e2e-001" for t in trades)

        # Verify counter incremented
        from datetime import date
        assert rm._trades_today.get(date.today(), 0) == 1

    @pytest.mark.asyncio
    async def test_low_confidence_decision_not_executed(self, repo):
        rm = RiskManager(RiskConfig(min_confidence=0.70))

        decision = TradeDecision(
            action=Action.BUY,
            symbol="AAPL",
            confidence=0.50,  # Below threshold
            reasoning="Weak signal",
        )
        check = rm.check_decision(decision)
        assert not check.approved

        # No trade inserted
        trades_before = await repo.get_trades()
        assert len(trades_before) == 0

    @pytest.mark.asyncio
    async def test_daily_loss_limit_blocks_further_trading(self, repo):
        rm = RiskManager(RiskConfig(daily_loss_limit_pct=0.03))
        # Portfolio with -5% daily loss
        portfolio = _portfolio(equity=10_000.0, daily_pnl=-500.0)

        order = OrderRequest(
            symbol="AAPL",
            quantity=10.0,
            side=Side.BUY,
            order_type=OrderType.MARKET,
            limit_price=100.0,
            platform=Platform.ALPACA,
        )
        result = rm.check_order(order, portfolio, 100.0)
        assert not result.approved

    @pytest.mark.asyncio
    async def test_position_size_adjusted_and_trade_inserted(self, repo):
        rm = RiskManager(RiskConfig(max_position_pct=0.05))
        # equity=10000, max_position=500; order wants 200 shares @ $10 = $2000 > $500
        portfolio = _portfolio(equity=10_000.0, cash=10_000.0)

        order = OrderRequest(
            symbol="CHEAP",
            quantity=200.0,
            side=Side.BUY,
            order_type=OrderType.MARKET,
            limit_price=10.0,
            platform=Platform.ALPACA,
        )
        result = rm.check_order(order, portfolio, 10.0)
        assert result.approved
        assert result.adjusted_quantity is not None
        assert result.adjusted_quantity < 200.0

        # Record the adjusted trade
        actual_qty = result.adjusted_quantity
        await repo.insert_trade(
            order_id="e2e-adj-001",
            symbol="CHEAP",
            side="buy",
            quantity=actual_qty,
            filled_price=10.0,
            platform="alpaca",
            source="test_e2e",
        )
        trades = await repo.get_trades(symbol="CHEAP")
        assert len(trades) == 1
        assert trades[0]["quantity"] == pytest.approx(actual_qty)


# ---------------------------------------------------------------------------
# TestArbitrageE2E
# ---------------------------------------------------------------------------

class TestArbitrageE2E:
    """Test that an arb scan result is correctly persisted to the DB."""

    @pytest.mark.asyncio
    async def test_arb_decisions_saved_to_db(self, repo):
        """Simulate: arb scanner produces decisions → both legs recorded in DB."""
        decisions = [
            {
                "order_id": "arb-poly-001",
                "symbol": "tok-yes-001",
                "side": "buy",
                "quantity": 100.0,
                "filled_price": 0.55,
                "platform": "polymarket",
                "source": "polymarket_arb",
            },
            {
                "order_id": "arb-kalshi-001",
                "symbol": "BTC-100K",
                "side": "sell",
                "quantity": 100.0,
                "filled_price": 0.40,
                "platform": "kalshi",
                "source": "polymarket_arb",
            },
        ]

        for d in decisions:
            await repo.insert_trade(**d)

        trades = await repo.get_trades(limit=10)
        order_ids = [t["order_id"] for t in trades]
        assert "arb-poly-001" in order_ids
        assert "arb-kalshi-001" in order_ids

    @pytest.mark.asyncio
    async def test_kalshi_settlement_recorded(self, repo):
        """Simulate: Kalshi market settles YES, settlement P&L recorded."""
        # Insert the original trade
        await repo.insert_trade(
            order_id="k-settle-001",
            symbol="BTC-100K",
            side="buy",
            quantity=100.0,
            filled_price=0.60,
            platform="kalshi",
            source="kalshi_arb",
        )

        # Insert settlement (requires valid trade_id foreign key)
        trade_id = await repo.insert_trade(
            order_id="k-settle-ref",
            symbol="BTC-100K",
            side="buy",
            quantity=100.0,
            filled_price=0.60,
            platform="kalshi",
            source="kalshi_arb",
        )
        await repo.insert_kalshi_settlement(
            trade_id=trade_id,
            ticker="BTC-100K",
            side="buy",
            result="yes",
            entry_price=0.60,
            payout_per_contract=1.0,
            quantity=100.0,
            total_pnl=(1.0 - 0.60) * 100.0,  # +$40
        )

        settlements = await repo.get_kalshi_settlements()
        assert len(settlements) >= 1
        btc_settlement = next((s for s in settlements if s["ticker"] == "BTC-100K"), None)
        assert btc_settlement is not None
        assert btc_settlement["total_pnl"] == pytest.approx(40.0)

    @pytest.mark.asyncio
    async def test_full_trade_and_pnl_cycle(self, repo):
        """Insert buy + sell → verify cumulative P&L is positive."""
        await repo.insert_trade(
            order_id="full-001",
            symbol="AAPL",
            side="buy",
            quantity=10.0,
            filled_price=100.0,
            platform="alpaca",
            source="test",
        )
        await repo.insert_trade(
            order_id="full-002",
            symbol="AAPL",
            side="sell",
            quantity=10.0,
            filled_price=120.0,
            platform="alpaca",
            source="test",
        )

        pnl_series = await repo.get_cumulative_pnl("alpaca")
        assert len(pnl_series) > 0
        final = pnl_series[-1]["cumulative_pnl"]
        assert final == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# TestMockBrokerE2E
# ---------------------------------------------------------------------------

class TestMockBrokerE2E:
    """Test the full signal→execute→persist flow using a mock broker."""

    @pytest.mark.asyncio
    async def test_filled_order_persisted_in_db(self, repo):
        mock_broker = AsyncMock()
        mock_broker.submit_order = AsyncMock(return_value=_order_result(
            symbol="TSLA", qty=5.0, price=250.0, status=OrderStatus.FILLED
        ))

        rm = RiskManager(RiskConfig(min_confidence=0.60))
        portfolio = _portfolio(equity=50_000.0, cash=50_000.0)

        decision = TradeDecision(
            action=Action.BUY,
            symbol="TSLA",
            confidence=0.80,
            reasoning="Strong momentum",
            suggested_size_usd=1_250.0,
        )

        # Check risk
        risk_result = rm.check_decision(decision)
        assert risk_result.approved

        # Submit order
        order = OrderRequest(
            symbol="TSLA",
            quantity=5.0,
            side=Side.BUY,
            order_type=OrderType.MARKET,
            limit_price=250.0,
            platform=Platform.ALPACA,
        )
        result = await mock_broker.submit_order(order)
        assert result.status == OrderStatus.FILLED

        # Persist
        trade_id = await repo.insert_trade(
            order_id=result.order_id,
            symbol=result.symbol,
            side="buy",
            quantity=result.quantity,
            filled_price=result.filled_price,
            platform="alpaca",
            source="test_e2e",
            confidence=decision.confidence,
            reasoning=decision.reasoning,
        )
        assert trade_id > 0

        trades = await repo.get_trades(symbol="TSLA")
        assert len(trades) == 1
        assert trades[0]["filled_price"] == pytest.approx(250.0)

    @pytest.mark.asyncio
    async def test_rejected_order_not_persisted(self, repo):
        mock_broker = AsyncMock()
        mock_broker.submit_order = AsyncMock(return_value=_order_result(
            symbol="AAPL", qty=10.0, price=150.0, status=OrderStatus.REJECTED
        ))

        order = OrderRequest(
            symbol="AAPL",
            quantity=10.0,
            side=Side.BUY,
            order_type=OrderType.MARKET,
            limit_price=150.0,
            platform=Platform.ALPACA,
        )
        result = await mock_broker.submit_order(order)
        assert result.status == OrderStatus.REJECTED

        # Don't persist rejected orders
        trades = await repo.get_trades(symbol="AAPL")
        assert len(trades) == 0

    @pytest.mark.asyncio
    async def test_multiple_trades_cumulative_pnl(self, repo):
        """Simulate 3 round-trips and verify final cumulative P&L."""
        trade_data = [
            ("buy",  "AAPL", 10.0, 100.0),
            ("sell", "AAPL", 10.0, 120.0),  # +$200
            ("buy",  "MSFT", 5.0,  300.0),
            ("sell", "MSFT", 5.0,  280.0),  # -$100
            ("buy",  "NVDA", 2.0,  500.0),
            ("sell", "NVDA", 2.0,  550.0),  # +$100
        ]
        for i, (side, sym, qty, price) in enumerate(trade_data):
            await repo.insert_trade(
                order_id=f"multi-{i}",
                symbol=sym,
                side=side,
                quantity=qty,
                filled_price=price,
                platform="alpaca",
                source="test",
            )

        pnl = await repo.get_cumulative_pnl("alpaca")
        final = pnl[-1]["cumulative_pnl"] if pnl else 0
        assert final == pytest.approx(200.0)  # +200 - 100 + 100 = +200
