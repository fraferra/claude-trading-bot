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
        data = portfolio.model_dump()
        # Expose paper/live mode so dashboards can show the correct badge
        from trading_bot.brokers.paper_polymarket import PaperPolymarketBroker
        data["is_paper"] = isinstance(broker, PaperPolymarketBroker)
        return data
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
        if s.get("monitor_type") in (
            "polymarket_arb", "cross_platform_arb", "cross_market", "temporal_momentum"
        )
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
    clob_client = getattr(broker, "client", None)
    scanner = ArbitrageScanner(config, clob_client=clob_client)
    result = await scanner.scan()

    return {
        "strategy": result.strategy_name,
        "events_scanned": result.metadata.get("events_scanned", 0),
        "opportunities_found": result.metadata.get("opportunities_found", 0),
        "opportunities": result.metadata.get("opportunities", [])[:10],
    }


@router.get("/polymarket/temporal-momentum/signals")
async def get_temporal_momentum_signals(request: Request):
    """Get current BTC/ETH/SOL momentum signals from the running monitor."""
    manager = getattr(request.app.state, "monitor_manager", None)
    if not manager:
        return {"signals": {}, "active_markets": 0, "opportunities": []}

    for monitor in manager._monitors.values():
        if monitor.monitor_type == "temporal_momentum":
            return {
                "signals": getattr(monitor, "_latest_signals", {}),
                "active_markets": len(getattr(monitor, "_active_markets", [])),
                "opportunities": getattr(monitor, "_latest_opportunities", []),
                "total_exposure_usd": getattr(monitor, "_total_exposure_usd", 0.0),
            }
    return {"signals": {}, "active_markets": 0, "opportunities": []}


@router.get("/polymarket/temporal-momentum/decisions")
async def get_temporal_momentum_decisions(
    limit: int = 50,
    repo: Repository = Depends(get_repo),
):
    """Get recent temporal momentum arb decisions."""
    decisions = await repo.get_agent_decisions(
        agent_type="temporal_momentum",
        limit=limit,
    )
    return {"decisions": decisions}


@router.post("/polymarket/temporal-momentum/scan")
async def trigger_temporal_momentum_scan(request: Request):
    """Trigger an immediate temporal momentum scan on the running monitor."""
    manager = getattr(request.app.state, "monitor_manager", None)
    if not manager:
        return {"error": "Monitor manager not available"}

    for monitor in manager._monitors.values():
        if monitor.monitor_type == "temporal_momentum":
            try:
                await monitor._refresh_markets()
                await monitor.run_cycle()
                return {
                    "status": "scanned",
                    "signals": getattr(monitor, "_latest_signals", {}),
                    "opportunities": getattr(monitor, "_latest_opportunities", []),
                }
            except Exception as e:
                return {"error": str(e)}

    # No running monitor — do a one-shot strategy scan
    config = request.app.state.config
    from trading_bot.strategies.temporal_momentum_arb import TemporalMomentumArbStrategy
    strategy = TemporalMomentumArbStrategy(config.temporal_momentum)
    markets = await strategy.find_active_crypto_markets()
    return {
        "status": "static_scan",
        "active_markets": len(markets),
        "markets": [
            {
                "question": m["question"][:80],
                "symbol": m["symbol"],
                "minutes_remaining": round(m["minutes_remaining"], 1),
                "yes_price": m["yes_price"],
                "volume": m["volume"],
            }
            for m in markets[:20]
        ],
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
