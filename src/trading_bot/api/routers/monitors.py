"""Monitor management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from trading_bot.api.deps import get_monitor_manager, get_repo
from trading_bot.db.repository import Repository
from trading_bot.monitors.manager import MonitorManager

router = APIRouter()


@router.get("/monitors")
async def list_monitors(
    manager: MonitorManager = Depends(get_monitor_manager),
    repo: Repository = Depends(get_repo),
):
    active = manager.list_monitors()
    db_states = await repo.get_all_monitor_states()
    return {
        "active": active,
        "all_states": db_states,
    }


@router.post("/monitors/{monitor_type}/start")
async def start_monitor(
    monitor_type: str,
    manager: MonitorManager = Depends(get_monitor_manager),
):
    try:
        state = await manager.start_monitor(monitor_type)
        return state
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/monitors/{monitor_id}/stop")
async def stop_monitor(
    monitor_id: str,
    manager: MonitorManager = Depends(get_monitor_manager),
):
    state = await manager.stop_monitor(monitor_id)
    if state is None:
        raise HTTPException(404, f"Monitor {monitor_id} not found")
    return state


@router.post("/monitors/{monitor_id}/pause")
async def pause_monitor(
    monitor_id: str,
    manager: MonitorManager = Depends(get_monitor_manager),
):
    state = await manager.pause_monitor(monitor_id)
    if state is None:
        raise HTTPException(404, f"Monitor {monitor_id} not found")
    return state


@router.post("/monitors/{monitor_id}/resume")
async def resume_monitor(
    monitor_id: str,
    manager: MonitorManager = Depends(get_monitor_manager),
):
    state = await manager.resume_monitor(monitor_id)
    if state is None:
        raise HTTPException(404, f"Monitor {monitor_id} not found")
    return state


@router.get("/monitors/{monitor_id}")
async def get_monitor_detail(
    monitor_id: str,
    repo: Repository = Depends(get_repo),
):
    state = await repo.get_monitor_state(monitor_id)
    if state is None:
        raise HTTPException(404, f"Monitor {monitor_id} not found")

    recent_trades = await repo.get_recent_monitor_trades(monitor_id, limit=10)
    return {**state, "recent_trades": recent_trades}
