"""Strategist Agent — weekly strategy review and parameter adaptation."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from trading_bot.agents.prompts import STRATEGIST_SYSTEM, STRATEGIST_USER
from trading_bot.analysis.llm_analyst import LLMAnalyst
from trading_bot.config import Config
from trading_bot.db.repository import Repository
from trading_bot.models import StrategyMemo
from trading_bot.utils.logging import log


class StrategistAgent:
    """Weekly self-review: analyzes performance and adjusts parameters."""

    def __init__(self, config: Config, repo: Repository) -> None:
        self.config = config
        self.repo = repo
        self.analyst = LLMAnalyst(config)
        self._model = config.llm.strategist_model

    async def weekly_review(self) -> StrategyMemo:
        """Analyze past week's performance and suggest parameter changes."""
        period_end = datetime.now()
        period_start = period_end - timedelta(days=7)

        # Fetch recent trades
        trades = await self.repo.get_trades(limit=100, source="research_agent")
        # Filter to last 7 days
        recent_trades = []
        for t in trades:
            try:
                trade_time = datetime.fromisoformat(t["created_at"])
                if trade_time >= period_start:
                    recent_trades.append(t)
            except (ValueError, KeyError):
                continue

        if not recent_trades:
            return StrategyMemo(
                period_start=period_start,
                period_end=period_end,
                lessons=["No trades executed this period."],
                next_week_focus=["Continue monitoring for opportunities."],
            )

        # Build trades summary
        trades_summary = "\n".join(
            f"  {t['symbol']}: {t['side']} {t['quantity']:.2f} @ ${t.get('filled_price', 0):.2f} "
            f"(confidence: {t.get('confidence', 0):.0%}) — {t.get('reasoning', 'N/A')}"
            for t in recent_trades
        )

        # Portfolio summary from latest snapshot
        snapshots = await self.repo.get_snapshots(platform="alpaca", limit=1)
        portfolio_summary = "No portfolio data available."
        if snapshots:
            s = snapshots[0]
            portfolio_summary = f"Cash: ${s['cash']:.2f}, Equity: ${s['equity']:.2f}, P&L: ${s['daily_pnl']:.2f}"

        ra = self.config.research_agent
        user_msg = STRATEGIST_USER.format(
            period_start=period_start.strftime("%Y-%m-%d"),
            period_end=period_end.strftime("%Y-%m-%d"),
            trades_summary=trades_summary,
            technical_weight=self.config.stock_scorer.technical_weight,
            fundamental_weight=self.config.stock_scorer.fundamental_weight,
            sentiment_weight=self.config.stock_scorer.sentiment_weight,
            min_research_score=ra.min_research_score,
            max_single_pct=ra.max_single_position_pct * 100,
            rebalance_drift=ra.rebalance_drift_threshold * 100,
            portfolio_summary=portfolio_summary,
        )

        try:
            raw = await self.analyst._call_llm_raw(STRATEGIST_SYSTEM, user_msg, model_override=self._model)
            json_str = _strip_markdown(raw)
            data = json.loads(json_str)

            memo = StrategyMemo(
                period_start=period_start,
                period_end=period_end,
                total_return_pct=float(data.get("total_return_pct", 0.0)),
                win_rate=max(0.0, min(1.0, float(data.get("win_rate", 0.0)))),
                best_trade=data.get("best_trade", ""),
                worst_trade=data.get("worst_trade", ""),
                lessons=data.get("lessons", []),
                parameter_changes=_validate_params(data.get("parameter_changes", {})),
                next_week_focus=data.get("next_week_focus", []),
            )

            log.info(
                f"Strategy review: return={memo.total_return_pct:+.1f}%, "
                f"win_rate={memo.win_rate:.0%}, changes={memo.parameter_changes}"
            )
            return memo

        except Exception as e:
            log.warning(f"Strategy review failed: {e}")
            return StrategyMemo(
                period_start=period_start,
                period_end=period_end,
                lessons=[f"Review failed: {e}"],
                next_week_focus=["Retry strategy review."],
            )

    def apply_changes(self, memo: StrategyMemo) -> None:
        """Apply parameter changes from a strategy memo to config."""
        changes = memo.parameter_changes
        if not changes:
            return

        sc = self.config.stock_scorer
        ra = self.config.research_agent

        if "technical_weight" in changes:
            sc.technical_weight = changes["technical_weight"]
        if "fundamental_weight" in changes:
            sc.fundamental_weight = changes["fundamental_weight"]
        if "sentiment_weight" in changes:
            sc.sentiment_weight = changes["sentiment_weight"]
        if "min_research_score" in changes:
            ra.min_research_score = changes["min_research_score"]
        if "max_single_position_pct" in changes:
            ra.max_single_position_pct = changes["max_single_position_pct"]
        if "rebalance_drift_threshold" in changes:
            ra.rebalance_drift_threshold = changes["rebalance_drift_threshold"]

        log.info(f"Applied strategy parameter changes: {changes}")


# Valid parameter ranges for safety
_PARAM_RANGES = {
    "technical_weight": (0.1, 0.6),
    "fundamental_weight": (0.1, 0.6),
    "sentiment_weight": (0.1, 0.6),
    "min_research_score": (3.0, 8.0),
    "max_single_position_pct": (0.05, 0.20),
    "rebalance_drift_threshold": (0.02, 0.10),
}


def _validate_params(changes: dict) -> dict:
    """Validate and clamp parameter changes to safe ranges."""
    validated = {}
    for key, value in changes.items():
        if key in _PARAM_RANGES:
            low, high = _PARAM_RANGES[key]
            validated[key] = max(low, min(high, float(value)))
    return validated


def _strip_markdown(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        end = -1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[1:end])
    return text
