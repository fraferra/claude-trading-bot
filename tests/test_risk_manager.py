from trading_bot.config import RiskConfig
from trading_bot.models import (
    Action,
    OrderRequest,
    OrderType,
    Platform,
    PortfolioSummary,
    Position,
    Side,
    TradeDecision,
)
from trading_bot.risk.manager import RiskManager


def _make_portfolio(cash: float = 10000.0, positions: list | None = None) -> PortfolioSummary:
    positions = positions or []
    equity = cash + sum(p.market_value for p in positions)
    return PortfolioSummary(
        cash=cash,
        equity=equity,
        positions=positions,
        daily_pnl=0.0,
        platform=Platform.ALPACA,
    )


def _make_order(symbol: str = "AAPL", side: Side = Side.BUY, quantity: float = 10.0) -> OrderRequest:
    return OrderRequest(
        symbol=symbol,
        side=side,
        quantity=quantity,
        order_type=OrderType.MARKET,
        platform=Platform.ALPACA,
    )


def test_decision_below_confidence():
    rm = RiskManager(RiskConfig(min_confidence=0.6))
    decision = TradeDecision(
        action=Action.BUY, symbol="AAPL", confidence=0.4, reasoning="Weak signal"
    )
    result = rm.check_decision(decision)
    assert not result.approved
    assert "confidence" in result.reason.lower()


def test_decision_above_confidence():
    rm = RiskManager(RiskConfig(min_confidence=0.6))
    decision = TradeDecision(
        action=Action.BUY, symbol="AAPL", confidence=0.8, reasoning="Strong signal"
    )
    result = rm.check_decision(decision)
    assert result.approved


def test_order_exceeds_position_limit():
    rm = RiskManager(RiskConfig(max_position_pct=0.10))
    portfolio = _make_portfolio(cash=10000.0)
    # 10 shares at $150 = $1500 which is 15% of $10000 portfolio
    order = _make_order(quantity=10.0)
    result = rm.check_order(order, portfolio, current_price=150.0)
    # Should be adjusted down to 10% = $1000 / $150 ≈ 6.67 shares
    assert result.approved
    assert result.adjusted_quantity is not None
    assert result.adjusted_quantity < 10.0


def test_order_within_position_limit():
    rm = RiskManager(RiskConfig(max_position_pct=0.10))
    portfolio = _make_portfolio(cash=10000.0)
    # 5 shares at $150 = $750 which is 7.5% of $10000 — within 10% limit
    order = _make_order(quantity=5.0)
    result = rm.check_order(order, portfolio, current_price=150.0)
    assert result.approved
    assert result.adjusted_quantity is None


def test_daily_trade_limit():
    rm = RiskManager(RiskConfig(max_trades_per_day=2))
    portfolio = _make_portfolio()
    order = _make_order(quantity=1.0)

    # First two trades should pass
    rm.record_trade()
    rm.record_trade()

    # Third should be rejected
    result = rm.check_order(order, portfolio, current_price=150.0)
    assert not result.approved
    assert "daily trade limit" in result.reason.lower()


def test_daily_loss_limit():
    rm = RiskManager(RiskConfig(daily_loss_limit_pct=0.03))
    portfolio = PortfolioSummary(
        cash=9500.0,
        equity=9500.0,
        positions=[],
        daily_pnl=-350.0,  # 3.68% loss on $9500 equity
        platform=Platform.ALPACA,
    )
    order = _make_order(quantity=1.0)
    result = rm.check_order(order, portfolio, current_price=150.0)
    assert not result.approved
    assert "daily loss limit" in result.reason.lower()


def test_insufficient_cash():
    rm = RiskManager(RiskConfig(max_position_pct=1.0, max_total_exposure_pct=1.0))
    portfolio = _make_portfolio(cash=100.0)
    # 10 shares at $150 = $1500 but only $100 cash
    order = _make_order(quantity=10.0)
    result = rm.check_order(order, portfolio, current_price=150.0)
    assert result.approved  # Should adjust down
    assert result.adjusted_quantity is not None
    assert result.adjusted_quantity * 150.0 <= 100.0


def test_sell_order_no_position_checks():
    rm = RiskManager(RiskConfig())
    portfolio = _make_portfolio(cash=10000.0)
    order = _make_order(side=Side.SELL, quantity=5.0)
    result = rm.check_order(order, portfolio, current_price=150.0)
    assert result.approved


def test_calculate_position_size():
    rm = RiskManager(RiskConfig(max_position_pct=0.10))
    qty = rm.calculate_position_size(
        confidence=0.8,
        portfolio_equity=100000.0,
        current_price=150.0,
    )
    # 0.10 * 0.8 = 0.08 → $8000 / $150 = 53.33
    assert abs(qty - 53.3333) < 0.01


def test_max_exposure_limit():
    rm = RiskManager(RiskConfig(max_position_pct=1.0, max_total_exposure_pct=0.50))
    existing_pos = Position(
        symbol="MSFT",
        quantity=20,
        avg_entry_price=300.0,
        current_price=300.0,
        market_value=6000.0,
        unrealized_pnl=0.0,
        platform=Platform.ALPACA,
    )
    portfolio = _make_portfolio(cash=4000.0, positions=[existing_pos])
    # Portfolio equity = 10000, already 60% invested, max is 50%
    order = _make_order(symbol="AAPL", quantity=10.0)
    result = rm.check_order(order, portfolio, current_price=150.0)
    # Already over limit, should reject
    assert not result.approved
