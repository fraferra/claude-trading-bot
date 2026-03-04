from trading_bot.models import (
    Action,
    OrderRequest,
    OrderType,
    Platform,
    PortfolioSummary,
    Position,
    RiskCheckResult,
    Side,
    TradeDecision,
)


def test_trade_decision_valid():
    d = TradeDecision(
        action=Action.BUY,
        symbol="AAPL",
        confidence=0.85,
        reasoning="Strong momentum",
        suggested_position_pct=0.05,
    )
    assert d.action == Action.BUY
    assert d.confidence == 0.85
    assert d.suggested_position_pct == 0.05


def test_trade_decision_hold():
    d = TradeDecision(
        action=Action.HOLD,
        symbol="MSFT",
        confidence=0.3,
        reasoning="Mixed signals",
    )
    assert d.action == Action.HOLD
    assert d.suggested_position_pct == 0.0
    assert d.suggested_size_usd == 0.0


def test_trade_decision_from_dict():
    data = {
        "action": "sell",
        "symbol": "TSLA",
        "confidence": 0.7,
        "reasoning": "Overbought on RSI",
        "suggested_position_pct": 0.03,
    }
    d = TradeDecision(**data)
    assert d.action == Action.SELL
    assert d.symbol == "TSLA"


def test_order_request():
    order = OrderRequest(
        symbol="AAPL",
        side=Side.BUY,
        quantity=10.0,
        order_type=OrderType.LIMIT,
        limit_price=150.0,
        platform=Platform.ALPACA,
    )
    assert order.symbol == "AAPL"
    assert order.limit_price == 150.0


def test_position():
    pos = Position(
        symbol="AAPL",
        quantity=10,
        avg_entry_price=145.0,
        current_price=155.0,
        market_value=1550.0,
        unrealized_pnl=100.0,
        platform=Platform.ALPACA,
    )
    assert pos.unrealized_pnl == 100.0


def test_portfolio_summary():
    pos = Position(
        symbol="AAPL",
        quantity=10,
        avg_entry_price=145.0,
        current_price=155.0,
        market_value=1550.0,
        unrealized_pnl=100.0,
        platform=Platform.ALPACA,
    )
    summary = PortfolioSummary(
        cash=8450.0,
        equity=10000.0,
        positions=[pos],
        daily_pnl=50.0,
        platform=Platform.ALPACA,
    )
    assert len(summary.positions) == 1
    assert summary.cash == 8450.0


def test_risk_check_result():
    result = RiskCheckResult(approved=False, reason="Too risky")
    assert not result.approved
    assert result.reason == "Too risky"

    result2 = RiskCheckResult(approved=True)
    assert result2.approved
