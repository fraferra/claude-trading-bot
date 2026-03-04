from __future__ import annotations

from datetime import date

from trading_bot.config import RiskConfig
from trading_bot.models import (
    OrderRequest,
    PortfolioSummary,
    RiskCheckResult,
    Side,
    TradeDecision,
)
from trading_bot.utils.logging import log


class RiskManager:
    def __init__(self, config: RiskConfig) -> None:
        self.config = config
        self._trades_today: dict[date, int] = {}

    def check_decision(self, decision: TradeDecision) -> RiskCheckResult:
        """Check if an LLM trading decision meets minimum confidence requirements."""
        if decision.confidence < self.config.min_confidence:
            return RiskCheckResult(
                approved=False,
                reason=f"Confidence {decision.confidence:.0%} is below minimum {self.config.min_confidence:.0%}",
            )
        return RiskCheckResult(approved=True)

    def check_order(
        self,
        order: OrderRequest,
        portfolio: PortfolioSummary,
        current_price: float,
    ) -> RiskCheckResult:
        """Run all pre-trade risk checks on an order."""
        # 1. Daily trade count limit
        today = date.today()
        count = self._trades_today.get(today, 0)
        if count >= self.config.max_trades_per_day:
            return RiskCheckResult(
                approved=False,
                reason=f"Daily trade limit reached ({self.config.max_trades_per_day} trades)",
            )

        # 2. Daily loss limit
        if portfolio.equity > 0:
            daily_loss_pct = -portfolio.daily_pnl / portfolio.equity
            if daily_loss_pct >= self.config.daily_loss_limit_pct:
                return RiskCheckResult(
                    approved=False,
                    reason=f"Daily loss limit reached ({daily_loss_pct:.1%} >= {self.config.daily_loss_limit_pct:.1%})",
                )

        # 3. Max position size check (for buys only)
        if order.side == Side.BUY:
            order_value = order.quantity * current_price
            max_position_value = portfolio.equity * self.config.max_position_pct

            # Check existing position in this symbol
            existing_value = 0.0
            for pos in portfolio.positions:
                if pos.symbol == order.symbol:
                    existing_value = pos.market_value
                    break

            total_position_value = existing_value + order_value
            if total_position_value > max_position_value:
                max_additional = max_position_value - existing_value
                max_qty = max_additional / current_price if current_price > 0 else 0
                if max_qty <= 0:
                    return RiskCheckResult(
                        approved=False,
                        reason=f"Position in {order.symbol} already at max ({self.config.max_position_pct:.0%} of portfolio)",
                    )
                return RiskCheckResult(
                    approved=True,
                    reason=f"Position size reduced from {order.quantity} to {max_qty:.2f} to stay within limits",
                    adjusted_quantity=max_qty,
                )

            # 4. Max total exposure check
            total_invested = sum(p.market_value for p in portfolio.positions)
            total_after = total_invested + order_value
            max_exposure = portfolio.equity * self.config.max_total_exposure_pct
            if total_after > max_exposure:
                remaining = max_exposure - total_invested
                max_qty = remaining / current_price if current_price > 0 else 0
                if max_qty <= 0:
                    return RiskCheckResult(
                        approved=False,
                        reason=f"Total exposure at max ({self.config.max_total_exposure_pct:.0%} of portfolio)",
                    )
                return RiskCheckResult(
                    approved=True,
                    reason=f"Order reduced to {max_qty:.2f} units to stay within total exposure limit",
                    adjusted_quantity=max_qty,
                )

            # 5. Cash check
            if order_value > portfolio.cash:
                max_qty = portfolio.cash / current_price if current_price > 0 else 0
                if max_qty <= 0:
                    return RiskCheckResult(
                        approved=False,
                        reason=f"Insufficient cash: ${portfolio.cash:.2f} available, ${order_value:.2f} needed",
                    )
                return RiskCheckResult(
                    approved=True,
                    reason=f"Order reduced to {max_qty:.2f} units due to available cash",
                    adjusted_quantity=max_qty,
                )

        return RiskCheckResult(approved=True)

    def calculate_position_size(
        self,
        confidence: float,
        portfolio_equity: float,
        current_price: float,
    ) -> float:
        """Calculate position size based on confidence (simplified Kelly-inspired).

        Higher confidence → larger position, scaled by max_position_pct.
        """
        # Scale from 0 to max_position_pct based on confidence
        # Minimum confidence threshold already enforced by check_decision
        base_pct = self.config.max_position_pct * confidence
        position_value = portfolio_equity * base_pct
        quantity = position_value / current_price if current_price > 0 else 0
        return round(quantity, 4)

    def calculate_kelly_position_size(
        self,
        kelly_fraction: float,
        kelly_cap: float,
        portfolio_equity: float,
        max_size_usd: float,
    ) -> float:
        """Calculate position size using Kelly Criterion.

        kelly_fraction: Raw Kelly fraction from strategy
        kelly_cap: Fractional Kelly multiplier (e.g., 0.25 for quarter-Kelly)
        portfolio_equity: Total portfolio value
        max_size_usd: Hard cap on position size
        """
        capped = kelly_fraction * kelly_cap
        raw_size = portfolio_equity * capped
        max_from_risk = portfolio_equity * self.config.max_position_pct
        return round(min(raw_size, max_size_usd, max_from_risk), 2)

    def record_trade(self) -> None:
        """Record that a trade was executed today."""
        today = date.today()
        self._trades_today[today] = self._trades_today.get(today, 0) + 1
        log.debug(f"Trades today: {self._trades_today[today]}/{self.config.max_trades_per_day}")
