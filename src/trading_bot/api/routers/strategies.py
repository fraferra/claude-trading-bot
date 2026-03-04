"""Strategy scan endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from trading_bot.api.deps import get_config
from trading_bot.config import Config

router = APIRouter()


class StockScoreRequest(BaseModel):
    symbol: str


class StockRankRequest(BaseModel):
    symbols: list[str] | None = None


class ArbScanRequest(BaseModel):
    min_edge: float | None = None


class CrossMarketScanRequest(BaseModel):
    queries: list[str] | None = None


class ProbabilityScanRequest(BaseModel):
    condition_ids: list[str] | None = None
    search_query: str | None = None


@router.post("/scan/stock-score")
async def scan_stock_score(
    req: StockScoreRequest,
    config: Config = Depends(get_config),
):
    if not config.anthropic_api_key:
        raise HTTPException(500, "ANTHROPIC_API_KEY not configured")

    from trading_bot.strategies.stock_scorer import MultiSignalStockScorer
    scorer = MultiSignalStockScorer(config)
    score = await scorer.score_stock(req.symbol.upper())
    return score.model_dump()


@router.post("/scan/stock-rank")
async def scan_stock_rank(
    req: StockRankRequest,
    config: Config = Depends(get_config),
):
    if not config.anthropic_api_key:
        raise HTTPException(500, "ANTHROPIC_API_KEY not configured")

    from trading_bot.strategies.stock_ranker import StockRanker
    ranker = StockRanker(config)
    symbols = req.symbols or config.stocks.watchlist
    ranking = await ranker.rank(symbols)
    return ranking.model_dump()


@router.post("/scan/arbitrage")
async def scan_arbitrage(
    req: ArbScanRequest,
    config: Config = Depends(get_config),
):
    from trading_bot.strategies.arbitrage import ArbitrageScanner
    scanner = ArbitrageScanner(config)
    if req.min_edge is not None:
        scanner.arb_config.min_edge_pct = req.min_edge

    result = await scanner.scan()
    return {
        "decisions": [d.model_dump() for d in result.decisions],
        "metadata": result.metadata,
    }


@router.post("/scan/cross-market")
async def scan_cross_market(
    req: CrossMarketScanRequest,
    config: Config = Depends(get_config),
):
    if not config.anthropic_api_key:
        raise HTTPException(500, "ANTHROPIC_API_KEY not configured")

    from trading_bot.strategies.cross_market import CrossMarketScanner
    scanner = CrossMarketScanner(config)
    result = await scanner.scan(search_queries=req.queries)
    return {
        "decisions": [d.model_dump() for d in result.decisions],
        "metadata": result.metadata,
    }


@router.post("/scan/probability")
async def scan_probability(
    req: ProbabilityScanRequest,
    config: Config = Depends(get_config),
):
    if not config.anthropic_api_key:
        raise HTTPException(500, "ANTHROPIC_API_KEY not configured")

    from trading_bot.strategies.probability_edge import ProbabilityEdgeStrategy
    strategy = ProbabilityEdgeStrategy(config)

    result = await strategy.scan(
        condition_ids=req.condition_ids,
        search_query=req.search_query,
    )
    return {
        "decisions": [d.model_dump() for d in result.decisions],
        "metadata": result.metadata,
    }
