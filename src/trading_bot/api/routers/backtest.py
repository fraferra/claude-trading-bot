"""Backtesting endpoints — run strategy backtests with custom parameters."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter
from pydantic import BaseModel

from trading_bot.backtest.engine import BacktestParams, run_backtest
from trading_bot.utils.logging import log

router = APIRouter()


class BacktestRequest(BaseModel):
    symbols: list[str]
    start_date: str | None = None  # defaults to 1 year ago
    end_date: str | None = None  # defaults to today
    initial_capital: float = 10_000.0
    trade_amount_usd: float = 500.0
    stop_loss_pct: float = 8.0
    take_profit_pct: float = 25.0
    technical_weight: float = 0.35
    fundamental_weight: float = 0.35
    momentum_weight: float = 0.30
    buy_threshold: float = 0.15
    sell_threshold: float = -0.15


@router.post("/backtest/run")
async def run_backtest_endpoint(req: BacktestRequest):
    """Run a backtest with custom parameters."""
    end = req.end_date or datetime.now().strftime("%Y-%m-%d")
    start = req.start_date or (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

    params = BacktestParams(
        symbols=[s.upper() for s in req.symbols],
        start_date=start,
        end_date=end,
        initial_capital=req.initial_capital,
        trade_amount_usd=req.trade_amount_usd,
        stop_loss_pct=req.stop_loss_pct,
        take_profit_pct=req.take_profit_pct,
        technical_weight=req.technical_weight,
        fundamental_weight=req.fundamental_weight,
        momentum_weight=req.momentum_weight,
        buy_threshold=req.buy_threshold,
        sell_threshold=req.sell_threshold,
    )

    log.info(f"Running backtest: {params.symbols} from {start} to {end}")
    result = await run_backtest(params)

    return {
        "params": {
            "symbols": params.symbols,
            "start_date": params.start_date,
            "end_date": params.end_date,
            "initial_capital": params.initial_capital,
            "trade_amount_usd": params.trade_amount_usd,
            "stop_loss_pct": params.stop_loss_pct,
            "take_profit_pct": params.take_profit_pct,
            "technical_weight": params.technical_weight,
            "fundamental_weight": params.fundamental_weight,
            "momentum_weight": params.momentum_weight,
            "buy_threshold": params.buy_threshold,
            "sell_threshold": params.sell_threshold,
        },
        "metrics": {
            "total_return_pct": result.total_return_pct,
            "buy_hold_return_pct": result.buy_hold_return_pct,
            "sharpe_ratio": result.sharpe_ratio,
            "max_drawdown_pct": result.max_drawdown_pct,
            "total_trades": result.total_trades,
            "winning_trades": result.winning_trades,
            "losing_trades": result.losing_trades,
            "win_rate": result.win_rate,
            "avg_win": result.avg_win,
            "avg_loss": result.avg_loss,
            "profit_factor": result.profit_factor,
            "final_equity": result.final_equity,
        },
        "equity_curve": result.equity_curve,
        "trades": [
            {
                "date": t.date,
                "symbol": t.symbol,
                "side": t.side,
                "price": round(t.price, 2),
                "quantity": round(t.quantity, 4),
                "pnl": round(t.pnl, 2),
                "reason": t.reason,
            }
            for t in result.trades
        ],
    }
