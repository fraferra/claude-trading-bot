"""Trade execution endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from trading_bot.api.deps import get_brokers, get_config, get_repo, get_risk_manager, get_ws_manager
from trading_bot.api.websocket import WebSocketManager
from trading_bot.config import Config
from trading_bot.db.repository import Repository
from trading_bot.models import (
    Action, OrderRequest, OrderType, Platform, Side, WSEvent, WSEventType,
)
from trading_bot.risk.manager import RiskManager

router = APIRouter()


class StockTradeRequest(BaseModel):
    symbol: str
    quantity: float | None = None
    order_type: str = "market"
    limit_price: float | None = None


class MarketTradeRequest(BaseModel):
    condition_id: str
    size_usd: float = 100.0
    side: str = "buy"


class TradePreviewRequest(BaseModel):
    symbol: str
    side: str = "buy"
    quantity: float | None = None
    platform: str = "alpaca"


@router.post("/trade/stock")
async def trade_stock(
    req: StockTradeRequest,
    config: Config = Depends(get_config),
    brokers: dict = Depends(get_brokers),
    risk_mgr: RiskManager = Depends(get_risk_manager),
    repo: Repository = Depends(get_repo),
    ws: WebSocketManager = Depends(get_ws_manager),
):
    if "alpaca" not in brokers:
        raise HTTPException(400, "Alpaca broker not configured")
    if not config.anthropic_api_key:
        raise HTTPException(500, "ANTHROPIC_API_KEY not configured")

    broker = brokers["alpaca"]
    symbol = req.symbol.upper()

    from trading_bot.analysis.llm_analyst import LLMAnalyst
    analyst = LLMAnalyst(config)
    portfolio = await broker.get_account()

    decision = await analyst.analyze_stock(symbol, portfolio)
    if decision.action == Action.HOLD:
        return {"executed": False, "reason": "hold", "decision": decision.model_dump()}

    risk_check = risk_mgr.check_decision(decision)
    if not risk_check.approved:
        return {"executed": False, "reason": risk_check.reason, "decision": decision.model_dump()}

    current_price = await broker.get_quote(symbol)
    quantity = req.quantity or risk_mgr.calculate_position_size(
        decision.confidence, portfolio.equity, current_price
    )

    side = Side.BUY if decision.action == Action.BUY else Side.SELL
    otype = OrderType.LIMIT if req.order_type == "limit" else OrderType.MARKET

    order = OrderRequest(
        symbol=symbol, side=side, quantity=quantity,
        order_type=otype, limit_price=req.limit_price, platform=Platform.ALPACA,
    )

    order_check = risk_mgr.check_order(order, portfolio, current_price)
    if not order_check.approved:
        return {"executed": False, "reason": order_check.reason, "decision": decision.model_dump()}
    if order_check.adjusted_quantity is not None:
        order.quantity = order_check.adjusted_quantity

    result = await broker.submit_order(order)
    risk_mgr.record_trade()

    await repo.insert_trade(
        result.order_id, symbol, side.value, order.quantity,
        result.filled_price, "alpaca", "api",
        reasoning=decision.reasoning, confidence=decision.confidence,
    )

    await ws.broadcast(WSEvent(
        type=WSEventType.TRADE_EXECUTED,
        data={"symbol": symbol, "side": side.value, "quantity": order.quantity,
              "price": result.filled_price, "platform": "alpaca"},
    ))

    return {"executed": True, "order": result.model_dump(), "decision": decision.model_dump()}


@router.post("/trade/market")
async def trade_market(
    req: MarketTradeRequest,
    config: Config = Depends(get_config),
    brokers: dict = Depends(get_brokers),
    risk_mgr: RiskManager = Depends(get_risk_manager),
    repo: Repository = Depends(get_repo),
    ws: WebSocketManager = Depends(get_ws_manager),
):
    if "polymarket" not in brokers:
        raise HTTPException(400, "Polymarket broker not configured")

    broker = brokers["polymarket"]
    current_price = await broker.get_quote(req.condition_id)
    qty = req.size_usd / current_price if current_price > 0 else 0

    side = Side.BUY if req.side.lower() == "buy" else Side.SELL
    order = OrderRequest(
        symbol=req.condition_id, side=side, quantity=qty,
        order_type=OrderType.MARKET, platform=Platform.POLYMARKET,
    )

    portfolio = await broker.get_account()
    order_check = risk_mgr.check_order(order, portfolio, current_price)
    if not order_check.approved:
        return {"executed": False, "reason": order_check.reason}
    if order_check.adjusted_quantity is not None:
        order.quantity = order_check.adjusted_quantity

    result = await broker.submit_order(order)
    risk_mgr.record_trade()

    await repo.insert_trade(
        result.order_id, req.condition_id, side.value, order.quantity,
        result.filled_price, "polymarket", "api",
    )

    await ws.broadcast(WSEvent(
        type=WSEventType.TRADE_EXECUTED,
        data={"symbol": req.condition_id, "side": side.value,
              "quantity": order.quantity, "price": result.filled_price,
              "platform": "polymarket"},
    ))

    return {"executed": True, "order": result.model_dump()}


@router.post("/trade/preview")
async def trade_preview(
    req: TradePreviewRequest,
    brokers: dict = Depends(get_brokers),
    risk_mgr: RiskManager = Depends(get_risk_manager),
):
    platform = req.platform.lower()
    broker = brokers.get(platform)
    if not broker:
        raise HTTPException(400, f"Broker {platform} not configured")

    portfolio = await broker.get_account()
    try:
        current_price = await broker.get_quote(req.symbol)
    except Exception:
        current_price = 0.0

    quantity = req.quantity or risk_mgr.calculate_position_size(
        0.7, portfolio.equity, current_price if current_price > 0 else 1.0
    )

    side = Side.BUY if req.side.lower() == "buy" else Side.SELL
    order = OrderRequest(
        symbol=req.symbol, side=side, quantity=quantity,
        order_type=OrderType.MARKET,
        platform=Platform.ALPACA if platform == "alpaca" else Platform.POLYMARKET,
    )

    check = risk_mgr.check_order(order, portfolio, current_price)

    return {
        "symbol": req.symbol,
        "side": side.value,
        "quantity": check.adjusted_quantity or quantity,
        "estimated_cost": (check.adjusted_quantity or quantity) * current_price,
        "current_price": current_price,
        "approved": check.approved,
        "reason": check.reason,
    }
