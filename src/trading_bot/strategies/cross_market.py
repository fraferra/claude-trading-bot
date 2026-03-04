from __future__ import annotations

import asyncio
import json

from trading_bot.analysis.llm_analyst import LLMAnalyst
from trading_bot.analysis.market_data import get_polymarket_data, search_polymarket_markets
from trading_bot.config import Config
from trading_bot.models import (
    Action,
    CrossMarketOpportunity,
    LogicalRelationship,
    Side,
    StrategyResult,
    TradeDecision,
)
from trading_bot.strategies import BaseStrategy
from trading_bot.utils.logging import log


class CrossMarketScanner(BaseStrategy):
    """Finds logically linked markets with pricing violations.

    Uses the LLM to:
    1. Identify pairs of markets with logical relationships
    2. Determine probability constraints between them
    3. Check if current prices violate those constraints
    """

    name = "cross_market_logical_arbitrage"

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self.cm_config = config.strategies.cross_market
        self.analyst = LLMAnalyst(config)

    async def scan(self, search_queries: list[str] | None = None) -> StrategyResult:
        if search_queries is None:
            search_queries = ["president", "election", "winner", "nominee", "congress", "senate"]

        # Step 1: Gather candidate markets
        log.info("Fetching candidate markets for cross-market analysis...")
        all_markets = await self._gather_candidate_markets(search_queries)

        if len(all_markets) < 2:
            return StrategyResult(
                strategy_name=self.name,
                metadata={"error": "Not enough markets found", "markets_analyzed": len(all_markets)},
            )

        # Step 2: Ask LLM to identify related pairs (batched)
        log.info(f"Analyzing {len(all_markets)} markets for logical relationships...")
        relationships = await self._find_relationships(all_markets)

        # Step 3: Check each relationship for pricing violations
        opportunities: list[CrossMarketOpportunity] = []
        for rel in relationships:
            opp = await self._check_relationship(rel)
            if opp is not None and opp.edge_pct >= self.cm_config.min_edge_pct:
                opportunities.append(opp)

        opportunities.sort(key=lambda o: o.edge_pct, reverse=True)

        decisions = []
        for opp in opportunities:
            decisions.extend(opp.suggested_trades)

        return StrategyResult(
            strategy_name=self.name,
            decisions=decisions,
            metadata={
                "markets_analyzed": len(all_markets),
                "relationships_found": len(relationships),
                "opportunities_found": len(opportunities),
                "opportunities": [opp.model_dump() for opp in opportunities],
            },
        )

    async def _gather_candidate_markets(self, queries: list[str]) -> list[dict]:
        seen_ids: set[str] = set()
        results: list[dict] = []

        tasks = [search_polymarket_markets(q, limit=20) for q in queries]
        batches = await asyncio.gather(*tasks, return_exceptions=True)

        for batch in batches:
            if isinstance(batch, Exception):
                continue
            for m in batch:
                cid = m.get("condition_id", "")
                if cid and cid not in seen_ids:
                    seen_ids.add(cid)
                    results.append(m)

        return results[:self.cm_config.max_pairs_to_analyze * 2]

    async def _find_relationships(self, markets: list[dict]) -> list[LogicalRelationship]:
        from trading_bot.analysis.prompts import (
            CROSS_MARKET_RELATIONSHIP_SYSTEM,
            CROSS_MARKET_RELATIONSHIP_USER,
        )

        relationships: list[LogicalRelationship] = []
        batch_size = self.cm_config.max_markets_per_batch

        for i in range(0, len(markets), batch_size):
            batch = markets[i:i + batch_size]

            market_list_text = "\n".join(
                f"  {idx+1}. [{m['condition_id'][:16]}...] {m['question']}"
                for idx, m in enumerate(batch)
            )

            user_msg = CROSS_MARKET_RELATIONSHIP_USER.format(
                market_list=market_list_text,
                num_markets=len(batch),
            )

            try:
                response = await self.analyst._call_llm_raw(
                    CROSS_MARKET_RELATIONSHIP_SYSTEM,
                    user_msg,
                )
                parsed = self._parse_relationships(response, batch)
                relationships.extend(parsed)
            except Exception as e:
                log.warning(f"Failed to analyze batch for relationships: {e}")

            if len(relationships) >= self.cm_config.max_pairs_to_analyze:
                break

        return relationships[:self.cm_config.max_pairs_to_analyze]

    def _parse_relationships(self, llm_response: str, markets: list[dict]) -> list[LogicalRelationship]:
        json_str = llm_response.strip()
        if json_str.startswith("```"):
            lines = json_str.split("\n")
            json_str = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            log.warning("Failed to parse cross-market LLM response")
            return []

        if not isinstance(data, list):
            data = data.get("relationships", [])

        results: list[LogicalRelationship] = []
        for item in data:
            try:
                results.append(LogicalRelationship(**item))
            except Exception as e:
                log.debug(f"Skipping malformed relationship: {e}")

        return results

    async def _check_relationship(self, rel: LogicalRelationship) -> CrossMarketOpportunity | None:
        try:
            market_a = await get_polymarket_data(rel.market_a_id)
            market_b = await get_polymarket_data(rel.market_b_id)
        except Exception as e:
            log.debug(f"Could not fetch market data for relationship: {e}")
            return None

        price_a = market_a.yes_price
        price_b = market_b.yes_price

        edge = 0.0
        expected_b = price_b
        trades: list[TradeDecision] = []

        if rel.relationship_type in ("entailment", "subset"):
            # A implies B, so P(A) <= P(B)
            if price_a > price_b:
                edge = price_a - price_b
                expected_b = price_a
                trades = [
                    TradeDecision(
                        action=Action.BUY, symbol=rel.market_b_id,
                        confidence=min(0.9, 0.5 + edge * 3), side=Side.BUY,
                        reasoning=f"Cross-market {rel.relationship_type}: '{rel.market_a_question}' implies '{rel.market_b_question}', but P(A)={price_a:.2%} > P(B)={price_b:.2%}",
                        suggested_size_usd=self.cm_config.max_size_usd,
                    ),
                ]

        elif rel.relationship_type == "mutual_exclusion":
            # P(A) + P(B) <= 1.0
            if price_a + price_b > 1.0:
                edge = (price_a + price_b) - 1.0
                expected_b = 1.0 - price_a
                trades = [
                    TradeDecision(
                        action=Action.SELL, symbol=rel.market_a_id,
                        confidence=min(0.9, 0.5 + edge * 3), side=Side.SELL,
                        reasoning=f"Cross-market mutual exclusion: P(A)+P(B)={price_a+price_b:.2%} > 100%",
                        suggested_size_usd=self.cm_config.max_size_usd,
                    ),
                    TradeDecision(
                        action=Action.SELL, symbol=rel.market_b_id,
                        confidence=min(0.9, 0.5 + edge * 3), side=Side.SELL,
                        reasoning=f"Cross-market mutual exclusion: P(A)+P(B)={price_a+price_b:.2%} > 100%",
                        suggested_size_usd=self.cm_config.max_size_usd,
                    ),
                ]

        if edge < self.cm_config.min_edge_pct or not trades:
            return None

        return CrossMarketOpportunity(
            relationship=rel,
            market_a_price=price_a,
            market_b_price=price_b,
            expected_constraint_price=expected_b,
            edge_pct=round(edge, 4),
            suggested_trades=trades,
            confidence=min(0.9, 0.5 + edge * 3),
            reasoning=rel.explanation,
        )
