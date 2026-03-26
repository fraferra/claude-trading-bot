"""Cross-platform arbitrage scanner: Polymarket ↔ Kalshi.

Detects when the same real-world event is priced differently on both platforms,
enabling a risk-free (modulo execution risk) arbitrage by buying the cheap side
on each platform and holding to resolution.

Strategy logic:
  For a matched market pair (same event on both platforms):
    p_yes = Polymarket YES price
    k_yes = Kalshi YES price

    Arb A (buy both YES): p_yes + k_no < 1.0 - fees → buy Poly YES + buy Kalshi NO
    Arb B (buy both NO):  p_no + k_yes < 1.0 - fees → buy Poly NO + buy Kalshi YES

  If combined cost < (1.0 - total_fees), guaranteed profit at resolution.

Pure math — no LLM calls.
"""

from __future__ import annotations

import difflib
import re
import time
from dataclasses import dataclass, field

from trading_bot.analysis.market_data import get_all_events
from trading_bot.config import CrossPlatformArbConfig
from trading_bot.models import Action, Side, StrategyResult, TradeDecision
from trading_bot.utils.logging import log


@dataclass
class CrossPlatformOpportunity:
    """A detected cross-platform arbitrage opportunity."""
    direction: str                   # 'buy_poly_yes_kalshi_no' | 'buy_poly_no_kalshi_yes'
    poly_token_id: str
    poly_condition_id: str
    poly_question: str
    poly_price: float                # price of the side we're buying on Polymarket
    kalshi_ticker: str
    kalshi_question: str
    kalshi_price: float              # price of the side we're buying on Kalshi
    combined_cost: float             # poly_price + kalshi_price
    gross_edge: float                # 1.0 - combined_cost
    net_edge: float                  # gross_edge - total fees
    match_score: float               # fuzzy match score (0-1)


@dataclass
class MarketCache:
    """Short-lived cache of matched market pairs."""
    pairs: list[tuple[dict, dict]] = field(default_factory=list)
    built_at: float = 0.0

    def is_fresh(self, ttl: int) -> bool:
        return (time.time() - self.built_at) < ttl


# Module-level cache shared across scanner instances
_market_cache = MarketCache()


class CrossPlatformArbScanner:
    """Scans for price discrepancies between Polymarket and Kalshi."""

    name = "cross_platform_arb"

    def __init__(self, config: CrossPlatformArbConfig) -> None:
        self.config = config

    async def scan(self, poly_broker, kalshi_broker) -> StrategyResult:
        """Fetch markets from both platforms and find cross-platform arb opportunities."""
        global _market_cache

        # 1. Build/refresh matched market pairs
        if not _market_cache.is_fresh(self.config.market_cache_ttl_seconds):
            poly_events = await get_all_events(limit=500)
            kalshi_events = await kalshi_broker.get_events(limit=200)
            _market_cache.pairs = _match_markets(
                poly_events, kalshi_events, self.config.fuzzy_match_threshold
            )
            _market_cache.built_at = time.time()
            log.info(
                f"CrossPlatformArb: rebuilt market cache, "
                f"{len(_market_cache.pairs)} matched pairs"
            )

        if not _market_cache.pairs:
            return StrategyResult(
                strategy_name=self.name,
                decisions=[],
                metadata={"pairs_matched": 0, "opportunities_found": 0},
            )

        # 2. Scan matched pairs for price discrepancies
        opportunities: list[CrossPlatformOpportunity] = []
        for poly_market, kalshi_market in _market_cache.pairs:
            try:
                opps = await self._check_pair(
                    poly_market, kalshi_market, poly_broker, kalshi_broker
                )
                opportunities.extend(opps)
            except Exception as e:
                log.debug(f"CrossPlatformArb pair check failed: {e}")

        # Sort by net edge descending
        opportunities.sort(key=lambda o: o.net_edge, reverse=True)

        decisions = []
        for opp in opportunities:
            decisions.extend(self._opportunity_to_decisions(opp))

        log.info(
            f"CrossPlatformArb scan: {len(_market_cache.pairs)} pairs checked, "
            f"{len(opportunities)} opportunities found"
        )

        return StrategyResult(
            strategy_name=self.name,
            decisions=decisions,
            metadata={
                "pairs_matched": len(_market_cache.pairs),
                "opportunities_found": len(opportunities),
                "opportunities": [
                    {
                        "direction": o.direction,
                        "poly_question": o.poly_question[:60],
                        "kalshi_question": o.kalshi_question[:60],
                        "combined_cost": round(o.combined_cost, 4),
                        "net_edge": round(o.net_edge, 4),
                        "match_score": round(o.match_score, 3),
                    }
                    for o in opportunities[:10]
                ],
            },
        )

    async def _check_pair(
        self, poly_market: dict, kalshi_market, poly_broker, kalshi_broker
    ) -> list[CrossPlatformOpportunity]:
        """Check a single matched pair for arbitrage opportunities."""
        opportunities = []

        # Extract Polymarket prices from the market dict
        # poly_market is a raw Gamma API market dict
        tokens = poly_market.get("tokens", [])
        poly_yes_price = 0.5
        poly_token_yes = ""
        for token in tokens:
            outcome = token.get("outcome", "").lower()
            price = float(token.get("price", 0.5))
            if outcome == "yes":
                poly_yes_price = price
                poly_token_yes = token.get("token_id", "")

        # Derive NO price from YES price to ensure internal consistency
        poly_no_price = 1.0 - poly_yes_price

        # Get Kalshi prices (fresh quote)
        try:
            kalshi_yes_price = await kalshi_broker.get_quote(kalshi_market.ticker)
            kalshi_no_price = 1.0 - kalshi_yes_price
        except Exception:
            return []

        if not (0.01 <= poly_yes_price <= 0.99 and 0.01 <= kalshi_yes_price <= 0.99):
            return []

        # Check volume filter
        poly_volume = float(poly_market.get("volume", 0))
        if poly_volume < self.config.min_volume_usd:
            return []

        total_fees = self.config.fee_estimate_poly_pct + self.config.fee_estimate_kalshi_pct
        poly_cond_id = poly_market.get("conditionId", poly_market.get("condition_id", ""))
        match_score = poly_market.get("_match_score", 0.0)

        # Arb A: buy Poly YES + buy Kalshi NO
        cost_a = poly_yes_price + kalshi_no_price
        net_a = (1.0 - cost_a) - total_fees
        if net_a >= self.config.min_net_edge_pct and poly_token_yes:
            opportunities.append(CrossPlatformOpportunity(
                direction="buy_poly_yes_kalshi_no",
                poly_token_id=poly_token_yes,
                poly_condition_id=poly_cond_id,
                poly_question=poly_market.get("question", ""),
                poly_price=poly_yes_price,
                kalshi_ticker=kalshi_market.ticker,
                kalshi_question=kalshi_market.title,
                kalshi_price=kalshi_no_price,
                combined_cost=round(cost_a, 4),
                gross_edge=round(1.0 - cost_a, 4),
                net_edge=round(net_a, 4),
                match_score=match_score,
            ))

        # Arb B: buy Poly NO + buy Kalshi YES
        # For Poly NO, we need the NO token_id
        poly_token_no = ""
        for token in tokens:
            if token.get("outcome", "").lower() == "no":
                poly_token_no = token.get("token_id", "")
                break

        cost_b = poly_no_price + kalshi_yes_price
        net_b = (1.0 - cost_b) - total_fees
        if net_b >= self.config.min_net_edge_pct and poly_token_no:
            opportunities.append(CrossPlatformOpportunity(
                direction="buy_poly_no_kalshi_yes",
                poly_token_id=poly_token_no,
                poly_condition_id=poly_cond_id,
                poly_question=poly_market.get("question", ""),
                poly_price=poly_no_price,
                kalshi_ticker=kalshi_market.ticker,
                kalshi_question=kalshi_market.title,
                kalshi_price=kalshi_yes_price,
                combined_cost=round(cost_b, 4),
                gross_edge=round(1.0 - cost_b, 4),
                net_edge=round(net_b, 4),
                match_score=match_score,
            ))

        return opportunities

    def _opportunity_to_decisions(
        self, opp: CrossPlatformOpportunity
    ) -> list[TradeDecision]:
        """Convert a cross-platform opportunity into two TradeDecision objects."""
        confidence = min(0.95, 0.60 + opp.net_edge * 5)
        size_usd = self.config.max_size_per_leg_usd

        # Polymarket leg
        poly_action = Action.BUY
        poly_side = Side.BUY
        poly_reasoning = (
            f"CrossPlatformArb [{opp.direction}] | "
            f"Poly: {opp.poly_question[:50]} @ {opp.poly_price:.4f} | "
            f"Kalshi: {opp.kalshi_question[:50]} @ {opp.kalshi_price:.4f} | "
            f"combined_cost={opp.combined_cost:.4f} net_edge={opp.net_edge:.2%}"
        )

        # Kalshi leg side depends on direction
        if opp.direction == "buy_poly_yes_kalshi_no":
            kalshi_side = Side.SELL   # Sell YES = buy NO on Kalshi
        else:
            kalshi_side = Side.BUY    # Buy YES on Kalshi

        # Encode routing info in the reasoning prefix so the monitor can parse it
        poly_tag = f"[XPLAT|poly|{opp.direction}|kalshi={opp.kalshi_ticker}]"
        kalshi_tag = (
            f"[XPLAT|kalshi|{opp.direction}"
            f"|poly={opp.poly_token_id}|kprice={opp.kalshi_price:.4f}]"
        )

        poly_decision = TradeDecision(
            action=poly_action,
            symbol=opp.poly_token_id,
            confidence=confidence,
            reasoning=f"{poly_tag} {poly_reasoning}",
            suggested_size_usd=size_usd,
            side=poly_side,
        )

        kalshi_decision = TradeDecision(
            action=poly_action,
            symbol=opp.kalshi_ticker,
            confidence=confidence,
            reasoning=f"{kalshi_tag} {poly_reasoning}",
            suggested_size_usd=size_usd,
            side=kalshi_side,
        )

        return [poly_decision, kalshi_decision]


# --- Market matching helpers ---

def _normalize_title(title: str) -> str:
    """Normalize a market title for fuzzy comparison."""
    title = title.lower()
    # Remove common date patterns (Jan 2025, Q1 2025, etc.)
    title = re.sub(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{4}\b", "", title)
    title = re.sub(r"\b(q[1-4]|h[12])\s+\d{4}\b", "", title)
    title = re.sub(r"\b20\d{2}\b", "", title)
    # Remove punctuation, extra whitespace
    title = re.sub(r"[^\w\s]", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title


def _match_markets(
    poly_events: list[dict],
    kalshi_events: list,
    threshold: float,
) -> list[tuple[dict, object]]:
    """Match Polymarket markets to Kalshi markets by title similarity.

    Returns list of (poly_market_dict, kalshi_market_data) pairs.
    """
    # Flatten Polymarket events → individual markets
    poly_markets: list[dict] = []
    for event in poly_events:
        for market in event.get("markets", []):
            question = market.get("question", "")
            if question:
                poly_markets.append(market)

    # Flatten Kalshi events → individual markets
    kalshi_markets: list = []
    for event in kalshi_events:
        for market in getattr(event, "markets", []) or []:
            if getattr(market, "ticker", ""):
                kalshi_markets.append(market)

    if not poly_markets or not kalshi_markets:
        return []

    # Pre-compute normalized titles
    poly_normalized = [_normalize_title(m.get("question", "")) for m in poly_markets]
    kalshi_normalized = [
        _normalize_title(getattr(m, "title", "") or getattr(m, "ticker", ""))
        for m in kalshi_markets
    ]

    matched: list[tuple[dict, object]] = []
    seen_kalshi: set[str] = set()

    for poly_idx, poly_norm in enumerate(poly_normalized):
        if not poly_norm:
            continue

        best_score = 0.0
        best_kalshi_idx = -1

        for kalshi_idx, kalshi_norm in enumerate(kalshi_normalized):
            if not kalshi_norm:
                continue
            ticker = getattr(kalshi_markets[kalshi_idx], "ticker", "")
            if ticker in seen_kalshi:
                continue

            score = difflib.SequenceMatcher(None, poly_norm, kalshi_norm).ratio()
            if score > best_score:
                best_score = score
                best_kalshi_idx = kalshi_idx

        if best_score >= threshold and best_kalshi_idx >= 0:
            poly_market = dict(poly_markets[poly_idx])
            poly_market["_match_score"] = best_score
            kalshi_market = kalshi_markets[best_kalshi_idx]
            matched.append((poly_market, kalshi_market))
            seen_kalshi.add(getattr(kalshi_market, "ticker", ""))

    return matched
