from __future__ import annotations

import json
from pathlib import Path

from trading_bot.analysis.llm_analyst import LLMAnalyst
from trading_bot.analysis.market_data import get_news, get_polymarket_data, search_polymarket_markets
from trading_bot.config import Config
from trading_bot.models import (
    Action,
    PolymarketData,
    PortfolioSummary,
    ProbabilityEstimate,
    Side,
    StrategyResult,
    TradeDecision,
)
from trading_bot.strategies import BaseStrategy
from trading_bot.utils.logging import log


class ProbabilityEdgeStrategy(BaseStrategy):
    """Enhanced AI probability estimation with Kelly Criterion sizing.

    Uses Claude to estimate true probabilities, then trades when
    the AI's estimate diverges significantly from the market price.
    """

    name = "ai_probability_edge"

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self.pe_config = config.strategies.probability_edge
        self.analyst = LLMAnalyst(config)

    async def analyze_market(
        self,
        condition_id: str,
        portfolio: PortfolioSummary | None = None,
    ) -> ProbabilityEstimate:
        """Estimate true probability and calculate edge for a single market."""
        import asyncio
        from trading_bot.analysis.prompts import (
            PROBABILITY_ESTIMATION_SYSTEM,
            PROBABILITY_ESTIMATION_USER,
        )

        market_data, news = await asyncio.gather(
            get_polymarket_data(condition_id),
            get_news(condition_id, limit=5),
        )

        question_news = await get_news(market_data.question[:80], limit=5)
        all_news = news + [n for n in question_news if n.title not in {n2.title for n2 in news}]

        news_text = "\n".join(
            f"- [{n.source}] {n.title}" for n in all_news[:8]
        ) if all_news else "No recent news found."

        available_balance = portfolio.cash if portfolio else 0.0

        user_msg = PROBABILITY_ESTIMATION_USER.format(
            question=market_data.question,
            description=market_data.description[:500] if market_data.description else "No description.",
            yes_price=market_data.yes_price,
            no_price=market_data.no_price,
            volume=f"{market_data.volume:,.0f}",
            liquidity=f"{market_data.liquidity:,.0f}",
            end_date=market_data.end_date or "Unknown",
            news=news_text,
            available_balance=f"{available_balance:,.2f}",
        )

        raw_response = await self.analyst._call_llm_raw(
            PROBABILITY_ESTIMATION_SYSTEM,
            user_msg,
        )

        estimate = self._parse_estimate(raw_response, condition_id, market_data)
        estimate.kelly_fraction = kelly_criterion(
            estimate.ai_probability, market_data.yes_price
        )

        if estimate.edge_pct > 0:
            estimate.suggested_side = Side.BUY
        elif estimate.edge_pct < 0:
            estimate.suggested_side = Side.SELL

        if self.pe_config.track_accuracy:
            self._log_prediction(estimate)

        return estimate

    async def scan(
        self,
        condition_ids: list[str] | None = None,
        search_query: str | None = None,
        portfolio: PortfolioSummary | None = None,
    ) -> StrategyResult:
        """Scan multiple markets for probability edge."""
        if condition_ids is None and search_query:
            markets = await search_polymarket_markets(search_query, limit=10)
            condition_ids = [m["condition_id"] for m in markets]
        elif condition_ids is None:
            return StrategyResult(
                strategy_name=self.name,
                metadata={"error": "Provide condition_ids or search_query"},
            )

        estimates: list[ProbabilityEstimate] = []
        decisions: list[TradeDecision] = []

        for cid in condition_ids:
            try:
                est = await self.analyze_market(cid, portfolio)
                estimates.append(est)

                if abs(est.edge_pct) >= self.pe_config.min_edge_pct:
                    size_usd = self._calculate_position_size(est.kelly_fraction, portfolio)
                    action = Action.BUY if est.edge_pct > 0 else Action.SELL
                    side = est.suggested_side or (Side.BUY if action == Action.BUY else Side.SELL)

                    decisions.append(TradeDecision(
                        action=action,
                        symbol=cid,
                        confidence=min(0.95, abs(est.edge_pct) * 2 + 0.5),
                        reasoning=(
                            f"AI Probability Edge: AI={est.ai_probability:.1%} vs "
                            f"Market={est.market_price:.1%}, edge={est.edge_pct:+.1%}. "
                            f"Kelly={est.kelly_fraction:.2%}. {est.reasoning}"
                        ),
                        suggested_size_usd=size_usd,
                        side=side,
                    ))
            except Exception as e:
                log.warning(f"Failed to analyze {cid}: {e}")

        return StrategyResult(
            strategy_name=self.name,
            decisions=decisions,
            metadata={
                "markets_analyzed": len(condition_ids),
                "estimates": [e.model_dump() for e in estimates],
                "edges_found": len(decisions),
            },
        )

    def _parse_estimate(
        self,
        llm_response: str,
        condition_id: str,
        market_data: PolymarketData,
    ) -> ProbabilityEstimate:
        json_str = llm_response
        if json_str.startswith("```"):
            lines = json_str.split("\n")
            json_str = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            log.warning("Failed to parse probability estimate, defaulting to market price")
            return ProbabilityEstimate(
                condition_id=condition_id,
                question=market_data.question,
                market_price=market_data.yes_price,
                ai_probability=market_data.yes_price,
                edge_pct=0.0,
                reasoning="Failed to parse LLM response",
            )

        ai_prob = float(data.get("probability", data.get("ai_probability", market_data.yes_price)))
        edge = ai_prob - market_data.yes_price

        return ProbabilityEstimate(
            condition_id=condition_id,
            question=market_data.question,
            market_price=market_data.yes_price,
            ai_probability=round(ai_prob, 4),
            confidence_interval_low=float(data.get("confidence_interval_low", max(0, ai_prob - 0.15))),
            confidence_interval_high=float(data.get("confidence_interval_high", min(1, ai_prob + 0.15))),
            edge_pct=round(edge, 4),
            reasoning=data.get("reasoning", ""),
            signals_used=data.get("signals_used", []),
        )

    def _calculate_position_size(
        self,
        kelly_fraction: float,
        portfolio: PortfolioSummary | None,
    ) -> float:
        if portfolio is None or portfolio.equity <= 0:
            return 0.0

        capped_kelly = kelly_fraction * self.pe_config.kelly_fraction_cap
        raw_size = portfolio.equity * capped_kelly
        return min(raw_size, self.pe_config.max_size_usd)

    def _log_prediction(self, estimate: ProbabilityEstimate) -> None:
        from datetime import datetime

        log_path = Path(self.pe_config.accuracy_log_file)

        entry = {
            "timestamp": datetime.now().isoformat(),
            "condition_id": estimate.condition_id,
            "question": estimate.question,
            "market_price": estimate.market_price,
            "ai_probability": estimate.ai_probability,
            "edge_pct": estimate.edge_pct,
            "kelly_fraction": estimate.kelly_fraction,
        }

        existing = []
        if log_path.exists():
            try:
                existing = json.loads(log_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass

        existing.append(entry)
        log_path.write_text(json.dumps(existing, indent=2))


def kelly_criterion(ai_probability: float, market_price: float) -> float:
    """Calculate the Kelly Criterion fraction for position sizing.

    For buying YES at market_price:
      p = ai_probability, b = (1/market_price) - 1
      f* = (p*b - q) / b  where q = 1-p

    For buying NO (ai_prob < market_price):
      Flip: p_no = 1-ai_prob, market_no = 1-market_price
    """
    if market_price <= 0 or market_price >= 1:
        return 0.0

    if ai_probability > market_price:
        p = ai_probability
        b = (1.0 / market_price) - 1.0
    else:
        p = 1.0 - ai_probability
        b = (1.0 / (1.0 - market_price)) - 1.0

    if b <= 0:
        return 0.0

    q = 1.0 - p
    f = (p * b - q) / b

    return max(0.0, min(1.0, f))
