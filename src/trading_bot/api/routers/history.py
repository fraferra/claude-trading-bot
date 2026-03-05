"""History endpoints — trades, decisions, strategy results."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from trading_bot.api.deps import get_repo
from trading_bot.db.repository import Repository
from trading_bot.utils.logging import log

router = APIRouter()


@router.get("/history/trades")
async def get_trades(
    symbol: str | None = None,
    source: str | None = None,
    limit: int = 100,
    repo: Repository = Depends(get_repo),
):
    return await repo.get_trades(limit=limit, symbol=symbol, source=source)


@router.get("/history/decisions")
async def get_decisions(
    limit: int = 100,
    repo: Repository = Depends(get_repo),
):
    return await repo.get_decisions(limit=limit)


@router.get("/history/strategy-results")
async def get_strategy_results(
    strategy_name: str | None = None,
    limit: int = 50,
    repo: Repository = Depends(get_repo),
):
    return await repo.get_strategy_results(strategy_name=strategy_name, limit=limit)


@router.get("/history/stock-scores")
async def get_stock_scores(
    symbol: str | None = None,
    limit: int = 50,
    repo: Repository = Depends(get_repo),
):
    return await repo.get_stock_scores(symbol=symbol, limit=limit)


@router.get("/history/cumulative-pnl")
async def get_cumulative_pnl(
    platform: str | None = None,
    repo: Repository = Depends(get_repo),
):
    """Get cumulative realized P&L time series per platform."""
    platforms = [platform] if platform else ["alpaca", "kalshi", "alpaca_crypto"]
    result = {}
    for p in platforms:
        result[p] = await repo.get_cumulative_pnl(p)
    return result


@router.post("/history/backfill-prices")
async def backfill_trade_prices(
    request: Request,
    repo: Repository = Depends(get_repo),
):
    """Backfill missing fill prices from Alpaca order history."""
    brokers = request.app.state.brokers
    alpaca = brokers.get("alpaca")
    if not alpaca:
        return {"error": "Alpaca broker not configured", "updated": 0}

    trades = await repo.get_trades_missing_price()
    updated = 0

    for trade in trades:
        order_id = trade.get("order_id")
        if not order_id:
            continue
        try:
            import asyncio
            from functools import partial

            loop = asyncio.get_event_loop()
            order = await loop.run_in_executor(
                None, partial(alpaca.trading_client.get_order_by_id, order_id)
            )
            if order.filled_avg_price:
                await repo.update_trade_price(trade["id"], float(order.filled_avg_price))
                updated += 1
                log.info(f"Backfilled price for {trade['symbol']}: ${float(order.filled_avg_price):.2f}")
        except Exception as e:
            log.warning(f"Failed to backfill {trade.get('symbol')} order {order_id}: {e}")

    return {"updated": updated, "total_missing": len(trades)}
