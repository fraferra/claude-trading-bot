"""Crypto Agent — high-frequency crypto trading using momentum/mean-reversion."""

from __future__ import annotations

from trading_bot.brokers.base import BaseBroker
from trading_bot.config import Config
from trading_bot.db.repository import Repository
from trading_bot.models import (
    OrderRequest,
    OrderResult,
    OrderType,
    Platform,
    PortfolioSummary,
    Side,
)
from trading_bot.risk.manager import RiskManager
from trading_bot.strategies.crypto_momentum import CryptoMomentumStrategy
from trading_bot.utils.logging import log


class CryptoAgent:
    """High-frequency crypto trading agent using momentum/mean-reversion signals."""

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
        self.strategy = CryptoMomentumStrategy(config)

    async def run_cycle(self, portfolio: PortfolioSummary) -> list[OrderResult]:
        """Execute one cycle: scan watchlist, generate signals, submit orders."""
        result = await self.strategy.scan(portfolio=portfolio)

        if not result.decisions:
            log.debug("Crypto Agent: no signals this cycle")
            return []

        executed: list[OrderResult] = []

        for decision in result.decisions:
            try:
                # Get crypto-specific metadata from StrategyResult
                crypto_meta = result.metadata.get("crypto_decisions", [])
                crypto_decision = None
                for cd in crypto_meta:
                    if cd.get("symbol") == decision.symbol:
                        crypto_decision = cd
                        break

                current_price = crypto_decision["technical_signals"]["current_price"] if crypto_decision else 0.0
                if current_price <= 0:
                    current_price = await self.broker.get_crypto_quote(decision.symbol)

                if current_price <= 0:
                    continue

                qty = decision.suggested_size_usd / current_price
                if qty <= 0:
                    continue

                side = Side.BUY if decision.action.value == "buy" else Side.SELL

                # Use limit price from crypto decision if available
                limit_price = None
                if crypto_decision:
                    limit_price = crypto_decision.get("limit_price", current_price)

                order = OrderRequest(
                    symbol=decision.symbol,
                    side=side,
                    quantity=round(qty, 6),  # Crypto supports fractional quantities
                    order_type=OrderType.LIMIT,
                    limit_price=limit_price,
                    platform=Platform.ALPACA_CRYPTO,
                )

                # Risk check
                order_check = self.risk_manager.check_order(order, portfolio, current_price)
                if not order_check.approved:
                    log.info(f"Crypto risk check rejected {decision.symbol}: {order_check.reason}")
                    continue
                if order_check.adjusted_quantity is not None:
                    order.quantity = order_check.adjusted_quantity

                # Submit
                trade_result = await self.broker.submit_order(order)
                self.risk_manager.record_trade()

                # Log trade
                await self.repo.insert_trade(
                    order_id=trade_result.order_id,
                    symbol=decision.symbol,
                    side=side.value,
                    quantity=order.quantity,
                    filled_price=trade_result.filled_price,
                    platform="alpaca_crypto",
                    source="crypto_agent",
                    strategy_name="crypto_momentum",
                    reasoning=decision.reasoning[:500],
                    confidence=decision.confidence,
                    status=trade_result.status.value,
                )

                log.info(
                    f"Crypto Agent: {side.value} {order.quantity:.6f} {decision.symbol} "
                    f"@ ${current_price:,.2f} (limit: ${limit_price:,.2f})"
                )
                executed.append(trade_result)

            except Exception as e:
                log.warning(f"Crypto Agent failed on {decision.symbol}: {e}")

        log.info(f"Crypto Agent cycle complete: {len(executed)} trades executed")
        return executed
