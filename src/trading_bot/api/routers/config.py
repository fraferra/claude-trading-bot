"""Config endpoints."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from trading_bot.api.deps import get_brokers, get_config
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
    kalshi: dict | None = None
    polymarket: dict | None = None
    crypto: dict | None = None
    shorts: dict | None = None
    drawdown_accumulation: dict | None = None
    position_guard: dict | None = None
    telegram: dict | None = None
    research_agent: dict | None = None


_CONFIG_SECTIONS = [
    "risk", "stocks", "run", "stock_scorer", "monitors",
    "kalshi", "polymarket", "crypto", "shorts", "drawdown_accumulation",
    "position_guard", "telegram", "research_agent",
]


def _rebuild_polymarket_broker(config: Config) -> object:
    """Instantiate the correct Polymarket broker based on current config."""
    from trading_bot.brokers.paper_polymarket import PaperPolymarketBroker
    poly = config.polymarket
    if poly.paper:
        return PaperPolymarketBroker(poly.paper_balance)
    has_credentials = poly.private_key and poly.api_key and poly.api_secret and poly.api_passphrase
    if not has_credentials:
        return PaperPolymarketBroker(poly.paper_balance)
    from trading_bot.brokers.polymarket_broker import PolymarketBroker
    return PolymarketBroker(poly)


@router.get("/config")
async def get_config_endpoint(config: Config = Depends(get_config)):
    return _safe_config(config)


@router.put("/config")
async def update_config(
    request: Request,
    update: ConfigUpdate,
    config: Config = Depends(get_config),
    brokers: dict = Depends(get_brokers),
):
    poly_paper_before = config.polymarket.paper

    for section_name in _CONFIG_SECTIONS:
        update_data = getattr(update, section_name, None)
        if update_data:
            section = getattr(config, section_name, None)
            if section:
                for k, v in update_data.items():
                    if hasattr(section, k):
                        setattr(section, k, v)

    # If polymarket paper mode changed, swap the broker live
    if update.polymarket is not None and config.polymarket.paper != poly_paper_before:
        brokers["polymarket"] = _rebuild_polymarket_broker(config)
        # Also update monitor_manager's broker reference
        monitor_manager = getattr(request.app.state, "monitor_manager", None)
        if monitor_manager:
            monitor_manager.brokers["polymarket"] = brokers["polymarket"]

    return _safe_config(config)
