"""Crypto momentum trading monitor — 15-minute cycle high-frequency crypto trading."""

from __future__ import annotations

from trading_bot.analysis.crypto_data import compute_crypto_technicals, get_crypto_bars
from trading_bot.models import (
    Action, OrderRequest, OrderType, Platform, Side, WSEvent, WSEventType,
)
from trading_bot.monitors.adaptation import StrategyAdaptation
from trading_bot.monitors.base import BaseMonitor
from trading_bot.strategies.crypto_momentum import CryptoMomentumStrategy
from trading_bot.utils.logging import log


class CryptoMomentumMonitor(BaseMonitor):
    """High-frequency crypto momentum trading monitor (15-minute cycles).

    No market hours check — crypto trades 24/7.
    Uses Alpaca for crypto execution with GTC time-in-force.
    """

    monitor_type = "crypto_momentum"

    def get_interval_seconds(self) -> int:
        return self.config.crypto.scan_interval_minutes * 60

    async def run_cycle(self) -> None:
        broker = self.brokers.get("alpaca")
        if not broker:
            log.warning("No Alpaca broker configured for crypto — skipping cycle")
            return

        strategy = CryptoMomentumStrategy(self.config)
        state = await self.repo.get_monitor_state(self.monitor_id)
        scale = state["current_position_scale"] if state else 1.0
        portfolio = await broker.get_account()

        result = await strategy.scan(portfolio=portfolio)

        if not result.decisions:
            log.debug("Crypto Monitor: no signals this cycle")
            return

        if result.decisions:
            await self.event_bus.broadcast(WSEvent(
                type=WSEventType.STRATEGY_SIGNAL,
                data={
                    "strategy": "crypto_momentum",
                    "signals_found": len(result.decisions),
                    "source": f"monitor:{self.monitor_id}",
                },
            ))

        # Get crypto decision metadata for limit prices
        crypto_decisions = result.metadata.get("crypto_decisions", [])
        crypto_map = {cd.get("symbol", ""): cd for cd in crypto_decisions}

        for decision in result.decisions:
            try:
                cd = crypto_map.get(decision.symbol, {})
                signals = cd.get("technical_signals", {})
                current_price = signals.get("current_price", 0.0)

                if current_price <= 0:
                    current_price = await broker.get_crypto_quote(decision.symbol)
                if current_price <= 0:
                    continue

                raw_size = decision.suggested_size_usd * scale
                qty = raw_size / current_price if current_price > 0 else 0
                if qty <= 0:
                    continue

                # Record signal to DB
                await self.repo.insert_crypto_signal(
                    symbol=decision.symbol,
                    rsi_14=signals.get("rsi_14"),
                    macd=signals.get("macd"),
                    macd_signal=signals.get("macd_signal"),
                    bb_pct_b=signals.get("bb_pct_b"),
                    momentum_score=signals.get("momentum_score", 0.0),
                    mean_reversion_score=signals.get("mean_reversion_score", 0.0),
                    composite_signal=signals.get("composite_signal", 0.0),
                    signal_direction=signals.get("signal_direction", "hold"),
                    current_price=current_price,
                    llm_override=cd.get("llm_override", False),
                    llm_reasoning=cd.get("llm_reasoning", ""),
                )

                side = Side.BUY if decision.action.value == "buy" else Side.SELL
                limit_price = cd.get("limit_price", current_price)

                order = OrderRequest(
                    symbol=decision.symbol,
                    side=side,
                    quantity=round(qty, 6),
                    order_type=OrderType.LIMIT,
                    limit_price=limit_price,
                    platform=Platform.ALPACA_CRYPTO,
                )

                order_check = self.risk_manager.check_order(order, portfolio, current_price)
                if not order_check.approved:
                    log.info(f"Crypto risk check rejected {decision.symbol}: {order_check.reason}")
                    continue
                if order_check.adjusted_quantity is not None:
                    order.quantity = order_check.adjusted_quantity

                trade_result = await broker.submit_order(order)
                self.risk_manager.record_trade()

                trade_id = await self.repo.insert_trade(
                    order_id=trade_result.order_id,
                    symbol=decision.symbol,
                    side=side.value,
                    quantity=order.quantity,
                    filled_price=trade_result.filled_price,
                    platform="alpaca_crypto",
                    source=f"monitor:{self.monitor_id}",
                    strategy_name="crypto_momentum",
                    reasoning=decision.reasoning[:500],
                    confidence=decision.confidence,
                    status=trade_result.status.value,
                )
                await self.repo.insert_monitor_trade(
                    self.monitor_id, trade_id, current_price, order.quantity,
                )

                await self.event_bus.broadcast(WSEvent(
                    type=WSEventType.TRADE_EXECUTED,
                    data={
                        "symbol": decision.symbol,
                        "side": side.value,
                        "quantity": order.quantity,
                        "filled_price": trade_result.filled_price,
                        "source": f"monitor:{self.monitor_id}",
                    },
                ))

            except Exception as e:
                log.warning(f"Crypto Monitor trade failed for {decision.symbol}: {e}")

        # Strategy adaptation
        adaptation = StrategyAdaptation(self.config.monitors, self.repo)
        await adaptation.evaluate_and_adapt(self.monitor_id)
