"""Discovery Agent — scans news to find candidate stocks for research."""

from __future__ import annotations

import asyncio
import json

from trading_bot.agents.prompts import DISCOVERY_SYSTEM, DISCOVERY_USER
from trading_bot.analysis.llm_analyst import LLMAnalyst
from trading_bot.analysis.market_data import get_news
from trading_bot.config import Config
from trading_bot.utils.logging import log


class DiscoveryAgent:
    """Find candidate stocks from current market news and signals."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.analyst = LLMAnalyst(config)
        self.max_candidates = config.research_agent.max_candidates

    async def find_candidates(self) -> list[tuple[str, str]]:
        """Scan news and return (symbol, reason) pairs for research.

        Always includes watchlist symbols as baseline candidates.
        """
        # Gather news from multiple angles
        market_news, earnings_news, sector_news = await asyncio.gather(
            get_news("stock market movers today", limit=15),
            get_news("earnings surprises stocks", limit=10),
            get_news("sector rotation stocks investing", limit=10),
        )

        market_text = "\n".join(
            f"- [{n.source}] {n.title}" for n in market_news
        ) if market_news else "No market news available."

        earnings_text = "\n".join(
            f"- [{n.source}] {n.title}" for n in earnings_news
        ) if earnings_news else "No earnings news available."

        sector_text = "\n".join(
            f"- [{n.source}] {n.title}" for n in sector_news
        ) if sector_news else "No sector news available."

        watchlist_str = ", ".join(self.config.stocks.watchlist)

        user_msg = DISCOVERY_USER.format(
            market_news=market_text,
            earnings_news=earnings_text,
            sector_news=sector_text,
            watchlist=watchlist_str,
        )

        try:
            raw = await self.analyst._call_llm_raw(DISCOVERY_SYSTEM, user_msg)
            json_str = _strip_markdown(raw)
            data = json.loads(json_str)
            candidates_raw = data.get("candidates", [])

            candidates = []
            seen = set()
            for c in candidates_raw:
                sym = c.get("symbol", "").upper().strip()
                reason = c.get("reason", "")
                if sym and sym not in seen:
                    seen.add(sym)
                    candidates.append((sym, reason))

            # Always include watchlist symbols not already discovered
            for sym in self.config.stocks.watchlist:
                if sym not in seen:
                    seen.add(sym)
                    candidates.append((sym, "Watchlist stock"))

            candidates = candidates[:self.max_candidates]
            log.info(f"Discovery found {len(candidates)} candidates")
            return candidates

        except Exception as e:
            log.warning(f"Discovery agent failed: {e}")
            # Fallback to watchlist
            return [(s, "Watchlist stock (discovery fallback)") for s in self.config.stocks.watchlist]

    @property
    def source_queries(self) -> list[str]:
        return [
            "stock market movers today",
            "earnings surprises stocks",
            "sector rotation stocks investing",
        ]


def _strip_markdown(text: str) -> str:
    """Strip markdown code fences from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        end = -1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[1:end])
    return text
