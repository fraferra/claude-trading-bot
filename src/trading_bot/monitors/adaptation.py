"""Strategy adaptation — adjusts monitor parameters based on recent performance."""

from __future__ import annotations

from trading_bot.config import MonitorConfig
from trading_bot.db.repository import Repository
from trading_bot.utils.logging import log


class StrategyAdaptation:
    """Adjusts position_scale and min_edge based on trade outcomes."""

    def __init__(self, config: MonitorConfig, repo: Repository) -> None:
        self.config = config
        self.repo = repo

    async def evaluate_and_adapt(self, monitor_id: str) -> dict:
        """Check recent trades and adjust parameters. Returns summary."""
        if not self.config.adaptation_enabled:
            return {"adapted": False}

        recent = await self.repo.get_recent_monitor_trades(
            monitor_id, limit=self.config.adaptation_lookback_trades
        )
        if len(recent) < 5:
            return {"adapted": False, "reason": "not_enough_trades"}

        closed = [t for t in recent if t.get("pnl") is not None]
        if len(closed) < 5:
            return {"adapted": False, "reason": "not_enough_closed_trades"}

        total_pnl = sum(t["pnl"] for t in closed)
        total_cost = sum(
            abs(t.get("entry_price", 0) * t.get("quantity", t.get("trade_quantity", 1)))
            for t in closed
        )
        pnl_pct = total_pnl / total_cost if total_cost > 0 else 0.0
        wins = sum(1 for t in closed if t["pnl"] > 0)
        win_rate = wins / len(closed)

        state = await self.repo.get_monitor_state(monitor_id)
        if not state:
            return {"adapted": False, "reason": "no_state"}

        current_scale = state["current_position_scale"]
        current_min_edge = state["current_min_edge"]
        adjustments = {}

        # Adapt position scale
        if pnl_pct < self.config.adaptation_loss_threshold:
            new_scale = max(
                self.config.adaptation_min_scale,
                current_scale - self.config.adaptation_scale_step,
            )
            if new_scale != current_scale:
                adjustments["position_scale"] = {"old": current_scale, "new": new_scale}
                current_scale = new_scale
        elif pnl_pct > self.config.adaptation_win_threshold:
            new_scale = min(
                self.config.adaptation_max_scale,
                current_scale + self.config.adaptation_scale_step,
            )
            if new_scale != current_scale:
                adjustments["position_scale"] = {"old": current_scale, "new": new_scale}
                current_scale = new_scale

        # Adapt minimum edge
        if win_rate < 0.50 and current_min_edge < 0.20:
            new_edge = min(0.20, current_min_edge + 0.01)
            adjustments["min_edge"] = {"old": current_min_edge, "new": new_edge}
            current_min_edge = new_edge
        elif win_rate > 0.70 and current_min_edge > 0.02:
            new_edge = max(0.02, current_min_edge - 0.005)
            adjustments["min_edge"] = {"old": current_min_edge, "new": new_edge}
            current_min_edge = new_edge

        if adjustments:
            await self.repo.update_monitor_adaptation(
                monitor_id, current_scale, current_min_edge
            )
            log.info(f"Monitor {monitor_id} adapted: {adjustments}")

        return {
            "adapted": bool(adjustments),
            "pnl_pct": round(pnl_pct, 4),
            "win_rate": round(win_rate, 4),
            "recent_trades": len(closed),
            "adjustments": adjustments,
        }
