"""API endpoints for the autonomous research agent."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request

router = APIRouter(prefix="/research")


@router.get("/status")
async def research_status(request: Request):
    """Get research agent status and configuration."""
    config = request.app.state.config
    ra = config.research_agent
    monitor_manager = request.app.state.monitor_manager

    # Check if research_agent monitor is running
    running_monitors = monitor_manager.list_monitors()
    research_monitors = [m for m in running_monitors if m["monitor_type"] == "research_agent"]

    return {
        "enabled": ra.enabled,
        "scan_interval_minutes": ra.scan_interval_minutes,
        "max_candidates": ra.max_candidates,
        "max_positions": ra.max_positions,
        "max_single_position_pct": ra.max_single_position_pct,
        "min_cash_reserve_pct": ra.min_cash_reserve_pct,
        "min_research_score": ra.min_research_score,
        "strategy_review_day": ra.strategy_review_day,
        "active_monitors": research_monitors,
    }


@router.get("/reports")
async def get_research_reports(request: Request, symbol: str | None = None, limit: int = 50):
    """Get latest research reports."""
    repo = request.app.state.repo
    reports = await repo.get_research_reports(symbol=symbol, limit=limit)
    # Parse JSON fields
    for r in reports:
        r["dimension_scores"] = json.loads(r.get("dimension_scores_json", "{}"))
        r["catalysts"] = json.loads(r.get("catalysts_json", "[]"))
        r["risks"] = json.loads(r.get("risks_json", "[]"))
    return {"reports": reports}


@router.get("/reports/{symbol}")
async def get_reports_for_symbol(request: Request, symbol: str, limit: int = 20):
    """Get research report history for a specific symbol."""
    repo = request.app.state.repo
    reports = await repo.get_research_reports(symbol=symbol.upper(), limit=limit)
    for r in reports:
        r["dimension_scores"] = json.loads(r.get("dimension_scores_json", "{}"))
        r["catalysts"] = json.loads(r.get("catalysts_json", "[]"))
        r["risks"] = json.loads(r.get("risks_json", "[]"))
    return {"reports": reports}


@router.get("/allocation")
async def get_current_allocation(request: Request):
    """Get most recent portfolio allocation."""
    repo = request.app.state.repo
    allocations = await repo.get_portfolio_allocations(limit=1)
    if not allocations:
        return {"allocation": None}

    alloc = allocations[0]
    alloc["entries"] = json.loads(alloc.get("entries_json", "[]"))
    return {"allocation": alloc}


@router.get("/memos")
async def get_strategy_memos(request: Request, limit: int = 20):
    """Get strategy review memos."""
    repo = request.app.state.repo
    memos = await repo.get_strategy_memos(limit=limit)
    for m in memos:
        m["lessons"] = json.loads(m.get("lessons_json", "[]"))
        m["parameter_changes"] = json.loads(m.get("parameter_changes_json", "{}"))
        m["next_week_focus"] = json.loads(m.get("next_week_focus_json", "[]"))
    return {"memos": memos}


@router.get("/discoveries")
async def get_discovery_runs(request: Request, limit: int = 20):
    """Get recent discovery runs."""
    repo = request.app.state.repo
    runs = await repo.get_discovery_runs(limit=limit)
    for r in runs:
        r["candidates"] = json.loads(r.get("candidates_json", "[]"))
        r["source_queries"] = json.loads(r.get("source_queries_json", "[]"))
    return {"discoveries": runs}


@router.post("/run")
async def trigger_research_run(request: Request):
    """Trigger an immediate research pipeline run."""
    config = request.app.state.config

    if not config.anthropic_api_key:
        return {"error": "ANTHROPIC_API_KEY not set"}, 400

    from trading_bot.agents.discovery import DiscoveryAgent
    from trading_bot.agents.researcher import ResearchAgent
    from trading_bot.agents.selector import SelectorAgent

    discovery = DiscoveryAgent(config)
    researcher = ResearchAgent(config)
    selector = SelectorAgent(config)
    repo = request.app.state.repo

    # 1. Discovery
    candidates = await discovery.find_candidates()

    await repo.insert_discovery_run(
        candidates_json=json.dumps([{"symbol": s, "reason": r} for s, r in candidates]),
        source_queries_json=json.dumps(discovery.source_queries),
        num_candidates=len(candidates),
    )

    # 2. Research (with concurrency limit)
    sem = asyncio.Semaphore(5)

    async def _score(sym, reason):
        async with sem:
            return await researcher.score(sym, reason)

    results = await asyncio.gather(
        *[_score(s, r) for s, r in candidates],
        return_exceptions=True,
    )

    reports = []
    for r in results:
        if hasattr(r, "symbol"):
            reports.append(r)
            await repo.insert_research_report(
                symbol=r.symbol,
                company_name=r.company_name,
                sector=r.sector,
                composite_score=r.composite_score,
                dimension_scores_json=r.dimension_scores.model_dump_json(),
                recommendation=r.llm_recommendation,
                target_weight=r.target_weight,
                catalysts_json=json.dumps(r.catalysts),
                risks_json=json.dumps(r.risks),
            )

    # 3. Allocation
    broker = request.app.state.brokers.get("alpaca")
    positions = []
    equity = 100000.0
    if broker:
        try:
            portfolio = await broker.get_account()
            positions = await broker.get_positions()
            equity = portfolio.equity + portfolio.cash
        except Exception:
            pass

    allocation = await selector.build_allocation(reports, positions, equity)

    await repo.insert_portfolio_allocation(
        entries_json=json.dumps([e.model_dump() for e in allocation.entries]),
        cash_reserve=allocation.cash_reserve,
        rebalance_needed=allocation.rebalance_needed,
        reasoning=allocation.reasoning,
    )

    return {
        "candidates_found": len(candidates),
        "reports_scored": len(reports),
        "allocation": {
            "entries": [e.model_dump() for e in allocation.entries],
            "cash_reserve": allocation.cash_reserve,
            "rebalance_needed": allocation.rebalance_needed,
            "reasoning": allocation.reasoning,
        },
        "top_stocks": [
            {"symbol": r.symbol, "score": r.composite_score, "rec": r.llm_recommendation}
            for r in sorted(reports, key=lambda x: x.composite_score, reverse=True)[:5]
        ],
    }


@router.post("/discover")
async def trigger_discovery_only(request: Request):
    """Run only the discovery phase to find candidates."""
    config = request.app.state.config

    if not config.anthropic_api_key:
        return {"error": "ANTHROPIC_API_KEY not set"}, 400

    from trading_bot.agents.discovery import DiscoveryAgent

    discovery = DiscoveryAgent(config)
    candidates = await discovery.find_candidates()

    repo = request.app.state.repo
    await repo.insert_discovery_run(
        candidates_json=json.dumps([{"symbol": s, "reason": r} for s, r in candidates]),
        source_queries_json=json.dumps(discovery.source_queries),
        num_candidates=len(candidates),
    )

    return {
        "candidates": [{"symbol": s, "reason": r} for s, r in candidates],
    }
