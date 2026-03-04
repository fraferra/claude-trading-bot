import pytest
from unittest.mock import AsyncMock, patch

from trading_bot.brokers.paper_polymarket import PaperPolymarketBroker
from trading_bot.models import OrderRequest, OrderStatus, OrderType, Platform, Side


@pytest.fixture
def broker(tmp_path, monkeypatch):
    """Create a fresh paper broker with state file in tmp dir."""
    monkeypatch.chdir(tmp_path)
    b = PaperPolymarketBroker(initial_balance=10000.0)
    return b


@pytest.fixture
def mock_market_data():
    """Mock get_polymarket_data to avoid real API calls."""
    from trading_bot.models import PolymarketData

    mock_data = PolymarketData(
        condition_id="test-market-123",
        question="Will it rain tomorrow?",
        yes_price=0.65,
        no_price=0.35,
        volume=50000.0,
        liquidity=10000.0,
    )
    with patch("trading_bot.brokers.paper_polymarket.get_polymarket_data", new_callable=AsyncMock) as mock:
        mock.return_value = mock_data
        yield mock


@pytest.mark.asyncio
async def test_initial_balance(broker):
    account = await broker.get_account()
    assert account.cash == 10000.0
    assert account.equity == 10000.0
    assert len(account.positions) == 0


@pytest.mark.asyncio
async def test_buy_order(broker, mock_market_data):
    order = OrderRequest(
        symbol="test-market-123",
        side=Side.BUY,
        quantity=100.0,
        order_type=OrderType.MARKET,
        platform=Platform.POLYMARKET,
    )
    result = await broker.submit_order(order)

    assert result.status == OrderStatus.FILLED
    assert result.filled_price == 0.65
    assert result.quantity == 100.0

    # Check cash was deducted
    account = await broker.get_account()
    assert account.cash == 10000.0 - (100.0 * 0.65)


@pytest.mark.asyncio
async def test_sell_order(broker, mock_market_data):
    # Buy first
    buy_order = OrderRequest(
        symbol="test-market-123",
        side=Side.BUY,
        quantity=100.0,
        order_type=OrderType.MARKET,
        platform=Platform.POLYMARKET,
    )
    await broker.submit_order(buy_order)

    # Then sell
    sell_order = OrderRequest(
        symbol="test-market-123",
        side=Side.SELL,
        quantity=50.0,
        order_type=OrderType.MARKET,
        platform=Platform.POLYMARKET,
    )
    result = await broker.submit_order(sell_order)

    assert result.status == OrderStatus.FILLED

    # Check remaining position
    positions = await broker.get_positions()
    assert len(positions) == 1
    assert positions[0].quantity == 50.0


@pytest.mark.asyncio
async def test_insufficient_funds(broker, mock_market_data):
    order = OrderRequest(
        symbol="test-market-123",
        side=Side.BUY,
        quantity=100000.0,  # Way too much
        order_type=OrderType.MARKET,
        platform=Platform.POLYMARKET,
    )
    result = await broker.submit_order(order)
    assert result.status == OrderStatus.REJECTED


@pytest.mark.asyncio
async def test_sell_more_than_held(broker, mock_market_data):
    # Buy 10
    buy_order = OrderRequest(
        symbol="test-market-123",
        side=Side.BUY,
        quantity=10.0,
        order_type=OrderType.MARKET,
        platform=Platform.POLYMARKET,
    )
    await broker.submit_order(buy_order)

    # Try to sell 20
    sell_order = OrderRequest(
        symbol="test-market-123",
        side=Side.SELL,
        quantity=20.0,
        order_type=OrderType.MARKET,
        platform=Platform.POLYMARKET,
    )
    result = await broker.submit_order(sell_order)
    assert result.status == OrderStatus.REJECTED


@pytest.mark.asyncio
async def test_reset(broker, mock_market_data):
    # Make a trade
    order = OrderRequest(
        symbol="test-market-123",
        side=Side.BUY,
        quantity=100.0,
        order_type=OrderType.MARKET,
        platform=Platform.POLYMARKET,
    )
    await broker.submit_order(order)

    # Reset
    broker.reset()
    account = await broker.get_account()
    assert account.cash == 10000.0
    assert len(account.positions) == 0


@pytest.mark.asyncio
async def test_state_persistence(tmp_path, monkeypatch, mock_market_data):
    monkeypatch.chdir(tmp_path)

    # Create broker and make a trade
    broker1 = PaperPolymarketBroker(initial_balance=10000.0)
    order = OrderRequest(
        symbol="test-market-123",
        side=Side.BUY,
        quantity=50.0,
        order_type=OrderType.MARKET,
        platform=Platform.POLYMARKET,
    )
    await broker1.submit_order(order)

    # Create a new broker instance (should load state from file)
    broker2 = PaperPolymarketBroker(initial_balance=10000.0)
    account = await broker2.get_account()
    assert account.cash < 10000.0  # Cash should reflect the trade
    positions = await broker2.get_positions()
    assert len(positions) == 1
