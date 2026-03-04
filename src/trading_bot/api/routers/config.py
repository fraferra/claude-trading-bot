"""Config endpoints."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from trading_bot.api.deps import get_config
from trading_bot.config import Config

router = APIRouter()


def _safe_config(config: Config) -> dict:
    """Return config as dict with secrets masked."""
    d = asdict(config)
    # Mask secrets
    if d.get("anthropic_api_key"):
        d["anthropic_api_key"] = "***" + d["anthropic_api_key"][-4:]
    if d.get("alpaca", {}).get("api_key"):
        d["alpaca"]["api_key"] = "***" + d["alpaca"]["api_key"][-4:]
    if d.get("alpaca", {}).get("secret_key"):
        d["alpaca"]["secret_key"] = "***"
    if d.get("polymarket", {}).get("private_key"):
        d["polymarket"]["private_key"] = "***"
    if d.get("polymarket", {}).get("api_key"):
        d["polymarket"]["api_key"] = "***"
    if d.get("polymarket", {}).get("api_secret"):
        d["polymarket"]["api_secret"] = "***"
    if d.get("polymarket", {}).get("api_passphrase"):
        d["polymarket"]["api_passphrase"] = "***"
    return d


class ConfigUpdate(BaseModel):
    risk: dict | None = None
    stocks: dict | None = None
    run: dict | None = None
    stock_scorer: dict | None = None
    monitors: dict | None = None


@router.get("/config")
async def get_config_endpoint(config: Config = Depends(get_config)):
    return _safe_config(config)


@router.put("/config")
async def update_config(
    update: ConfigUpdate,
    config: Config = Depends(get_config),
):
    if update.risk:
        for k, v in update.risk.items():
            if hasattr(config.risk, k):
                setattr(config.risk, k, v)
    if update.stocks:
        for k, v in update.stocks.items():
            if hasattr(config.stocks, k):
                setattr(config.stocks, k, v)
    if update.run:
        for k, v in update.run.items():
            if hasattr(config.run, k):
                setattr(config.run, k, v)
    if update.stock_scorer:
        for k, v in update.stock_scorer.items():
            if hasattr(config.stock_scorer, k):
                setattr(config.stock_scorer, k, v)
    if update.monitors:
        for k, v in update.monitors.items():
            if hasattr(config.monitors, k):
                setattr(config.monitors, k, v)

    return _safe_config(config)
