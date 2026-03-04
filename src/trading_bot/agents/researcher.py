"""Research Agent — deep 6-dimensional scoring of candidate stocks."""

from __future__ import annotations

import asyncio
import json

from trading_bot.agents.prompts import RESEARCH_SYSTEM, RESEARCH_USER
from trading_bot.analysis.llm_analyst import LLMAnalyst, _format_large_number
from trading_bot.analysis.market_data import get_news, get_stock_data, get_stock_fundamentals
from trading_bot.config import Config
from trading_bot.models import (
    DimensionScores,
    FundamentalScore,
    MarketRegime,
    ResearchReport,
    SentimentScore,
    TechnicalScore,
)
from trading_bot.strategies.stock_scorer import (
    compute_fundamental_score,
    compute_technical_score,
    detect_regime,
)
from trading_bot.utils.logging import log


class ResearchAgent:
    """Deep-score a candidate stock across 6 dimensions."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.analyst = LLMAnalyst(config)

    async def score(self, symbol: str, discovery_reason: str = "") -> ResearchReport:
        """Score a single stock with full research analysis."""
        # Gather all data in parallel
        stock_data, fundamentals, news = await asyncio.gather(
            get_stock_data(symbol, self.config.stocks.default_period),
            get_stock_fundamentals(symbol),
            get_news(f"{symbol} stock", limit=8),
        )

        # Compute quantitative scores (reuse existing pure functions)
        technical = compute_technical_score(symbol, stock_data)
        fundamental = compute_fundamental_score(symbol, fundamentals)
        regime = detect_regime(stock_data)

        # Build rich context for LLM
        news_text = "\n".join(
            f"- [{n.source}] {n.title}" for n in news
        ) if news else "No recent news."

        price_history_text = "\n".join(
            f"  {d['date']}: O=${d['open']} H=${d['high']} L=${d['low']} C=${d['close']} V={d['volume']:,}"
            for d in stock_data.price_history[-10:]
        ) if stock_data.price_history else "No price history."

        user_msg = RESEARCH_USER.format(
            symbol=symbol,
            discovery_reason=discovery_reason or "Watchlist stock",
            current_price=stock_data.current_price,
            sma_20=stock_data.sma_20 or "N/A",
            sma_50=stock_data.sma_50 or "N/A",
            rsi_14=stock_data.rsi_14 or "N/A",
            macd=stock_data.macd or "N/A",
            macd_signal=stock_data.macd_signal or "N/A",
            technical_composite=f"{technical.composite:+.2f}",
            market_cap=_format_large_number(fundamentals.market_cap),
            pe_ratio=fundamentals.pe_ratio or "N/A",
            forward_pe=fundamentals.forward_pe or "N/A",
            dividend_yield=f"{fundamentals.dividend_yield:.2%}" if fundamentals.dividend_yield else "N/A",
            beta=fundamentals.beta or "N/A",
            sector=fundamentals.sector or "N/A",
            fifty_two_week_low=fundamentals.fifty_two_week_low or "N/A",
            fifty_two_week_high=fundamentals.fifty_two_week_high or "N/A",
            fundamental_composite=f"{fundamental.composite:+.2f}",
            price_history=price_history_text,
            news=news_text,
            regime=regime.value,
        )

        try:
            raw = await self.analyst._call_llm_raw(RESEARCH_SYSTEM, user_msg)
            json_str = _strip_markdown(raw)
            data = json.loads(json_str)

            dimension_scores = DimensionScores(
                financial_health=_clamp(data.get("financial_health", 5.0), 1.0, 10.0),
                growth_potential=_clamp(data.get("growth_potential", 5.0), 1.0, 10.0),
                news_sentiment=_clamp(data.get("news_sentiment", 5.0), 1.0, 10.0),
                news_impact=_clamp(data.get("news_impact", 5.0), 1.0, 10.0),
                price_momentum=_clamp(data.get("price_momentum", 5.0), 1.0, 10.0),
                volatility_risk=_clamp(data.get("volatility_risk", 5.0), 1.0, 10.0),
                reasoning=data.get("reasoning", {}),
            )

            # Composite = average of 6 dimensions
            dims = [
                dimension_scores.financial_health,
                dimension_scores.growth_potential,
                dimension_scores.news_sentiment,
                dimension_scores.news_impact,
                dimension_scores.price_momentum,
                dimension_scores.volatility_risk,
            ]
            composite = round(sum(dims) / len(dims), 2)

            # Build sentiment score from LLM's news_sentiment dimension
            sentiment = SentimentScore(
                symbol=symbol,
                sentiment=round((dimension_scores.news_sentiment - 5.0) / 5.0, 4),
                confidence=0.7,
                key_factors=data.get("catalysts", [])[:3],
            )

            return ResearchReport(
                symbol=symbol,
                company_name=data.get("company_name", ""),
                sector=data.get("sector", fundamentals.sector or ""),
                dimension_scores=dimension_scores,
                composite_score=composite,
                technical=technical,
                fundamental=fundamental,
                sentiment=sentiment,
                regime=regime,
                catalysts=data.get("catalysts", []),
                risks=data.get("risks", []),
                llm_recommendation=data.get("recommendation", "hold"),
                target_weight=_clamp(data.get("target_weight", 0.0), 0.0, 0.15),
            )

        except Exception as e:
            log.warning(f"Research scoring failed for {symbol}: {e}")
            # Return neutral report with quantitative data only
            sentiment = SentimentScore(symbol=symbol)
            return ResearchReport(
                symbol=symbol,
                sector=fundamentals.sector or "",
                technical=technical,
                fundamental=fundamental,
                sentiment=sentiment,
                regime=regime,
            )


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _strip_markdown(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        end = -1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[1:end])
    return text
