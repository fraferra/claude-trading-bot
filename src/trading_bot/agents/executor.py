"""Executor Agent — calculates and executes rebalancing trades."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from trading_bot.brokers.base import BaseBroker
from trading_bot.config import Config
from trading_bot.db.repository import Repository
from trading_bot.models import (
    AllocationEntry,
    OrderRequest,
    OrderResult,
    OrderType,
    Platform,
    PortfolioAllocation,
    Side,
)
from trading_bot.risk.manager import RiskManager
from trading_bot.utils.logging import log

_ET = ZoneInfo("America/New_York")
_MARKET_OPEN = time(9, 30)
_MARKET_CLOSE = time(16, 0)


class ExecutorAgent:
    """Calculate and execute rebalancing trades via Alpaca broker."""

    def __init__(
        self,
        config: Config,
        broker: BaseBroker,
        risk_manager: RiskManager,
        repo: Repository,
    ) -> None:
        self.config = config
        self.broker = broker
        self.risk_manager = risk_manager
        self.repo = repo

    @staticmethod
    def is_market_open() -> bool:
        """Check if US stock market is currently open (ET timezone)."""
        now_et = datetime.now(_ET)
        # Weekday: Mon=0 .. Fri=4
        if now_et.weekday() >= 5:
            return False
        return _MARKET_OPEN <= now_et.time() <= _MARKET_CLOSE

    async def rebalance(
        self, allocation: PortfolioAllocation, source: str = "research_agent"
    ) -> list[OrderResult]:
        """Execute trades to move from current to target allocation.

        Sells first, then buys, to free up cash.
        Only executes during US market hours (9:30 AM - 4:00 PM ET, Mon-Fri).
        """
        if not allocation.rebalance_needed:
            log.info("No rebalance needed")
            return []

        if not self.is_market_open():
            now_et = datetime.now(_ET)
            log.info(
                f"Market is closed (ET: {now_et.strftime('%A %H:%M')}). "
                f"Skipping execution — will retry next cycle."
            )
            return []

        portfolio = await self.broker.get_account()
        equity = portfolio.equity + portfolio.cash

        if equity <= 0:
            log.warning("Portfolio has no equity, skipping rebalance")
            return []

        # Separate sells and buys
        sells = [e for e in allocation.entries if e.action in ("sell", "trim")]
        buys = [e for e in allocation.entries if e.action in ("buy", "add")]

        results = []

        # Execute sells first
        for entry in sells:
            result = await self._execute_entry(entry, equity, source)
            if result:
                results.append(result)

        # Then buys
        for entry in buys:
            result = await self._execute_entry(entry, equity, source)
            if result:
                results.append(result)

        log.info(f"Rebalance complete: {len(results)} trades executed")
        return results

    async def _execute_entry(
        self, entry: AllocationEntry, equity: float, source: str
    ) -> OrderResult | None:
        """Execute a single allocation entry as a market order."""
        try:
            current_price = await self.broker.get_quote(entry.symbol)
            if current_price <= 0:
                return None

            # Calculate target dollar value and quantity
            if entry.action in ("sell", "trim"):
                # Sell: reduce from current to target weight
                dollar_diff = (entry.current_weight - entry.target_weight) * equity
                qty = dollar_diff / current_price
                side = Side.SELL
            else:
                # Buy/add: increase from current to target weight
                dollar_diff = (entry.target_weight - entry.current_weight) * equity
                qty = dollar_diff / current_price
                side = Side.BUY

            qty = round(qty, 2)
            if qty <= 0:
                return None

            # Risk check
            order = OrderRequest(
                symbol=entry.symbol,
                side=side,
                quantity=qty,
                order_type=OrderType.MARKET,
                platform=Platform.ALPACA,
            )

            risk_check = self.risk_manager.check_order(
                order, await self.broker.get_account(), current_price
            )
            if not risk_check.approved:
                log.info(f"Risk check rejected {entry.symbol}: {risk_check.reason}")
                return None

            if risk_check.adjusted_quantity is not None:
                order.quantity = risk_check.adjusted_quantity

            # Submit
            result = await self.broker.submit_order(order)
            self.risk_manager.record_trade()

            # Log trade
            await self.repo.insert_trade(
                order_id=result.order_id,
                symbol=entry.symbol,
                side=side.value,
                quantity=order.quantity,
                filled_price=result.filled_price,
                platform="alpaca",
                source=source,
                strategy_name="research_agent",
                reasoning=f"Rebalance: {entry.action} to {entry.target_weight:.1%} weight",
                confidence=entry.research_score / 10.0,
                status=result.status.value,
            )

            log.info(
                f"Executor: {side.value} {order.quantity:.2f} {entry.symbol} @ ${current_price:.2f}"
            )
            return result

        except Exception as e:
            log.warning(f"Executor failed on {entry.symbol}: {e}")
            return None
