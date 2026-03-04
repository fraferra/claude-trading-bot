"""Kalshi prediction market API endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request

from trading_bot.api.deps import get_repo
from trading_bot.db.repository import Repository

router = APIRouter()


@router.get("/kalshi/events")
async def get_kalshi_events(request: Request, limit: int = 50):
    """List available Kalshi events."""
    broker = request.app.state.brokers.get("kalshi")
    if not broker:
        return {"error": "Kalshi broker not configured", "events": []}
    events = await broker.get_events(limit=limit)
    return {"events": [e.model_dump() for e in events]}


@router.get("/kalshi/markets/{ticker}")
async def get_kalshi_market(ticker: str, request: Request):
    """Get specific Kalshi market data."""
    broker = request.app.state.brokers.get("kalshi")
    if not broker:
        return {"error": "Kalshi broker not configured"}
    market = await broker.get_market(ticker)
    return market.model_dump()


@router.get("/kalshi/portfolio")
async def get_kalshi_portfolio(request: Request):
    """Get Kalshi portfolio (positions and balance)."""
    broker = request.app.state.brokers.get("kalshi")
    if not broker:
        return {"error": "Kalshi broker not configured"}
    try:
        portfolio = await broker.get_account()
        return portfolio.model_dump()
    except Exception as e:
        return {"error": f"Kalshi API error: {str(e)}"}


@router.get("/kalshi/orders")
async def get_kalshi_orders(request: Request, status: str | None = None):
    """Get Kalshi orders. Pass status=resting for open orders."""
    broker = request.app.state.brokers.get("kalshi")
    if not broker:
        return {"error": "Kalshi broker not configured", "orders": []}
    try:
        orders = await broker.get_orders(status=status)
        return {"orders": orders}
    except Exception as e:
        return {"error": f"Kalshi API error: {str(e)}", "orders": []}


@router.get("/kalshi/trades")
async def get_kalshi_trades(
    limit: int = 50,
    repo: Repository = Depends(get_repo),
):
    """Get Kalshi trades from local DB."""
    return await repo.get_trades(limit=limit, platform="kalshi")


@router.get("/kalshi/estimates")
async def get_kalshi_estimates(
    ticker: str | None = None,
    limit: int = 50,
    repo: Repository = Depends(get_repo),
):
    """Get recent AI probability estimates from DB."""
    return await repo.get_kalshi_estimates(ticker=ticker, limit=limit)


@router.get("/kalshi/decisions")
async def get_kalshi_decisions(
    limit: int = 50,
    symbol: str | None = None,
    repo: Repository = Depends(get_repo),
):
    """Get recent Kalshi agent decisions from the decision log."""
    return await repo.get_agent_decisions(
        agent_type="kalshi_prediction", limit=limit, symbol=symbol,
    )


@router.get("/kalshi/settlements")
async def get_kalshi_settlements(
    limit: int = 50,
    repo: Repository = Depends(get_repo),
):
    """Get Kalshi settlement history (concluded bets with P&L)."""
    return await repo.get_kalshi_settlements(limit=limit)


@router.post("/kalshi/scan")
async def trigger_kalshi_scan(request: Request, repo: Repository = Depends(get_repo)):
    """Trigger a full Kalshi discovery + analysis cycle."""
    broker = request.app.state.brokers.get("kalshi")
    if not broker:
        return {"error": "Kalshi broker not configured"}

    from trading_bot.agents.kalshi_analyst import KalshiAnalystAgent
    from trading_bot.agents.kalshi_discovery import KalshiDiscoveryAgent

    config = request.app.state.config
    discovery = KalshiDiscoveryAgent(config, broker)
    analyst = KalshiAnalystAgent(config)

    markets = await discovery.find_opportunities()
    estimates = []
    for m in markets[:10]:  # Limit manual scans
        try:
            est = await analyst.analyze_market(m)
            estimates.append(est)
            await repo.insert_kalshi_estimate(
                ticker=est.ticker,
                title=est.title,
                market_price=est.market_price,
                ai_probability=est.ai_probability,
                edge_pct=est.edge_pct,
                kelly_fraction=est.kelly_fraction,
                suggested_side=est.suggested_side.value if est.suggested_side else None,
                reasoning=est.reasoning[:500],
                category=est.category,
            )
            # Also log decision
            await repo.insert_agent_decision(
                agent_type="kalshi_prediction",
                symbol=est.ticker,
                action=est.suggested_side.value if est.suggested_side else "hold",
                confidence=min(0.95, abs(est.edge_pct) * 2 + 0.5),
                reasoning=est.reasoning,
                signals_json=json.dumps({
                    "market_price": est.market_price,
                    "ai_probability": est.ai_probability,
                    "edge_pct": est.edge_pct,
                    "kelly_fraction": est.kelly_fraction,
                    "category": est.category,
                    "title": est.title,
                }),
                outcome="scan_result",
            )
        except Exception:
            pass

    return {
        "markets_found": len(markets),
        "analyzed": len(estimates),
        "estimates": [
            {**e.model_dump(), "reasoning": e.reasoning}
            for e in estimates
        ],
    }
