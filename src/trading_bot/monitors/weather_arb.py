"""Weather forecast arbitrage monitor.

Scans Polymarket for short-term weather event markets and compares prices
against NOAA Weather.gov forecast probabilities. Executes trades when the
NOAA-derived probability diverges from the market price by >= min_edge_pct.

No LLM calls — pure NOAA data vs market price comparison.
"""

from __future__ import annotations

from trading_bot.models import (
    OrderRequest,
    OrderType,
    Platform,
    Side,
    WSEvent,
    WSEventType,
)
from trading_bot.monitors.base import BaseMonitor
from trading_bot.strategies.weather_arb import WeatherArbScanner
from trading_bot.utils.logging import log


class WeatherArbMonitor(BaseMonitor):
    """Weather arbitrage monitor.

    Every cycle:
    1. Scan Polymarket for weather markets in the configured time window
    2. Fetch NOAA forecasts for each relevant city
    3. Compare NOAA probability vs market price
    4. Execute trades where edge >= min_edge_pct
    """

    monitor_type = "weather_arb"

    def get_interval_seconds(self) -> int:
        return self.config.weather_arb.scan_interval_minutes * 60

    async def run_cycle(self) -> None:
        if not self.config.weather_arb.enabled:
            return

        broker = self.brokers.get("polymarket")
        if not broker:
            log.warning("WeatherArbMonitor: no Polymarket broker configured — skipping")
            return

        # 1. Scan for opportunities
        scanner = WeatherArbScanner(self.config.weather_arb)
        result = await scanner.scan()

        opportunities = result.metadata.get("opportunities", [])
        log.info(
            f"WeatherArbMonitor: {result.metadata['weather_markets_found']} weather markets, "
            f"{result.metadata['noaa_signals']} with edge"
        )

        if opportunities:
            await self.event_bus.broadcast(WSEvent(
                type=WSEventType.STRATEGY_SIGNAL,
                data={
                    "strategy": "weather_arb",
                    "weather_markets_found": result.metadata["weather_markets_found"],
                    "opportunities_found": result.metadata["noaa_signals"],
                    "source": f"monitor:{self.monitor_id}",
                    "opportunities": [
                        {
                            "question": o["question"],
                            "city": o["city"],
                            "event_type": o["event_type"],
                            "target_date": o["target_date"],
                            "market_yes_price": o["market_yes_price"],
                            "noaa_probability": o["noaa_probability"],
                            "edge_pct": o["edge_pct"],
                            "suggested_side": o["suggested_side"],
                            "forecast_detail": o["forecast_detail"],
                        }
                        for o in opportunities
                    ],
                },
            ))

        # 2. Execute top opportunities
        for decision in result.decisions:
            await self._execute_decision(decision, broker)

    async def _execute_decision(self, decision, broker) -> None:
        """Submit a single weather arb trade."""
        try:
            # Get current portfolio for risk check
            portfolio = await broker.get_account()

            # Check daily loss limit
            if portfolio.equity > 0:
                daily_loss_pct = -portfolio.daily_pnl / portfolio.equity
                if daily_loss_pct >= self.config.risk.daily_loss_limit_pct:
                    log.info(
                        f"WeatherArbMonitor: daily loss limit reached "
                        f"({daily_loss_pct:.1%}), skipping {decision.symbol[:20]}"
                    )
                    return

            # Check total weather arb exposure
            total_exposure = sum(
                p.market_value
                for p in portfolio.positions
                if "weather" in p.symbol.lower() or p.platform == Platform.POLYMARKET
            )
            if total_exposure >= self.config.weather_arb.max_total_exposure_usd:
                log.info("WeatherArbMonitor: max total exposure reached, skipping")
                return

            # Compute quantity from suggested size and current price
            price = decision.suggested_size_usd  # treat as dollar size
            if decision.side == Side.BUY:
                qty = decision.suggested_size_usd
            else:
                qty = decision.suggested_size_usd

            order = OrderRequest(
                symbol=decision.symbol,
                side=decision.side,
                quantity=qty,
                order_type=OrderType.MARKET,
                platform=Platform.POLYMARKET,
            )

            if portfolio.cash < qty:
                log.info(
                    f"WeatherArbMonitor: insufficient cash "
                    f"(need ${qty:.2f}, have ${portfolio.cash:.2f})"
                )
                return

            result = await broker.submit_order(order)
            if result:
                log.info(
                    f"WeatherArbMonitor: executed weather trade "
                    f"{decision.side.value} ${qty:.2f} on {decision.symbol[:20]} | "
                    f"{decision.reasoning[:100]}"
                )
                if self.repo:
                    await self.repo.insert_trade(
                        platform="polymarket",
                        symbol=decision.symbol,
                        side=decision.side.value,
                        quantity=qty,
                        price=decision.yes_price if hasattr(decision, "yes_price") else 0.5,
                        strategy="weather_arb",
                        order_id=result.order_id,
                    )

        except Exception as e:
            log.warning(f"WeatherArbMonitor: trade execution failed: {e}")
