"""Watchlist stock ranker — ranks all stocks by composite score."""

from __future__ import annotations

from trading_bot.config import Config
from trading_bot.models import MarketRegime, StockRanking, StrategyResult
from trading_bot.strategies import BaseStrategy
from trading_bot.strategies.stock_scorer import MultiSignalStockScorer
from trading_bot.utils.logging import log


class StockRanker(BaseStrategy):
    """Rank all watchlist stocks using the multi-signal scorer."""

    name = "stock_ranker"

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self.scorer = MultiSignalStockScorer(config)

    async def rank(self, symbols: list[str] | None = None) -> StockRanking:
        """Score and rank stocks by composite score (descending)."""
        symbols = symbols or self.config.stocks.watchlist

        scores = []
        for symbol in symbols:
            try:
                score = await self.scorer.score_stock(symbol)
                scores.append(score)
            except Exception as e:
                log.warning(f"Failed to score {symbol}: {e}")

        scores.sort(key=lambda s: s.composite_score, reverse=True)

        regime = scores[0].regime if scores else MarketRegime.LOW_VOLATILITY

        return StockRanking(rankings=scores, regime=regime)

    async def scan(self) -> StrategyResult:
        """Scan watchlist and return as StrategyResult."""
        ranking = await self.rank()

        decisions = []
        for score in ranking.rankings:
            if score.suggested_action.value != "hold":
                from trading_bot.models import TradeDecision
                decisions.append(TradeDecision(
                    action=score.suggested_action,
                    symbol=score.symbol,
                    confidence=score.confidence,
                    reasoning=score.reasoning,
                    suggested_position_pct=0.05 * score.confidence,
                ))

        return StrategyResult(
            strategy_name=self.name,
            decisions=decisions,
            metadata={
                "rankings": [s.model_dump() for s in ranking.rankings],
                "regime": ranking.regime.value,
                "stocks_ranked": len(ranking.rankings),
            },
        )
