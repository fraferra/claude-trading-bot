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
    request: Request,
    platform: str | None = None,
    repo: Repository = Depends(get_repo),
):
    """Get cumulative P&L time series per platform.

    Returns realized P&L from closed trades PLUS current unrealized P&L
    from open positions appended as a 'today' data point, so the chart
    shows the true total P&L (realized + unrealized) as of right now.

    Also returns an S&P 500 benchmark series for stocks comparison.
    """
    from datetime import date as date_type

    platforms = [platform] if platform else ["alpaca", "kalshi", "alpaca_crypto"]
    brokers = request.app.state.brokers

    # Collect current unrealized P&L per platform from open positions
    unrealized_by_platform: dict[str, float] = {}
    equity_total = 0.0
    try:
        alpaca = brokers.get("alpaca")
        if alpaca:
            positions = await alpaca.get_positions()
            for p in positions:
                plat = "alpaca_crypto" if "/" in p.symbol else "alpaca"
                unrealized_by_platform[plat] = unrealized_by_platform.get(plat, 0) + p.unrealized_pnl
            # Get account equity for benchmark scaling
            account = await alpaca.get_account()
            equity_total = float(account.equity) if account else 0.0
    except Exception as e:
        log.warning(f"Failed to get unrealized P&L for chart: {e}")

    result = {}
    today = date_type.today().isoformat()

    for p in platforms:
        series = await repo.get_cumulative_pnl(p)

        # Append a "today" point that adds unrealized P&L to the cumulative realized
        unrealized = unrealized_by_platform.get(p, 0.0)
        if unrealized != 0.0 or series:
            last_realized = series[-1]["cumulative_pnl"] if series else 0.0

            # If last data point is already today, merge unrealized into it
            if series and series[-1]["date"] == today:
                series[-1]["cumulative_pnl"] = round(last_realized + unrealized, 2)
                series[-1]["unrealized"] = round(unrealized, 2)
            else:
                series.append({
                    "date": today,
                    "daily_pnl": 0.0,
                    "cumulative_pnl": round(last_realized + unrealized, 2),
                    "unrealized": round(unrealized, 2),
                })

        result[p] = series

    # --- S&P 500 benchmark for stocks comparison ---
    alpaca_series = result.get("alpaca", [])
    if alpaca_series:
        sp500 = await _get_sp500_benchmark(alpaca_series, equity_total)
        result["sp500"] = sp500

    return result


async def _get_sp500_benchmark(
    stock_series: list[dict], equity: float
) -> list[dict]:
    """Compute S&P 500 equivalent P&L for the same date range as stock trades.

    Downloads SPY daily close prices and computes what the P&L would be
    if the same equity were passively invested in SPY from the first trade date.
    """
    import asyncio
    import math
    from functools import partial

    if not stock_series or equity <= 0:
        return []

    first_date = stock_series[0]["date"]
    last_date = stock_series[-1]["date"]

    try:
        import yfinance as yf
        import pandas as pd

        loop = asyncio.get_event_loop()
        # Add a buffer day before start for the reference price
        start_dt = pd.Timestamp(first_date) - pd.Timedelta(days=5)

        data = await loop.run_in_executor(
            None,
            lambda: yf.download(
                "SPY", start=start_dt.strftime("%Y-%m-%d"),
                end=(pd.Timestamp(last_date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                progress=False, auto_adjust=True,
            ),
        )

        if data.empty:
            return []

        # Handle MultiIndex columns (modern yfinance)
        if isinstance(data.columns, pd.MultiIndex):
            if "Close" in data.columns.get_level_values(0):
                close_series = data["Close"]
                if isinstance(close_series, pd.DataFrame):
                    close_series = close_series.iloc[:, 0]
            else:
                close_series = data.iloc[:, 0]
        elif "Close" in data.columns:
            close_series = data["Close"]
        else:
            close_series = data.iloc[:, 0]

        # Get the reference price at or before the first trade date
        mask = close_series.index <= pd.Timestamp(first_date)
        if mask.any():
            ref_price = float(close_series[mask].iloc[-1])
        else:
            ref_price = float(close_series.iloc[0])

        if ref_price <= 0 or math.isnan(ref_price):
            return []

        # Build date set from stock series for matching
        stock_dates = {point["date"] for point in stock_series}

        # Compute SPY P&L for each date that exists in the stock series
        sp500_series = []
        for idx, price in close_series.items():
            date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
            if date_str in stock_dates:
                spy_return = (float(price) / ref_price) - 1.0
                sp500_pnl = round(equity * spy_return, 2)
                sp500_series.append({
                    "date": date_str,
                    "cumulative_pnl": sp500_pnl,
                })

        return sp500_series

    except Exception as e:
        log.warning(f"Failed to fetch S&P 500 benchmark: {e}")
        return []


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
