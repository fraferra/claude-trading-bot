"""Analysis endpoints — invoke LLM analysis on stocks and markets."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from trading_bot.api.deps import get_brokers, get_config
from trading_bot.config import Config

router = APIRouter()


class AnalyzeRequest(BaseModel):
    symbol: str | None = None
    condition_id: str | None = None


@router.post("/analyze/stock")
async def analyze_stock(
    req: AnalyzeRequest,
    config: Config = Depends(get_config),
    brokers: dict = Depends(get_brokers),
):
    if not req.symbol:
        raise HTTPException(400, "symbol is required")
    if not config.anthropic_api_key:
        raise HTTPException(500, "ANTHROPIC_API_KEY not configured")

    from trading_bot.analysis.llm_analyst import LLMAnalyst
    analyst = LLMAnalyst(config)

    portfolio = None
    if "alpaca" in brokers:
        try:
            portfolio = await brokers["alpaca"].get_account()
        except Exception:
            pass

    decision = await analyst.analyze_stock(req.symbol.upper(), portfolio)
    return decision.model_dump()


@router.post("/analyze/market")
async def analyze_market(
    req: AnalyzeRequest,
    config: Config = Depends(get_config),
    brokers: dict = Depends(get_brokers),
):
    if not req.condition_id:
        raise HTTPException(400, "condition_id is required")
    if not config.anthropic_api_key:
        raise HTTPException(500, "ANTHROPIC_API_KEY not configured")

    from trading_bot.analysis.llm_analyst import LLMAnalyst
    analyst = LLMAnalyst(config)

    portfolio = None
    if "polymarket" in brokers:
        try:
            portfolio = await brokers["polymarket"].get_account()
        except Exception:
            pass

    decision = await analyst.analyze_polymarket(req.condition_id, portfolio)
    return decision.model_dump()


@router.post("/analyze/probability")
async def analyze_probability(
    req: AnalyzeRequest,
    config: Config = Depends(get_config),
    brokers: dict = Depends(get_brokers),
):
    if not req.condition_id:
        raise HTTPException(400, "condition_id is required")
    if not config.anthropic_api_key:
        raise HTTPException(500, "ANTHROPIC_API_KEY not configured")

    from trading_bot.strategies.probability_edge import ProbabilityEdgeStrategy
    strategy = ProbabilityEdgeStrategy(config)

    portfolio = None
    if "polymarket" in brokers:
        try:
            portfolio = await brokers["polymarket"].get_account()
        except Exception:
            pass

    estimate = await strategy.analyze_market(req.condition_id, portfolio)
    return estimate.model_dump()
