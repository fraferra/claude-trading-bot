"""Strategy Review Monitor — runs weekly strategy self-review."""

from __future__ import annotations

import json

from trading_bot.agents.strategist import StrategistAgent
from trading_bot.models import WSEvent, WSEventType
from trading_bot.monitors.base import BaseMonitor
from trading_bot.utils.logging import log


class StrategyReviewMonitor(BaseMonitor):
    """Weekly strategy review that analyzes performance and adjusts parameters."""

    monitor_type = "strategy_review"

    def get_interval_seconds(self) -> int:
        return 7 * 24 * 3600  # Weekly

    async def run_cycle(self) -> None:
        strategist = StrategistAgent(self.config, self.repo)

        log.info(f"Monitor {self.monitor_id}: Running weekly strategy review")
        memo = await strategist.weekly_review()

        # Apply parameter changes if any
        if memo.parameter_changes:
            strategist.apply_changes(memo)
            log.info(f"Monitor {self.monitor_id}: Applied parameter changes: {memo.parameter_changes}")

        # Save memo to DB
        await self.repo.insert_strategy_memo(
            period_start=memo.period_start.isoformat(),
            period_end=memo.period_end.isoformat(),
            total_return_pct=memo.total_return_pct,
            win_rate=memo.win_rate,
            lessons_json=json.dumps(memo.lessons),
            parameter_changes_json=json.dumps(memo.parameter_changes),
            next_week_focus_json=json.dumps(memo.next_week_focus),
        )

        # Broadcast
        await self.event_bus.broadcast(WSEvent(
            type=WSEventType.STRATEGY_SIGNAL,
            data={
                "source": f"monitor:{self.monitor_id}",
                "type": "strategy_review",
                "total_return_pct": memo.total_return_pct,
                "win_rate": memo.win_rate,
                "parameter_changes": memo.parameter_changes,
                "lessons": memo.lessons,
            },
        ))

        log.info(
            f"Monitor {self.monitor_id}: Review complete — "
            f"return={memo.total_return_pct:+.1f}%, win_rate={memo.win_rate:.0%}"
        )
