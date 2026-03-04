"""Portfolio endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from trading_bot.api.deps import get_brokers, get_config, get_repo
from trading_bot.config import Config
from trading_bot.db.repository import Repository

router = APIRouter()


@router.get("/portfolio")
async def get_portfolio(
    config: Config = Depends(get_config),
    brokers: dict = Depends(get_brokers),
):
    result = {}
    for name, broker in brokers.items():
        try:
            summary = await broker.get_account()
            result[name] = summary.model_dump()
        except Exception as e:
            result[name] = {"error": str(e)}
    return result


@router.get("/positions")
async def get_positions(
    brokers: dict = Depends(get_brokers),
):
    positions = []
    for name, broker in brokers.items():
        try:
            summary = await broker.get_account()
            for p in summary.positions:
                positions.append(p.model_dump())
        except Exception:
            pass
    return positions


@router.get("/snapshots")
async def get_snapshots(
    platform: str | None = None,
    limit: int = 100,
    repo: Repository = Depends(get_repo),
):
    return await repo.get_snapshots(platform=platform, limit=limit)
