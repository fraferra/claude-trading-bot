"""Multi-signal stock scoring strategy.

Three independent sub-scores (technical, fundamental, sentiment)
fused with regime-aware weighting. Based on 3S-Trader research framework.
"""

from __future__ import annotations

import asyncio
import json

from trading_bot.analysis.llm_analyst import LLMAnalyst
from trading_bot.analysis.market_data import get_news, get_stock_data, get_stock_fundamentals
from trading_bot.config import Config
from trading_bot.models import (
    Action,
    FundamentalScore,
    MarketRegime,
    SentimentScore,
    StockCompositeScore,
    StockData,
    StockFundamentals,
    StrategyResult,
    TechnicalScore,
    TradeDecision,
)
from trading_bot.strategies import BaseStrategy
from trading_bot.utils.logging import log


class MultiSignalStockScorer(BaseStrategy):
    """Score stocks using technical, fundamental, and sentiment signals."""

    name = "multi_signal_stock_scorer"

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self.scorer_config = config.stock_scorer
        self.analyst = LLMAnalyst(config)

    async def score_stock(self, symbol: str) -> StockCompositeScore:
        """Score a single stock across all signal dimensions."""
        stock_data, fundamentals, news = await asyncio.gather(
            get_stock_data(symbol, self.config.stocks.default_period),
            get_stock_fundamentals(symbol),
            get_news(f"{symbol} stock", limit=8),
        )

        technical = compute_technical_score(symbol, stock_data)
        fundamental = compute_fundamental_score(symbol, fundamentals)
        sentiment = await self._compute_sentiment_score(symbol, news)

        regime = detect_regime(stock_data)
        weights = self._get_regime_weights(regime)

        composite = (
            weights["technical"] * technical.composite
            + weights["fundamental"] * fundamental.composite
            + weights["sentiment"] * sentiment.sentiment
        )
        composite = round(max(-1.0, min(1.0, composite)), 4)

        action = Action.HOLD
        if composite >= self.scorer_config.min_composite_score:
            action = Action.BUY
        elif composite <= self.scorer_config.max_composite_score:
            action = Action.SELL

        return StockCompositeScore(
            symbol=symbol,
            technical=technical,
            fundamental=fundamental,
            sentiment=sentiment,
            regime=regime,
            composite_score=composite,
            signal_weights=weights,
            suggested_action=action,
            confidence=min(1.0, abs(composite)),
            reasoning=(
                f"Composite {composite:+.2f} ({regime.value}): "
                f"tech={technical.composite:+.2f}, "
                f"fund={fundamental.composite:+.2f}, "
                f"sent={sentiment.sentiment:+.2f}"
            ),
        )

    async def scan(self) -> StrategyResult:
        """Score all watchlist stocks and return ranked results."""
        scores: list[StockCompositeScore] = []
        decisions: list[TradeDecision] = []

        for symbol in self.config.stocks.watchlist:
            try:
                score = await self.score_stock(symbol)
                scores.append(score)

                if score.suggested_action != Action.HOLD:
                    decisions.append(TradeDecision(
                        action=score.suggested_action,
                        symbol=symbol,
                        confidence=score.confidence,
                        reasoning=score.reasoning,
                        suggested_position_pct=0.05 * score.confidence,
                    ))
            except Exception as e:
                log.warning(f"Failed to score {symbol}: {e}")

        scores.sort(key=lambda s: s.composite_score, reverse=True)

        return StrategyResult(
            strategy_name=self.name,
            decisions=decisions,
            metadata={
                "scores": [s.model_dump() for s in scores],
                "regime": scores[0].regime.value if scores else "unknown",
                "stocks_scored": len(scores),
            },
        )

    async def _compute_sentiment_score(self, symbol: str, news) -> SentimentScore:
        """Use LLM to score sentiment from news headlines."""
        from trading_bot.analysis.prompts import SENTIMENT_SCORING_SYSTEM, SENTIMENT_SCORING_USER

        news_text = "\n".join(f"- [{n.source}] {n.title}" for n in news) if news else "No news."
        user_msg = SENTIMENT_SCORING_USER.format(symbol=symbol, news=news_text)

        try:
            raw = await self.analyst._call_llm_raw(SENTIMENT_SCORING_SYSTEM, user_msg)
            json_str = raw.strip()
            if json_str.startswith("```"):
                lines = json_str.split("\n")
                json_str = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            data = json.loads(json_str)
            return SentimentScore(
                symbol=symbol,
                sentiment=max(-1.0, min(1.0, float(data.get("sentiment", 0.0)))),
                confidence=max(0.0, min(1.0, float(data.get("confidence", 0.5)))),
                key_factors=data.get("key_factors", []),
            )
        except Exception as e:
            log.warning(f"Sentiment scoring failed for {symbol}: {e}")
            return SentimentScore(symbol=symbol)

    def _get_regime_weights(self, regime: MarketRegime) -> dict[str, float]:
        """Get signal weights adjusted for market regime."""
        base = {
            "technical": self.scorer_config.technical_weight,
            "fundamental": self.scorer_config.fundamental_weight,
            "sentiment": self.scorer_config.sentiment_weight,
        }
        adjustments = {
            MarketRegime.TRENDING_UP: {"technical": 0.10, "fundamental": -0.05, "sentiment": -0.05},
            MarketRegime.TRENDING_DOWN: {"technical": 0.10, "fundamental": -0.05, "sentiment": -0.05},
            MarketRegime.HIGH_VOLATILITY: {"technical": -0.10, "fundamental": 0.05, "sentiment": 0.05},
            MarketRegime.MEAN_REVERTING: {"technical": 0.05, "fundamental": 0.05, "sentiment": -0.10},
            MarketRegime.LOW_VOLATILITY: {"technical": 0.0, "fundamental": 0.0, "sentiment": 0.0},
        }
        adj = adjustments.get(regime, {})
        result = {k: base[k] + adj.get(k, 0) for k in base}
        total = sum(result.values())
        return {k: round(v / total, 3) for k, v in result.items()}


# --- Pure computation functions (no LLM, testable) ---

def compute_technical_score(symbol: str, data: StockData) -> TechnicalScore:
    """Compute technical analysis sub-score from stock data."""
    sma_trend = 0.0
    if data.sma_20 and data.sma_50:
        if data.current_price > data.sma_20 > data.sma_50:
            sma_trend = 1.0
        elif data.current_price < data.sma_20 < data.sma_50:
            sma_trend = -1.0
        elif data.current_price > data.sma_20:
            sma_trend = 0.5
        else:
            sma_trend = -0.5

    rsi_signal = 0.0
    if data.rsi_14:
        if data.rsi_14 < 30:
            rsi_signal = 1.0
        elif data.rsi_14 < 40:
            rsi_signal = 0.5
        elif data.rsi_14 > 70:
            rsi_signal = -1.0
        elif data.rsi_14 > 60:
            rsi_signal = -0.5

    macd_sig = 0.0
    if data.macd is not None and data.macd_signal is not None:
        diff = data.macd - data.macd_signal
        macd_sig = max(-1.0, min(1.0, diff * 10))

    momentum = 0.0
    if data.price_history and len(data.price_history) >= 2:
        first_close = data.price_history[0]["close"]
        if first_close > 0:
            pct_change = (data.current_price - first_close) / first_close
            momentum = max(-1.0, min(1.0, pct_change * 5))

    composite = (sma_trend + rsi_signal + macd_sig + momentum) / 4.0

    return TechnicalScore(
        symbol=symbol,
        sma_trend=round(sma_trend, 4),
        rsi_signal=round(rsi_signal, 4),
        macd_signal=round(max(-1.0, min(1.0, macd_sig)), 4),
        momentum_score=round(momentum, 4),
        composite=round(max(-1.0, min(1.0, composite)), 4),
    )


def compute_fundamental_score(symbol: str, fund: StockFundamentals) -> FundamentalScore:
    """Compute fundamental analysis sub-score."""
    pe_score = 0.0
    if fund.pe_ratio:
        if fund.pe_ratio < 15:
            pe_score = 0.8
        elif fund.pe_ratio < 25:
            pe_score = 0.3
        elif fund.pe_ratio < 35:
            pe_score = -0.3
        else:
            pe_score = -0.8

    growth = 0.0
    if fund.pe_ratio and fund.forward_pe:
        ratio = fund.forward_pe / fund.pe_ratio
        if ratio < 0.8:
            growth = 0.8
        elif ratio < 1.0:
            growth = 0.3
        elif ratio > 1.2:
            growth = -0.5

    quality = 0.0
    if fund.beta:
        if fund.beta < 0.8:
            quality += 0.3
        elif fund.beta > 1.5:
            quality -= 0.3
    if fund.dividend_yield and fund.dividend_yield > 0.02:
        quality += 0.2

    composite = (pe_score + growth + quality) / 3.0

    return FundamentalScore(
        symbol=symbol,
        pe_vs_sector=round(pe_score, 4),
        growth_score=round(growth, 4),
        quality_score=round(max(-1.0, min(1.0, quality)), 4),
        composite=round(max(-1.0, min(1.0, composite)), 4),
    )


def detect_regime(data: StockData) -> MarketRegime:
    """Detect market regime from price history."""
    if not data.price_history or len(data.price_history) < 10:
        return MarketRegime.LOW_VOLATILITY

    closes = [d["close"] for d in data.price_history]
    returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes)) if closes[i - 1] > 0]

    if not returns:
        return MarketRegime.LOW_VOLATILITY

    avg_return = sum(returns) / len(returns)
    volatility = (sum((r - avg_return) ** 2 for r in returns) / len(returns)) ** 0.5

    if avg_return > 0.002 and data.sma_20 and data.current_price > data.sma_20:
        return MarketRegime.TRENDING_UP
    elif avg_return < -0.002 and data.sma_20 and data.current_price < data.sma_20:
        return MarketRegime.TRENDING_DOWN

    if volatility > 0.02:
        return MarketRegime.HIGH_VOLATILITY
    elif volatility < 0.005:
        return MarketRegime.LOW_VOLATILITY

    return MarketRegime.MEAN_REVERTING
