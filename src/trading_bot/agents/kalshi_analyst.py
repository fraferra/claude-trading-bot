"""Kalshi Analyst Agent — estimate probabilities and generate trade decisions."""

from __future__ import annotations

import json

from trading_bot.agents.kalshi_prompts import KALSHI_PROBABILITY_SYSTEM, KALSHI_PROBABILITY_USER
from trading_bot.analysis.llm_analyst import LLMAnalyst
from trading_bot.analysis.market_data import get_news
from trading_bot.config import Config
from trading_bot.models import (
    Action,
    KalshiMarketData,
    KalshiProbabilityEstimate,
    Platform,
    PortfolioSummary,
    Side,
    TradeDecision,
)
from trading_bot.strategies.probability_edge import kelly_criterion
from trading_bot.utils.logging import log


class KalshiAnalystAgent:
    """Estimate probabilities and generate trade decisions for Kalshi markets."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.analyst = LLMAnalyst(config)
        self._kalshi_cfg = config.kalshi

    async def analyze_market(
        self, market: KalshiMarketData
    ) -> KalshiProbabilityEstimate:
        """Use LLM to estimate true probability, compute edge and Kelly sizing."""
        # Gather relevant news
        search_query = market.title[:80]
        try:
            news = await get_news(search_query, limit=5)
            news_text = "\n".join(
                f"- [{n.source}] {n.title}" for n in news
            ) if news else "No recent news found."
        except Exception:
            news_text = "News unavailable."

        user_msg = KALSHI_PROBABILITY_USER.format(
            question=market.title,
            title=market.title,
            yes_price=market.yes_price,
            no_price=market.no_price,
            volume=market.volume,
            close_time=market.close_time or "Unknown",
            news=news_text,
            context=market.subtitle or "No additional context.",
        )

        try:
            raw = await self.analyst._call_llm_raw(KALSHI_PROBABILITY_SYSTEM, user_msg)

            # Parse response
            json_str = raw.strip()
            if json_str.startswith("```"):
                lines = json_str.split("\n")
                end = -1 if lines[-1].strip() == "```" else len(lines)
                json_str = "\n".join(lines[1:end])

            data = json.loads(json_str)
            ai_prob = float(data.get("probability", market.yes_price))
            edge = ai_prob - market.yes_price

            estimate = KalshiProbabilityEstimate(
                ticker=market.ticker,
                title=market.title,
                market_price=market.yes_price,
                ai_probability=round(ai_prob, 4),
                confidence_interval_low=float(
                    data.get("confidence_interval_low", max(0, ai_prob - 0.15))
                ),
                confidence_interval_high=float(
                    data.get("confidence_interval_high", min(1, ai_prob + 0.15))
                ),
                edge_pct=round(edge, 4),
                kelly_fraction=kelly_criterion(ai_prob, market.yes_price),
                reasoning=data.get("reasoning", ""),
                category=market.category,
            )

            # Determine side
            if estimate.edge_pct > 0:
                estimate.suggested_side = Side.BUY
            elif estimate.edge_pct < 0:
                estimate.suggested_side = Side.SELL

            return estimate

        except Exception as e:
            log.warning(f"Kalshi probability estimation failed for {market.ticker}: {e}")
            return KalshiProbabilityEstimate(
                ticker=market.ticker,
                title=market.title,
                market_price=market.yes_price,
                ai_probability=market.yes_price,
                edge_pct=0.0,
                reasoning=f"Analysis failed: {e}",
                category=market.category,
            )

    async def generate_decisions(
        self,
        estimates: list[KalshiProbabilityEstimate],
        portfolio: PortfolioSummary,
    ) -> list[TradeDecision]:
        """Convert probability estimates with sufficient edge into trade decisions."""
        decisions = []
        total_exposure = 0.0

        # Sort by absolute edge (best opportunities first)
        sorted_estimates = sorted(estimates, key=lambda e: abs(e.edge_pct), reverse=True)

        for est in sorted_estimates:
            # Check minimum edge
            if abs(est.edge_pct) < self._kalshi_cfg.min_edge_pct:
                continue

            # Check max positions
            if len(decisions) >= self._kalshi_cfg.max_positions:
                break

            # Check total exposure
            if total_exposure >= self._kalshi_cfg.max_total_exposure_usd:
                break

            # Size using Kelly with cap
            size_usd = self._calculate_position_size(est, portfolio)
            if size_usd <= 0:
                continue

            # Ensure we don't exceed total exposure
            size_usd = min(size_usd, self._kalshi_cfg.max_total_exposure_usd - total_exposure)

            action = Action.BUY if est.edge_pct > 0 else Action.SELL
            side = est.suggested_side or (Side.BUY if action == Action.BUY else Side.SELL)

            decisions.append(TradeDecision(
                action=action,
                symbol=est.ticker,
                confidence=min(0.95, abs(est.edge_pct) * 2 + 0.5),
                reasoning=(
                    f"Kalshi Edge: AI={est.ai_probability:.1%} vs "
                    f"Market={est.market_price:.1%}, edge={est.edge_pct:+.1%}. "
                    f"Kelly={est.kelly_fraction:.2%}. {est.reasoning}"
                ),
                suggested_size_usd=size_usd,
                side=side,
            ))
            total_exposure += size_usd

        log.info(
            f"Kalshi Analyst: {len(estimates)} estimates → "
            f"{len(decisions)} trade decisions (${total_exposure:.0f} exposure)"
        )
        return decisions

    def _calculate_position_size(
        self,
        estimate: KalshiProbabilityEstimate,
        portfolio: PortfolioSummary,
    ) -> float:
        """Calculate position size using Kelly Criterion with safety cap."""
        if portfolio.equity <= 0:
            return 0.0

        capped_kelly = estimate.kelly_fraction * self._kalshi_cfg.kelly_fraction_cap
        raw_size = portfolio.equity * capped_kelly
        return min(raw_size, self._kalshi_cfg.max_size_usd)
