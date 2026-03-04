"""Dependency injection for FastAPI routes."""

from __future__ import annotations

from fastapi import Request

from trading_bot.api.websocket import WebSocketManager
from trading_bot.config import Config
from trading_bot.db.repository import Repository
from trading_bot.monitors.manager import MonitorManager
from trading_bot.risk.manager import RiskManager


def get_config(request: Request) -> Config:
    return request.app.state.config


def get_repo(request: Request) -> Repository:
    return request.app.state.repo


def get_ws_manager(request: Request) -> WebSocketManager:
    return request.app.state.ws_manager


def get_monitor_manager(request: Request) -> MonitorManager:
    return request.app.state.monitor_manager


def get_risk_manager(request: Request) -> RiskManager:
    return request.app.state.risk_manager


def get_brokers(request: Request) -> dict:
    return request.app.state.brokers
