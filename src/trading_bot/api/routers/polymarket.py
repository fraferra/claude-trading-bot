"""Polymarket prediction market API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from trading_bot.api.deps import get_repo
from trading_bot.db.repository import Repository

router = APIRouter()


@router.get("/polymarket/portfolio")
async def get_polymarket_portfolio(request: Request):
    """Get Polymarket portfolio (USDC balance and open positions)."""
    broker = request.app.state.brokers.get("polymarket")
    if not broker:
        return {"error": "Polymarket broker not configured"}
    try:
        portfolio = await broker.get_account()
        return portfolio.model_dump()
    except Exception as e:
        return {"error": f"Polymarket API error: {str(e)}"}


@router.get("/polymarket/positions")
async def get_polymarket_positions(request: Request):
    """Get open Polymarket positions."""
    broker = request.app.state.brokers.get("polymarket")
    if not broker:
        return {"error": "Polymarket broker not configured", "positions": []}
    try:
        positions = await broker.get_positions()
        return {"positions": [p.model_dump() for p in positions]}
    except Exception as e:
        return {"error": f"Polymarket API error: {str(e)}", "positions": []}


@router.get("/polymarket/trades")
async def get_polymarket_trades(
    limit: int = 50,
    repo: Repository = Depends(get_repo),
):
    """Get Polymarket trades from local DB."""
    return await repo.get_trades(limit=limit, platform="polymarket")


@router.get("/polymarket/settlements")
async def get_polymarket_settlements(
    limit: int = 50,
    repo: Repository = Depends(get_repo),
):
    """Get Polymarket settlement history (concluded markets with P&L)."""
    return await repo.get_polymarket_settlements(limit=limit)


@router.get("/polymarket/arb-opportunities")
async def get_arb_opportunities(
    limit: int = 20,
    repo: Repository = Depends(get_repo),
):
    """Get recent polymarket arb opportunities from agent decision log."""
    decisions = await repo.get_agent_decisions(
        agent_type="polymarket_arb",
        limit=limit,
        outcome="executed",
    )
    return {"opportunities": decisions}


@router.get("/polymarket/cross-platform-pairs")
async def get_cross_platform_pairs(
    status: str | None = None,
    limit: int = 50,
    repo: Repository = Depends(get_repo),
):
    """Get cross-platform arb pairs (Polymarket ↔ Kalshi)."""
    pairs = await repo.get_arb_pairs(status=status, limit=limit)
    return {"pairs": pairs}


@router.get("/polymarket/pnl-history")
async def get_polymarket_pnl_history(
    repo: Repository = Depends(get_repo),
):
    """Get cumulative Polymarket P&L time series."""
    pnl = await repo.get_polymarket_cumulative_pnl()
    return {"pnl_history": pnl}


@router.get("/polymarket/monitor-stats")
async def get_monitor_stats(
    repo: Repository = Depends(get_repo),
):
    """Get Polymarket arb monitor performance stats."""
    states = await repo.get_all_monitor_states()
    poly_monitors = [
        s for s in states
        if s.get("monitor_type") in ("polymarket_arb", "cross_platform_arb", "cross_market")
    ]
    return {"monitors": poly_monitors}


@router.get("/polymarket/decisions")
async def get_polymarket_decisions(
    limit: int = 50,
    agent_type: str | None = None,
    repo: Repository = Depends(get_repo),
):
    """Get recent Polymarket arb agent decisions."""
    agent = agent_type or "polymarket_arb"
    decisions = await repo.get_agent_decisions(agent_type=agent, limit=limit)
    return {"decisions": decisions}


@router.post("/polymarket/arb-scan")
async def trigger_arb_scan(request: Request, repo: Repository = Depends(get_repo)):
    """Trigger an immediate Polymarket multi-outcome arb scan."""
    broker = request.app.state.brokers.get("polymarket")
    if not broker:
        return {"error": "Polymarket broker not configured"}

    from trading_bot.strategies.arbitrage import ArbitrageScanner
    config = request.app.state.config
    scanner = ArbitrageScanner(config)
    result = await scanner.scan()

    return {
        "strategy": result.strategy_name,
        "events_scanned": result.metadata.get("events_scanned", 0),
        "opportunities_found": result.metadata.get("opportunities_found", 0),
        "opportunities": result.metadata.get("opportunities", [])[:10],
    }


@router.post("/polymarket/cross-platform-scan")
async def trigger_cross_platform_scan(
    request: Request, repo: Repository = Depends(get_repo)
):
    """Trigger an immediate cross-platform arb scan (Polymarket ↔ Kalshi)."""
    poly_broker = request.app.state.brokers.get("polymarket")
    kalshi_broker = request.app.state.brokers.get("kalshi")

    if not poly_broker or not kalshi_broker:
        return {"error": "Both Polymarket and Kalshi brokers must be configured"}

    from trading_bot.strategies.cross_platform_arb import CrossPlatformArbScanner
    config = request.app.state.config
    scanner = CrossPlatformArbScanner(config.cross_platform_arb)
    result = await scanner.scan(poly_broker, kalshi_broker)

    return {
        "strategy": result.strategy_name,
        "pairs_matched": result.metadata.get("pairs_matched", 0),
        "opportunities_found": result.metadata.get("opportunities_found", 0),
        "opportunities": result.metadata.get("opportunities", [])[:10],
    }
