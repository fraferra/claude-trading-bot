"""Extended RiskManager tests: Kelly position sizing, check_short_order,
calculate_short_position_size, and edge-case coverage.
"""

from __future__ import annotations

import pytest

from trading_bot.config import RiskConfig, ShortConfig
from trading_bot.models import (
    OrderRequest,
    OrderType,
    Platform,
    PortfolioSummary,
    Position,
    Side,
    TradeDecision,
    Action,
)
from trading_bot.risk.manager import RiskManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _risk_cfg(**kwargs) -> RiskConfig:
    defaults = dict(
        max_position_pct=0.10,
        max_total_exposure_pct=0.80,
        daily_loss_limit_pct=0.03,
        min_confidence=0.60,
        max_trades_per_day=10,
    )
    defaults.update(kwargs)
    return RiskConfig(**defaults)


def _short_cfg(**kwargs) -> ShortConfig:
    defaults = dict(
        enabled=True,
        max_short_exposure_pct=0.30,
        max_single_short_pct=0.05,
        risk_per_trade_pct=0.005,
        stop_atr_multiplier=2.5,
    )
    defaults.update(kwargs)
    return ShortConfig(**defaults)


def _portfolio(equity=10_000.0, cash=10_000.0, daily_pnl=0.0, positions=None):
    return PortfolioSummary(
        cash=cash,
        equity=equity,
        positions=positions or [],
        daily_pnl=daily_pnl,
        platform=Platform.ALPACA,
    )


def _order(symbol="AAPL", qty=10.0, side=Side.BUY, price=100.0):
    return OrderRequest(
        symbol=symbol,
        quantity=qty,
        side=side,
        order_type=OrderType.MARKET,
        limit_price=price,
        platform=Platform.ALPACA,
    )


def _position(symbol, qty, price, market_value=None):
    mv = market_value if market_value is not None else abs(qty) * price
    return Position(
        symbol=symbol,
        quantity=qty,
        avg_entry_price=price,
        current_price=price,
        market_value=mv,
        unrealized_pnl=0.0,
        platform=Platform.ALPACA,
    )


# ---------------------------------------------------------------------------
# TestKellyPositionSizing
# ---------------------------------------------------------------------------

class TestKellyPositionSizing:
    """calculate_kelly_position_size:
    capped = fraction * cap
    raw = equity * capped
    return min(raw, max_size_usd, equity * max_position_pct)
    """

    def _rm(self, max_position_pct=0.10) -> RiskManager:
        return RiskManager(_risk_cfg(max_position_pct=max_position_pct))

    def test_basic_kelly_size(self):
        rm = self._rm()
        # fraction=0.20, cap=0.25 → capped=0.05, raw=10000*0.05=500
        # min(500, 1000, 10000*0.10=1000) → 500
        size = rm.calculate_kelly_position_size(0.20, 0.25, 10_000.0, 1_000.0)
        assert size == pytest.approx(500.0)

    def test_kelly_capped_by_max_size_usd(self):
        rm = self._rm()
        # fraction=0.50, cap=1.0 → raw=10000*0.50=5000
        # min(5000, 100, 1000) → 100
        size = rm.calculate_kelly_position_size(0.50, 1.0, 10_000.0, 100.0)
        assert size == pytest.approx(100.0)

    def test_kelly_capped_by_max_position_pct(self):
        rm = self._rm(max_position_pct=0.05)
        # fraction=0.50, cap=1.0 → raw=10000*0.50=5000
        # min(5000, 10000, 10000*0.05=500) → 500
        size = rm.calculate_kelly_position_size(0.50, 1.0, 10_000.0, 10_000.0)
        assert size == pytest.approx(500.0)

    def test_kelly_fraction_zero_returns_zero(self):
        rm = self._rm()
        size = rm.calculate_kelly_position_size(0.0, 0.25, 10_000.0, 1_000.0)
        assert size == pytest.approx(0.0)

    def test_kelly_cap_applied(self):
        rm = self._rm()
        # fraction=0.40, cap=0.25 → capped=0.10
        # raw=10000*0.10=1000; min(1000, 2000, 1000) → 1000
        size = rm.calculate_kelly_position_size(0.40, 0.25, 10_000.0, 2_000.0)
        assert size == pytest.approx(1_000.0)

    def test_kelly_all_caps_binding(self):
        # Verify the most restrictive cap wins
        rm = self._rm(max_position_pct=0.01)  # very restrictive
        size = rm.calculate_kelly_position_size(0.50, 1.0, 10_000.0, 5_000.0)
        # equity * max_position_pct = 100 is the binding constraint
        assert size == pytest.approx(100.0)

    def test_kelly_result_rounded_to_cents(self):
        rm = self._rm()
        size = rm.calculate_kelly_position_size(0.123456789, 0.25, 10_000.0, 10_000.0)
        # Should be rounded to 2 decimal places
        assert round(size, 2) == size


# ---------------------------------------------------------------------------
# TestShortOrderChecks
# ---------------------------------------------------------------------------

class TestShortOrderChecks:

    def _rm(self, max_trades_per_day=10, daily_loss_limit_pct=0.03) -> RiskManager:
        return RiskManager(_risk_cfg(
            max_trades_per_day=max_trades_per_day,
            daily_loss_limit_pct=daily_loss_limit_pct,
        ))

    def test_short_within_single_limit_approved(self):
        rm = self._rm()
        portfolio = _portfolio(equity=10_000.0)
        # order_value = 10 * 40 = 400 < max_single = 10000 * 0.05 = 500
        order = _order(symbol="AAPL", qty=10.0, side=Side.SELL, price=40.0)
        result = rm.check_short_order(order, portfolio, 40.0, _short_cfg())
        assert result.approved

    def test_short_exceeds_single_limit_adjusted(self):
        rm = self._rm()
        portfolio = _portfolio(equity=10_000.0)
        # order_value = 100 * 100 = 10000 > max_single = 10000 * 0.05 = 500
        order = _order(symbol="AAPL", qty=100.0, side=Side.SELL, price=100.0)
        result = rm.check_short_order(order, portfolio, 100.0, _short_cfg())
        assert result.approved
        assert result.adjusted_quantity is not None
        assert result.adjusted_quantity < 100.0

    def test_short_rejected_when_total_exposure_full(self):
        rm = self._rm()
        # Existing short positions fill exposure
        existing_short = _position("TSLA", qty=-30.0, price=100.0, market_value=3_000.0)
        portfolio = _portfolio(equity=10_000.0, positions=[existing_short])
        # max_short_exposure = 10000 * 0.30 = 3000; already at 3000
        order = _order(symbol="AAPL", qty=1.0, side=Side.SELL, price=100.0)
        result = rm.check_short_order(order, portfolio, 100.0, _short_cfg())
        assert not result.approved

    def test_short_respects_daily_trade_limit(self):
        rm = self._rm(max_trades_per_day=2)
        from datetime import date
        today = date.today()
        rm._trades_today[today] = 2  # At limit

        portfolio = _portfolio()
        order = _order(side=Side.SELL, qty=5.0, price=50.0)
        result = rm.check_short_order(order, portfolio, 50.0, _short_cfg())
        assert not result.approved
        assert "Daily trade limit" in result.reason

    def test_short_respects_daily_loss_limit(self):
        rm = self._rm(daily_loss_limit_pct=0.03)
        # daily_pnl = -400, equity = 10000 → loss_pct = 0.04 >= 0.03
        portfolio = _portfolio(equity=10_000.0, daily_pnl=-400.0)
        order = _order(side=Side.SELL, qty=5.0, price=50.0)
        result = rm.check_short_order(order, portfolio, 50.0, _short_cfg())
        assert not result.approved
        assert "loss limit" in result.reason.lower()


# ---------------------------------------------------------------------------
# TestShortPositionSizing
# ---------------------------------------------------------------------------

class TestShortPositionSizing:
    """calculate_short_position_size:
    risk_amount = equity * risk_per_trade_pct
    stop_distance = atr * stop_atr_multiplier
    shares = risk_amount / stop_distance, capped by max_single_short_pct
    """

    def _rm(self) -> RiskManager:
        return RiskManager(_risk_cfg())

    def test_size_based_on_atr_stop_distance(self):
        rm = self._rm()
        # equity=10000, risk_per_trade=0.005 → risk_amount=50
        # atr=2.0, multiplier=2.5 → stop_distance=5.0
        # shares = 50 / 5 = 10
        # max_single = 10000 * 0.05 / 100 = 5 shares (@ $100)
        # min(10, 5) → 5
        cfg = _short_cfg(risk_per_trade_pct=0.005, stop_atr_multiplier=2.5, max_single_short_pct=0.05)
        size = rm.calculate_short_position_size(10_000.0, 100.0, 2.0, cfg)
        assert size > 0

    def test_size_capped_by_single_short_pct(self):
        rm = self._rm()
        # Very large ATR → very few shares from risk formula, but check cap still applied
        cfg = _short_cfg(risk_per_trade_pct=0.005, stop_atr_multiplier=2.5, max_single_short_pct=0.05)
        # With small ATR, risk formula gives many shares → capped by max_single_short_pct
        size = rm.calculate_short_position_size(100_000.0, 10.0, 0.01, cfg)
        max_shares = (100_000.0 * 0.05) / 10.0  # = 500
        assert size <= max_shares

    def test_zero_atr_returns_zero(self):
        rm = self._rm()
        cfg = _short_cfg()
        size = rm.calculate_short_position_size(10_000.0, 100.0, 0.0, cfg)
        assert size == 0.0

    def test_zero_price_returns_zero(self):
        rm = self._rm()
        cfg = _short_cfg()
        size = rm.calculate_short_position_size(10_000.0, 0.0, 2.0, cfg)
        assert size == 0.0

    def test_result_rounded_to_two_decimals(self):
        rm = self._rm()
        cfg = _short_cfg(risk_per_trade_pct=0.005, stop_atr_multiplier=3.0)
        size = rm.calculate_short_position_size(10_000.0, 57.33, 1.7, cfg)
        assert round(size, 2) == size

    def test_size_always_positive(self):
        rm = self._rm()
        cfg = _short_cfg()
        size = rm.calculate_short_position_size(10_000.0, 100.0, 2.0, cfg)
        assert size >= 0.0


# ---------------------------------------------------------------------------
# TestRiskManagerEdgeCases
# ---------------------------------------------------------------------------

class TestRiskManagerEdgeCases:

    def _rm(self, **kwargs) -> RiskManager:
        return RiskManager(_risk_cfg(**kwargs))

    def test_confidence_exactly_at_threshold_approved(self):
        rm = self._rm(min_confidence=0.60)
        decision = TradeDecision(
            action=Action.BUY, symbol="AAPL", confidence=0.60, reasoning="exact threshold"
        )
        result = rm.check_decision(decision)
        assert result.approved

    def test_confidence_just_below_threshold_rejected(self):
        rm = self._rm(min_confidence=0.60)
        decision = TradeDecision(
            action=Action.BUY, symbol="AAPL", confidence=0.599, reasoning="just below"
        )
        result = rm.check_decision(decision)
        assert not result.approved

    def test_daily_loss_exact_boundary_rejected(self):
        rm = self._rm(daily_loss_limit_pct=0.03)
        # loss = exactly 3% of equity → rejected (>= check)
        portfolio = _portfolio(equity=10_000.0, daily_pnl=-300.0)
        order = _order()
        result = rm.check_order(order, portfolio, 100.0)
        assert not result.approved

    def test_sell_order_skips_position_size_check(self):
        rm = self._rm(max_position_pct=0.001)  # Very restrictive
        # Even a tiny sell should pass position-size check (only buys checked)
        portfolio = _portfolio(equity=10_000.0, cash=10_000.0)
        order = _order(qty=1.0, side=Side.SELL, price=50.0)
        result = rm.check_order(order, portfolio, 50.0)
        assert result.approved

    def test_check_order_approved_when_all_checks_pass(self):
        rm = self._rm()
        portfolio = _portfolio(equity=10_000.0, cash=9_000.0)
        # Small order well within limits
        order = _order(qty=1.0, side=Side.BUY, price=100.0)
        result = rm.check_order(order, portfolio, 100.0)
        assert result.approved

    def test_record_trade_increments_count(self):
        rm = self._rm()
        from datetime import date
        today = date.today()
        initial = rm._trades_today.get(today, 0)
        rm.record_trade()
        assert rm._trades_today[today] == initial + 1

    def test_calculate_position_size_scales_with_confidence(self):
        rm = self._rm(max_position_pct=0.10)
        low  = rm.calculate_position_size(0.60, 10_000.0, 100.0)
        high = rm.calculate_position_size(0.90, 10_000.0, 100.0)
        assert high > low

    def test_daily_trade_limit_reached_rejected(self):
        rm = self._rm(max_trades_per_day=3)
        from datetime import date
        today = date.today()
        rm._trades_today[today] = 3

        portfolio = _portfolio()
        order = _order()
        result = rm.check_order(order, portfolio, 100.0)
        assert not result.approved
        assert "Daily trade limit" in result.reason
