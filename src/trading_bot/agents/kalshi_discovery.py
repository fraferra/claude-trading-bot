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

        # 1. Fetch open events — don't filter by series_ticker because config
        #    categories are generic names (politics, economics) not Kalshi
        #    series tickers (KXFEDRATE, KXINX, etc.)
        all_markets: list[KalshiMarketData] = []
        try:
            events = await self.broker.get_events(
                limit=self._kalshi_cfg.max_events_to_scan,
            )
            for event in events:
                if event.markets:
                    all_markets.extend(event.markets)
                else:
                    try:
                        markets = await self.broker.get_markets_for_event(event.event_ticker)
                        all_markets.extend(markets)
                    except Exception as me:
                        log.debug(f"Failed to fetch markets for {event.event_ticker}: {me}")
        except Exception as e:
            log.warning(f"Failed to fetch Kalshi events: {e}")

        # 2. Filter: active, sufficient volume, not closing too soon
        filtered = self._filter_markets(all_markets)
        log.info(f"Kalshi Discovery: {len(all_markets)} total → {len(filtered)} after filtering")

        if not filtered:
            return []

        # 3. LLM ranking
        ranked = await self._rank_with_llm(filtered)
        log.info(f"Kalshi Discovery: LLM ranked {len(ranked)} markets")

        return ranked

    # Keywords in market titles that signal long-term / annual / multi-month bets.
    # These are blocked regardless of Kalshi's close_time field.
    _LONG_TERM_KEYWORDS = [
        "end of year", "by year-end", "year-end",
        "annual", "by december", "by january",
        "before 2025", "before 2026", "before 2027", "before 2028",
        "by 2025", "by 2026", "by 2027", "by 2028", "by 2029", "by 2030",
        "in 2025", "in 2026", "in 2027", "in 2028",
        "this year", "next year",
        "during 2025", "during 2026", "during 2027",
        "term ends", "term start", "presidency",
    ]

    def _filter_markets(self, markets: list[KalshiMarketData]) -> list[KalshiMarketData]:
        """Filter markets by basic criteria including strict time horizon.

        Only allows markets expected to resolve within max_days_until_close
        (default 90 days). Markets with far-future placeholder dates (2070,
        2099) are event-triggered; they are allowed only if their title does
        not indicate a long-term outcome.
        """
        filtered = []
        from datetime import timezone
        now = datetime.now(timezone.utc)
        max_days = self._kalshi_cfg.max_days_until_close
        max_seconds = max_days * 86400
        # Dates beyond this are Kalshi placeholders (2070, 2099, etc.)
        placeholder_cutoff = 10 * 365 * 86400  # 10 years

        too_soon = 0
        too_far = 0
        too_far_title = 0
        low_vol = 0
        resolved = 0
        inactive = 0

        for m in markets:
            # Must be active
            if m.status and m.status not in ("active", "open"):
                inactive += 1
                continue

            # Must have some volume
            if m.volume < 10:
                low_vol += 1
                continue

            # Skip already resolved
            if m.result:
                resolved += 1
                continue

            # Title-based filter: reject obviously long-term bets regardless of close_time
            title_lower = (m.title or "").lower()
            if any(kw in title_lower for kw in self._LONG_TERM_KEYWORDS):
                too_far_title += 1
                continue

            # Time-based filtering
            if m.close_time:
                try:
                    close = datetime.fromisoformat(m.close_time.replace("Z", "+00:00"))
                    if close.tzinfo is None:
                        close = close.replace(tzinfo=timezone.utc)
                    time_until_close = (close - now).total_seconds()
                    # Skip if closing within 1 hour
                    if time_until_close < 3600:
                        too_soon += 1
                        continue
                    # Placeholder far-future dates (2070, 2099) — event-triggered.
                    # Title filter above already blocked long-term ones, so remaining
                    # placeholder-date markets are likely near-term event triggers
                    # (e.g., "Will the Fed raise rates at the next meeting?")
                    if time_until_close > placeholder_cutoff:
                        pass  # Event-triggered, title already vetted
                    elif time_until_close > max_seconds:
                        too_far += 1
                        continue
                except (ValueError, TypeError):
                    pass

            filtered.append(m)

        log.info(
            f"Kalshi filter breakdown: inactive={inactive}, low_vol={low_vol}, "
            f"resolved={resolved}, too_soon={too_soon}, too_far={too_far}, "
            f"too_far_title={too_far_title}, "
            f"passed={len(filtered)} (max_days={max_days})"
        )

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

        max_days = self._kalshi_cfg.max_days_until_close
        system_prompt = KALSHI_DISCOVERY_SYSTEM.format(max_days=max_days)
        user_msg = KALSHI_DISCOVERY_USER.format(
            markets_summary=markets_summary,
            current_date=datetime.now().strftime("%Y-%m-%d"),
            categories=", ".join(self._kalshi_cfg.categories),
            max_days=max_days,
        )

        try:
            raw = await self.analyst._call_llm_raw(system_prompt, user_msg)

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
