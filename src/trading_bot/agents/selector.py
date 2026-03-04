"""Selector Agent — constructs target portfolio allocation from research reports."""

from __future__ import annotations

import json

from trading_bot.agents.prompts import SELECTOR_SYSTEM, SELECTOR_USER
from trading_bot.analysis.llm_analyst import LLMAnalyst
from trading_bot.config import Config
from trading_bot.models import AllocationEntry, PortfolioAllocation, Position, ResearchReport
from trading_bot.utils.logging import log


class SelectorAgent:
    """Construct target portfolio allocation from scored candidates."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.analyst = LLMAnalyst(config)
        self.ra = config.research_agent

    async def build_allocation(
        self,
        reports: list[ResearchReport],
        current_positions: list[Position] | None = None,
        portfolio_equity: float = 0.0,
    ) -> PortfolioAllocation:
        """Build target allocation from research reports.

        Uses deterministic ranking + LLM review for adjustments.
        """
        current_positions = current_positions or []
        current_weights = _compute_current_weights(current_positions, portfolio_equity)

        # Filter by minimum score and sort by composite
        qualified = [r for r in reports if r.composite_score >= self.ra.min_research_score]
        qualified.sort(key=lambda r: r.composite_score, reverse=True)

        # Take top N
        top = qualified[:self.ra.max_positions]

        if not top:
            return PortfolioAllocation(
                cash_reserve=1.0,
                reasoning="No stocks met the minimum research score threshold.",
            )

        # Allocate weights proportional to score
        allocatable = 1.0 - self.ra.min_cash_reserve_pct
        total_score = sum(r.composite_score for r in top)

        entries = []
        for r in top:
            raw_weight = (r.composite_score / total_score) * allocatable if total_score > 0 else 0.0
            weight = min(raw_weight, self.ra.max_single_position_pct)
            weight = round(weight, 4)

            current_w = current_weights.get(r.symbol, 0.0)
            action = _determine_action(current_w, weight, self.ra.rebalance_drift_threshold)

            entries.append(AllocationEntry(
                symbol=r.symbol,
                target_weight=weight,
                current_weight=current_w,
                research_score=r.composite_score,
                action=action,
            ))

        # Check for sells — positions not in new allocation
        allocated_symbols = {e.symbol for e in entries}
        for sym, w in current_weights.items():
            if sym not in allocated_symbols and w > 0.01:
                entries.append(AllocationEntry(
                    symbol=sym,
                    target_weight=0.0,
                    current_weight=w,
                    research_score=0.0,
                    action="sell",
                ))

        total_target = sum(e.target_weight for e in entries)
        cash_reserve = round(1.0 - total_target, 4)

        rebalance_needed = any(e.action != "hold" for e in entries)

        # LLM review for concentration/correlation issues
        reasoning = await self._llm_review(entries, current_positions, portfolio_equity)

        return PortfolioAllocation(
            entries=entries,
            cash_reserve=cash_reserve,
            total_positions=len([e for e in entries if e.target_weight > 0]),
            rebalance_needed=rebalance_needed,
            reasoning=reasoning,
        )

    async def _llm_review(
        self,
        entries: list[AllocationEntry],
        current_positions: list[Position],
        portfolio_equity: float,
    ) -> str:
        """Ask LLM to review the allocation for issues."""
        allocation_table = "\n".join(
            f"  {e.symbol}: target={e.target_weight:.1%}, current={e.current_weight:.1%}, "
            f"score={e.research_score:.1f}, action={e.action}"
            for e in entries
        )

        current_portfolio = "\n".join(
            f"  {p.symbol}: {p.quantity} shares @ ${p.avg_entry_price:.2f} "
            f"(value: ${p.market_value:.0f})"
            for p in current_positions
        ) if current_positions else "  No current positions"

        user_msg = SELECTOR_USER.format(
            allocation_table=allocation_table,
            current_portfolio=current_portfolio,
            max_positions=self.ra.max_positions,
            max_single_pct=self.ra.max_single_position_pct * 100,
            min_cash_pct=self.ra.min_cash_reserve_pct * 100,
        )

        try:
            raw = await self.analyst._call_llm_raw(SELECTOR_SYSTEM, user_msg)
            json_str = _strip_markdown(raw)
            data = json.loads(json_str)
            assessment = data.get("overall_assessment", "")
            concerns = data.get("concerns", [])
            if concerns:
                return f"{assessment} Concerns: {'; '.join(concerns)}"
            return assessment
        except Exception as e:
            log.warning(f"Selector LLM review failed: {e}")
            return "Allocation based on research scores (LLM review unavailable)."


def _compute_current_weights(positions: list[Position], equity: float) -> dict[str, float]:
    if equity <= 0:
        return {}
    return {p.symbol: round(p.market_value / equity, 4) for p in positions if p.market_value > 0}


def _determine_action(current_weight: float, target_weight: float, threshold: float) -> str:
    diff = target_weight - current_weight
    if current_weight == 0 and target_weight > 0:
        return "buy"
    if target_weight == 0 and current_weight > 0:
        return "sell"
    if diff > threshold:
        return "add"
    if diff < -threshold:
        return "trim"
    return "hold"


def _strip_markdown(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        end = -1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[1:end])
    return text
