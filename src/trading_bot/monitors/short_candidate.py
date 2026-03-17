"""Short candidate monitor — broad market scan for short selling proposals."""

from __future__ import annotations

import asyncio
import json

from trading_bot.models import WSEvent, WSEventType
from trading_bot.monitors.base import BaseMonitor
from trading_bot.strategies.short_scorer import broad_market_short_scan, score_short
from trading_bot.utils.logging import log


class ShortCandidateMonitor(BaseMonitor):
    """Scan the broad market for short candidates and create proposals.

    Every cycle:
    1. Expire stale proposals
    2. If broad_market_scan enabled: pull S&P 500 + NASDAQ-100 universe,
       pre-filter for overbought conditions, then detail-score survivors
    3. Otherwise: score the configured watchlist
    4. Store proposals with outcome='pending_approval' for human review
    5. Broadcast via WebSocket for real-time UI
    """

    monitor_type = "short_candidate"

    def get_interval_seconds(self) -> int:
        return self.config.shorts.scan_interval_minutes * 60

    async def run_cycle(self) -> None:
        short_cfg = self.config.shorts
        if not short_cfg.enabled:
            log.info("Short scanning disabled — skipping cycle")
            return

        # 1. Expire old proposals
        expired = await self.repo.expire_old_proposals(
            "short_scorer", short_cfg.proposal_expiry_hours,
        )
        if expired:
            log.info(f"Short Monitor: expired {expired} stale proposals")

        # 2. Get scored candidates
        if short_cfg.broad_market_scan and not short_cfg.watchlist:
            # Broad market scan: S&P 500 + NASDAQ-100 → pre-filter → score
            log.info("Short Monitor: running broad market scan")
            results = await broad_market_short_scan(
                rsi_min=short_cfg.prefilter_rsi_min,
                near_high_pct=short_cfg.prefilter_near_high_pct,
                max_prefilter=short_cfg.max_prefilter_candidates,
            )
            total_scanned = "broad market"
        else:
            # Watchlist-only mode
            watchlist = short_cfg.watchlist or self.config.stocks.watchlist
            if not watchlist:
                log.info("Short Monitor: no watchlist configured")
                return
            log.info(f"Short Monitor: scanning {len(watchlist)} watchlist symbols")
            sem = asyncio.Semaphore(5)

            async def _score(sym: str):
                async with sem:
                    return await score_short(sym)

            raw = await asyncio.gather(
                *[_score(s) for s in watchlist], return_exceptions=True,
            )
            results = [r for r in raw if not isinstance(r, Exception)]
            for r in raw:
                if isinstance(r, Exception):
                    log.warning(f"Short scoring failed: {r}")
            total_scanned = f"{len(watchlist)} symbols"

        # 3. Create proposals for candidates that pass threshold
        proposals_created = 0
        for signals in results:
            passes_threshold = signals.short_score <= short_cfg.min_short_score

            signals_data = {
                "rsi_2": signals.rsi_2,
                "rsi_14": signals.rsi_14,
                "bb_pct_b": signals.bb_pct_b,
                "macd_histogram": signals.macd_histogram,
                "macd_hist_declining": signals.macd_hist_declining,
                "volume_ratio": signals.volume_ratio,
                "price_vs_sma200": signals.price_vs_sma200,
                "atr_14": signals.atr_14,
                "pe_ratio": signals.pe_ratio,
                "current_price": signals.current_price,
                "short_score": signals.short_score,
                "signal_breakdown": signals.signal_breakdown,
            }

            if passes_threshold:
                decision_id = await self.repo.insert_agent_decision(
                    agent_type="short_scorer",
                    symbol=signals.symbol,
                    action="sell",
                    confidence=min(0.95, abs(signals.short_score)),
                    reasoning=self._build_reasoning(signals),
                    signals_json=json.dumps(signals_data),
                    outcome="pending_approval",
                )
                proposals_created += 1

                await self.event_bus.broadcast(WSEvent(
                    type=WSEventType.SHORT_PROPOSAL,
                    data={
                        "decision_id": decision_id,
                        "symbol": signals.symbol,
                        "short_score": signals.short_score,
                        "current_price": signals.current_price,
                        "source": f"monitor:{self.monitor_id}",
                    },
                ))
            else:
                await self.repo.insert_agent_decision(
                    agent_type="short_scorer",
                    symbol=signals.symbol,
                    action="hold",
                    confidence=abs(signals.short_score),
                    reasoning=f"Score {signals.short_score:.2f} above threshold {short_cfg.min_short_score}",
                    signals_json=json.dumps(signals_data),
                    outcome="filtered_score",
                )

        log.info(
            f"Short Monitor: {proposals_created} proposals created "
            f"from {total_scanned} (scored {len(results)} candidates)"
        )

    def _build_reasoning(self, signals) -> str:
        parts = [f"Short score: {signals.short_score:.2f}"]
        for signal_name, weight in signals.signal_breakdown.items():
            parts.append(f"  {signal_name}: {weight:+.2f}")
        if signals.current_price:
            parts.append(f"Price: ${signals.current_price:.2f}")
        if signals.atr_14:
            parts.append(f"ATR(14): ${signals.atr_14:.2f}")
        return " | ".join(parts)
