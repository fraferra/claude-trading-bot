"""Kalshi prediction market API endpoints."""

from __future__ import annotations

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


@router.get("/kalshi/estimates")
async def get_kalshi_estimates(
    ticker: str | None = None,
    limit: int = 50,
    repo: Repository = Depends(get_repo),
):
    """Get recent AI probability estimates from DB."""
    return await repo.get_kalshi_estimates(ticker=ticker, limit=limit)


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
        except Exception:
            pass

    return {
        "markets_found": len(markets),
        "analyzed": len(estimates),
        "estimates": [e.model_dump() for e in estimates],
    }
