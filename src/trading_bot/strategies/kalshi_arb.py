"""Kalshi multi-outcome arbitrage scanner — pure math, no LLM calls.

For Kalshi events with N mutually exclusive and collectively exhaustive (MECE)
outcomes (e.g. Fed rate buckets, CPI ranges, economic indicator bins):
  - sum(YES prices) should equal exactly $1.00
  - If sum < 1.0: buy all YES outcomes → guaranteed profit of (1.0 - sum)
  - If sum > 1.0: sell all YES outcomes → guaranteed profit of (sum - 1.0)

Only trade when net_edge (after fees) >= min_edge_pct.
"""

from __future__ import annotations

import asyncio

from trading_bot.models import (
    Action,
    KalshiEventData,
    Side,
    StrategyResult,
    TradeDecision,
)
from trading_bot.utils.logging import log


class KalshiArbitrageScanner:
    """Scans Kalshi events for multi-outcome (MECE) arbitrage opportunities."""

    name = "kalshi_arbitrage"

    def __init__(self, config) -> None:
        # config is KalshiArbConfig
        self.config = config

    async def scan(self, broker) -> StrategyResult:
        """Fetch all open Kalshi events and find MECE arbitrage opportunities."""
        log.info(
            f"KalshiArb Scanner: fetching up to {self.config.max_events_to_scan} events..."
        )

        events = await broker.get_events(limit=self.config.max_events_to_scan)
        log.info(f"KalshiArb Scanner: got {len(events)} events from API")

        # Enrich events that have no embedded markets
        events = await self._enrich_events(events, broker)

        opportunities: list[dict] = []
        for event in events:
            opp = self._check_event(event)
            if opp is not None:
                opportunities.append(opp)

        opportunities.sort(key=lambda o: o["net_edge"], reverse=True)

        # Build flat decisions list + keep grouped structure for the monitor
        all_decisions: list[TradeDecision] = []
        for opp in opportunities:
            all_decisions.extend(opp["decisions"])

        log.info(
            f"KalshiArb Scanner: {len(events)} events scanned, "
            f"{len(opportunities)} opportunities found"
        )

        return StrategyResult(
            strategy_name=self.name,
            decisions=all_decisions,
            metadata={
                "events_scanned": len(events),
                "opportunities_found": len(opportunities),
                "opportunity_groups": [
                    {
                        "event_ticker": o["event_ticker"],
                        "event_title": o["event_title"],
                        "price_sum": o["price_sum"],
                        "net_edge": o["net_edge"],
                        "direction": o["direction"],
                        "n_legs": o["n_legs"],
                        "tickers": o["tickers"],
                        "decisions": o["decisions"],
                    }
                    for o in opportunities
                ],
            },
        )

    async def _enrich_events(
        self, events: list[KalshiEventData], broker
    ) -> list[KalshiEventData]:
        """Fetch markets for events that have too few embedded markets."""
        sem = asyncio.Semaphore(5)

        async def _enrich(event: KalshiEventData) -> KalshiEventData:
            if len(event.markets) >= self.config.min_markets:
                return event
            async with sem:
                try:
                    markets = await broker.get_markets_for_event(event.event_ticker)
                    return KalshiEventData(
                        event_ticker=event.event_ticker,
                        title=event.title,
                        category=event.category,
                        markets=markets,
                    )
                except Exception as e:
                    log.debug(f"KalshiArb: failed to enrich {event.event_ticker}: {e}")
                    return event

        enriched = await asyncio.gather(*[_enrich(e) for e in events])
        return list(enriched)

    def _check_event(self, event: KalshiEventData) -> dict | None:
        """Check a single event for MECE arbitrage opportunity.

        Returns an opportunity dict or None.
        """
        # Filter to open, liquid markets with valid prices
        valid_markets = [
            m for m in event.markets
            if m.status == "open"
            and m.volume > 0
            and 0.01 <= m.yes_price <= 0.99
        ]

        n = len(valid_markets)
        if n < self.config.min_markets or n > self.config.max_markets:
            return None

        # All markets in the MECE set must survive filtering; partial sets produce phantom arbs
        if n != len(event.markets):
            log.debug(
                f"Skipping {event.event_ticker}: {len(event.markets) - n} "
                f"market(s) excluded due to filtering"
            )
            return None

        price_sum = sum(m.yes_price for m in valid_markets)

        # Sanity bounds: if prices don't vaguely sum to 1.0, skip
        # (likely not a MECE set — e.g. overlapping conditions)
        if not (0.50 <= price_sum <= 1.50):
            return None

        raw_edge = abs(1.0 - price_sum)
        total_fees = self.config.fee_estimate_pct * n
        net_edge = raw_edge - total_fees

        if net_edge < self.config.min_edge_pct:
            return None

        direction = "buy_all" if price_sum < 1.0 else "sell_all"

        decisions = self._build_decisions(event, valid_markets, direction, net_edge)
        tickers = [m.ticker for m in valid_markets]

        log.info(
            f"KalshiArb opportunity: {event.title[:60]} | "
            f"sum={price_sum:.4f} edge={net_edge:.2%} {direction} "
            f"({n} legs: {', '.join(tickers)})"
        )

        return {
            "event_ticker": event.event_ticker,
            "event_title": event.title,
            "price_sum": round(price_sum, 4),
            "net_edge": round(net_edge, 4),
            "direction": direction,
            "n_legs": n,
            "tickers": tickers,
            "decisions": decisions,
        }

    def _build_decisions(self, event, markets, direction: str, net_edge: float) -> list[TradeDecision]:
        """Convert an opportunity into a list of TradeDecision (one per leg)."""
        n = len(markets)
        # Conservative sizing: cap per-leg size so total exposure stays within limit
        per_leg_usd = min(
            self.config.max_size_per_leg_usd,
            self.config.max_total_exposure_usd / n,
        )
        confidence = min(0.99, 0.70 + net_edge * 3)

        decisions = []
        for market in markets:
            if direction == "buy_all":
                action = Action.BUY
                side = Side.BUY
            else:
                action = Action.SELL
                side = Side.SELL

            decisions.append(TradeDecision(
                action=action,
                symbol=market.ticker,
                confidence=confidence,
                reasoning=(
                    f"KalshiArb: {event.title[:80]} | "
                    f"price_sum={sum(m.yes_price for m in markets):.4f} "
                    f"net_edge={net_edge:.2%} | {direction} all {n} legs"
                ),
                suggested_size_usd=per_leg_usd,
                side=side,
            ))

        return decisions
