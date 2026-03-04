"""Market data endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from trading_bot.api.deps import get_config
from trading_bot.config import Config

router = APIRouter()


@router.get("/stocks/{symbol}")
async def get_stock_data(
    symbol: str,
    config: Config = Depends(get_config),
):
    from trading_bot.analysis.market_data import get_stock_data, get_stock_fundamentals

    symbol = symbol.upper()
    try:
        data = await get_stock_data(symbol, period=config.stocks.default_period)
        fundamentals = await get_stock_fundamentals(symbol)
        return {
            "data": data.model_dump() if data else None,
            "fundamentals": fundamentals.model_dump() if fundamentals else None,
        }
    except Exception as e:
        raise HTTPException(500, f"Failed to get data for {symbol}: {e}")


@router.get("/markets/search")
async def search_markets(
    q: str,
    limit: int = 10,
):
    from trading_bot.analysis.market_data import search_polymarket_markets

    results = await search_polymarket_markets(q, limit)
    return results


@router.get("/markets/{condition_id}")
async def get_market_data(
    condition_id: str,
):
    from trading_bot.analysis.market_data import get_polymarket_data

    try:
        data = await get_polymarket_data(condition_id)
        return data.model_dump() if data else None
    except Exception as e:
        raise HTTPException(500, f"Failed to get market data: {e}")
