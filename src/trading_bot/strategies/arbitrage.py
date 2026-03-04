from __future__ import annotations

from trading_bot.analysis.market_data import get_all_events, parse_event_to_model
from trading_bot.config import Config
from trading_bot.models import (
    Action,
    ArbitrageOpportunity,
    EventData,
    Side,
    StrategyResult,
    TradeDecision,
)
from trading_bot.strategies import BaseStrategy
from trading_bot.utils.logging import log


class ArbitrageScanner(BaseStrategy):
    """Scans for multi-outcome arbitrage across Polymarket events.

    Pure computation — no LLM calls needed.

    For each event with N mutually exclusive outcomes:
    - Sum the YES prices of all outcomes
    - If sum < 1.0: buy all YES outcomes -> guaranteed profit of (1.0 - sum)
    - If sum > 1.0: sell all YES outcomes -> profit of (sum - 1.0)
    - Only flag when edge > min_edge_pct + fees
    """

    name = "multi_outcome_arbitrage"

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self.arb_config = config.strategies.arbitrage

    async def scan(self) -> StrategyResult:
        log.info(f"Scanning up to {self.arb_config.max_events_to_scan} events for arbitrage...")

        raw_events = await get_all_events(limit=self.arb_config.max_events_to_scan)
        events = [parse_event_to_model(e) for e in raw_events]

        opportunities: list[ArbitrageOpportunity] = []
        for event in events:
            opp = self._check_event(event)
            if opp is not None:
                opportunities.append(opp)

        opportunities.sort(key=lambda o: o.edge_pct, reverse=True)

        decisions = []
        for opp in opportunities:
            decisions.extend(self._opportunity_to_decisions(opp))

        return StrategyResult(
            strategy_name=self.name,
            decisions=decisions,
            metadata={
                "events_scanned": len(events),
                "opportunities_found": len(opportunities),
                "opportunities": [opp.model_dump() for opp in opportunities],
            },
        )

    def _check_event(self, event: EventData) -> ArbitrageOpportunity | None:
        outcomes = event.outcomes

        if len(outcomes) < self.arb_config.min_outcomes:
            return None
        if len(outcomes) > self.arb_config.max_outcomes:
            return None

        # Filter out outcomes with zero liquidity
        valid_outcomes = [o for o in outcomes if o.liquidity > 0 and o.yes_price > 0]
        if len(valid_outcomes) < 2:
            return None

        price_sum = sum(o.yes_price for o in valid_outcomes)

        raw_edge = abs(1.0 - price_sum)
        total_fees = self.arb_config.fee_estimate_pct * len(valid_outcomes)
        net_edge = raw_edge - total_fees

        if net_edge < self.arb_config.min_edge_pct:
            return None

        direction = "buy_all" if price_sum < 1.0 else "sell_all"

        return ArbitrageOpportunity(
            event_id=event.event_id,
            event_title=event.title,
            outcomes=valid_outcomes,
            price_sum=round(price_sum, 4),
            edge_pct=round(net_edge, 4),
            direction=direction,
            estimated_profit_per_dollar=round(net_edge, 4),
            fee_estimate_pct=self.arb_config.fee_estimate_pct,
        )

    def _opportunity_to_decisions(self, opp: ArbitrageOpportunity) -> list[TradeDecision]:
        decisions = []
        per_leg_size = self.arb_config.max_size_per_leg_usd

        for outcome in opp.outcomes:
            action = Action.BUY if opp.direction == "buy_all" else Action.SELL
            side = Side.BUY if action == Action.BUY else Side.SELL

            decisions.append(TradeDecision(
                action=action,
                symbol=outcome.condition_id,
                confidence=min(0.95, 0.5 + opp.edge_pct * 5),
                reasoning=(
                    f"Arbitrage: {opp.event_title} | "
                    f"Price sum={opp.price_sum:.4f}, edge={opp.edge_pct:.2%} | "
                    f"{opp.direction} all outcomes"
                ),
                suggested_size_usd=per_leg_size,
                side=side,
            ))

        return decisions
