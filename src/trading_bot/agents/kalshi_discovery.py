"""Kalshi Discovery Agent — find interesting markets for analysis."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

from trading_bot.agents.kalshi_prompts import KALSHI_DISCOVERY_SYSTEM, KALSHI_DISCOVERY_USER
from trading_bot.analysis.llm_analyst import LLMAnalyst
from trading_bot.config import Config
from trading_bot.models import KalshiMarketData
from trading_bot.utils.logging import log


class KalshiDiscoveryAgent:
    """Discover interesting Kalshi markets for probability analysis."""

    def __init__(self, config: Config, broker) -> None:
        self.config = config
        self.broker = broker
        self.analyst = LLMAnalyst(config)
        self._kalshi_cfg = config.kalshi

    async def find_opportunities(self) -> list[KalshiMarketData]:
        """Scan Kalshi events, filter, and rank by tradability."""
        log.info("Kalshi Discovery: scanning for opportunities...")

        # 1. Fetch events across categories
        all_markets: list[KalshiMarketData] = []
        for category in self._kalshi_cfg.categories:
            try:
                events = await self.broker.get_events(
                    category=category,
                    limit=self._kalshi_cfg.max_events_to_scan // len(self._kalshi_cfg.categories),
                )
                for event in events:
                    if event.markets:
                        all_markets.extend(event.markets)
                    else:
                        # Fetch markets for this event
                        markets = await self.broker.get_markets_for_event(event.event_ticker)
                        all_markets.extend(markets)
            except Exception as e:
                log.warning(f"Failed to fetch Kalshi events for {category}: {e}")

        # 2. Filter: active, sufficient volume, not closing too soon
        filtered = self._filter_markets(all_markets)
        log.info(f"Kalshi Discovery: {len(all_markets)} total → {len(filtered)} after filtering")

        if not filtered:
            return []

        # 3. LLM ranking
        ranked = await self._rank_with_llm(filtered)
        log.info(f"Kalshi Discovery: LLM ranked {len(ranked)} markets")

        return ranked

    def _filter_markets(self, markets: list[KalshiMarketData]) -> list[KalshiMarketData]:
        """Filter markets by basic criteria."""
        filtered = []
        now = datetime.now()

        for m in markets:
            # Must be active
            if m.status and m.status not in ("active", "open"):
                continue

            # Must have some volume
            if m.volume < 10:
                continue

            # Skip already resolved
            if m.result:
                continue

            # Skip if closing within 1 hour
            if m.close_time:
                try:
                    close = datetime.fromisoformat(m.close_time.replace("Z", "+00:00"))
                    if (close.replace(tzinfo=None) - now).total_seconds() < 3600:
                        continue
                except (ValueError, TypeError):
                    pass

            filtered.append(m)

        return filtered[:50]  # Cap at 50 for LLM processing

    async def _rank_with_llm(
        self, markets: list[KalshiMarketData]
    ) -> list[KalshiMarketData]:
        """Use LLM to rank markets by trading opportunity quality."""
        # Build summary of markets for the prompt
        markets_summary = "\n".join(
            f"- {m.ticker}: \"{m.title}\" — YES: {m.yes_price:.0%}, "
            f"NO: {m.no_price:.0%}, Vol: {m.volume}, Close: {m.close_time}"
            for m in markets
        )

        user_msg = KALSHI_DISCOVERY_USER.format(
            markets_summary=markets_summary,
            current_date=datetime.now().strftime("%Y-%m-%d"),
            categories=", ".join(self._kalshi_cfg.categories),
        )

        try:
            raw = await self.analyst._call_llm_raw(KALSHI_DISCOVERY_SYSTEM, user_msg)

            # Parse response
            json_str = raw.strip()
            if json_str.startswith("```"):
                lines = json_str.split("\n")
                end = -1 if lines[-1].strip() == "```" else len(lines)
                json_str = "\n".join(lines[1:end])

            data = json.loads(json_str)
            ranked_tickers = data.get("ranked_tickers", [])

            # Map tickers back to market data
            ticker_map = {m.ticker: m for m in markets}
            ranked = [ticker_map[t] for t in ranked_tickers if t in ticker_map]

            return ranked[:15]  # Top 15

        except Exception as e:
            log.warning(f"Kalshi LLM ranking failed: {e}, returning by volume")
            # Fallback: sort by volume
            markets.sort(key=lambda m: m.volume, reverse=True)
            return markets[:15]
