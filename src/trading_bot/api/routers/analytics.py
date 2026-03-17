"""Analytics endpoints — performance metrics, risk analysis, CSV export."""

from __future__ import annotations

import csv
import io
import math
from collections import defaultdict, deque
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from trading_bot.api.deps import get_repo
from trading_bot.db.repository import Repository
from trading_bot.utils.logging import log

router = APIRouter()


def _compute_metrics(trades: list[dict]) -> dict:
    """Compute performance metrics from trade history using FIFO matching."""
    positions: dict[str, deque] = defaultdict(deque)
    realized_pnl: list[dict] = []  # {"date": str, "pnl": float, "symbol": str}

    for t in trades:
        symbol = t["symbol"]
        side = t["side"]
        qty = t["quantity"]
        price = t.get("filled_price")
        date = t["created_at"][:10] if t.get("created_at") else ""

        if not price:
            continue

        if side == "buy":
            positions[symbol].append((qty, price))
        elif side == "sell":
            remaining = qty
            while remaining > 0 and positions[symbol]:
                lot_qty, lot_price = positions[symbol][0]
                matched = min(remaining, lot_qty)
                pnl = (price - lot_price) * matched
                realized_pnl.append({"date": date, "pnl": pnl, "symbol": symbol})
                remaining -= matched
                if matched >= lot_qty:
                    positions[symbol].popleft()
                else:
                    positions[symbol][0] = (lot_qty - matched, lot_price)

    if not realized_pnl:
        return {
            "total_realized_pnl": 0, "total_trades": 0, "winning_trades": 0,
            "losing_trades": 0, "win_rate": 0, "avg_win": 0, "avg_loss": 0,
            "profit_factor": 0, "sharpe_ratio": 0, "sortino_ratio": 0,
            "max_drawdown_pct": 0, "max_drawdown_usd": 0,
            "best_trade": 0, "worst_trade": 0,
            "daily_returns": [], "pnl_by_symbol": {},
        }

    # Basic stats
    wins = [r for r in realized_pnl if r["pnl"] > 0]
    losses = [r for r in realized_pnl if r["pnl"] < 0]
    total_pnl = sum(r["pnl"] for r in realized_pnl)
    total_win = sum(r["pnl"] for r in wins) if wins else 0
    total_loss = abs(sum(r["pnl"] for r in losses)) if losses else 0

    # Daily returns
    daily_pnl: dict[str, float] = defaultdict(float)
    for r in realized_pnl:
        daily_pnl[r["date"]] += r["pnl"]

    sorted_dates = sorted(daily_pnl.keys())
    daily_returns = [{"date": d, "pnl": round(daily_pnl[d], 2)} for d in sorted_dates]

    # Sharpe ratio (annualized, assuming daily returns)
    returns_list = [daily_pnl[d] for d in sorted_dates]
    avg_return = sum(returns_list) / len(returns_list) if returns_list else 0
    std_return = math.sqrt(sum((r - avg_return) ** 2 for r in returns_list) / max(len(returns_list) - 1, 1)) if len(returns_list) > 1 else 0
    sharpe = (avg_return / std_return * math.sqrt(252)) if std_return > 0 else 0

    # Sortino ratio (only downside deviation)
    downside = [r for r in returns_list if r < 0]
    downside_dev = math.sqrt(sum(r ** 2 for r in downside) / max(len(downside), 1)) if downside else 0
    sortino = (avg_return / downside_dev * math.sqrt(252)) if downside_dev > 0 else 0

    # Max drawdown
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for d in sorted_dates:
        cumulative += daily_pnl[d]
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    # P&L by symbol
    pnl_by_symbol: dict[str, float] = defaultdict(float)
    for r in realized_pnl:
        pnl_by_symbol[r["symbol"]] += r["pnl"]

    # P&L by source/strategy
    pnl_by_strategy: dict[str, float] = defaultdict(float)
    trade_count_by_strategy: dict[str, int] = defaultdict(int)
    for t in trades:
        source = t.get("source", "unknown")
        strategy = source.split(":")[0] if ":" in source else source
        trade_count_by_strategy[strategy] += 1

    return {
        "total_realized_pnl": round(total_pnl, 2),
        "total_trades": len(realized_pnl),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": round(len(wins) / len(realized_pnl) * 100, 1) if realized_pnl else 0,
        "avg_win": round(total_win / len(wins), 2) if wins else 0,
        "avg_loss": round(-total_loss / len(losses), 2) if losses else 0,
        "profit_factor": round(total_win / total_loss, 2) if total_loss > 0 else float("inf"),
        "sharpe_ratio": round(sharpe, 2),
        "sortino_ratio": round(sortino, 2),
        "max_drawdown_pct": 0,  # Would need equity history for percentage
        "max_drawdown_usd": round(max_dd, 2),
        "best_trade": round(max((r["pnl"] for r in realized_pnl), default=0), 2),
        "worst_trade": round(min((r["pnl"] for r in realized_pnl), default=0), 2),
        "daily_returns": daily_returns,
        "pnl_by_symbol": {k: round(v, 2) for k, v in sorted(pnl_by_symbol.items(), key=lambda x: x[1], reverse=True)},
        "trade_count_by_strategy": dict(trade_count_by_strategy),
    }


@router.get("/analytics/performance")
async def get_performance(
    platform: str | None = None,
    repo: Repository = Depends(get_repo),
):
    """Get comprehensive performance analytics."""
    trades = await repo.get_all_trades_for_analytics(platform=platform)
    metrics = _compute_metrics(trades)

    # Add Kalshi settlement data
    settlements = await repo.get_kalshi_settlements(limit=1000)
    kalshi_pnl = sum(s["total_pnl"] for s in settlements)
    kalshi_wins = sum(1 for s in settlements if s["total_pnl"] > 0)
    kalshi_losses = sum(1 for s in settlements if s["total_pnl"] < 0)

    metrics["kalshi_realized_pnl"] = round(kalshi_pnl, 2)
    metrics["kalshi_wins"] = kalshi_wins
    metrics["kalshi_losses"] = kalshi_losses
    metrics["kalshi_win_rate"] = round(kalshi_wins / max(kalshi_wins + kalshi_losses, 1) * 100, 1)

    return metrics


@router.get("/analytics/risk")
async def get_risk_metrics(
    request: Request,
    repo: Repository = Depends(get_repo),
):
    """Get current risk metrics — sector exposure, concentration, etc."""
    brokers = request.app.state.brokers
    alpaca = brokers.get("alpaca")

    result = {
        "positions": [],
        "sector_exposure": {},
        "top_positions_pct": [],
        "total_long_value": 0,
        "total_short_value": 0,
        "net_exposure": 0,
        "position_count": 0,
        "largest_position_pct": 0,
        "hhi_concentration": 0,  # Herfindahl-Hirschman Index
    }

    if not alpaca:
        return result

    try:
        account = await alpaca.get_account()
        positions = account.positions
        equity = account.equity

        if not positions or equity <= 0:
            return result

        total_long = sum(p.market_value for p in positions if p.quantity > 0)
        total_short = sum(abs(p.market_value) for p in positions if p.quantity < 0)

        pos_data = []
        for p in positions:
            pct = abs(p.market_value) / equity * 100
            pos_data.append({
                "symbol": p.symbol,
                "quantity": p.quantity,
                "market_value": round(p.market_value, 2),
                "pct_of_portfolio": round(pct, 1),
                "unrealized_pnl": round(p.unrealized_pnl, 2),
                "pnl_pct": round((p.current_price - p.avg_entry_price) / p.avg_entry_price * 100, 1) if p.avg_entry_price > 0 else 0,
                "is_short": p.quantity < 0,
            })

        pos_data.sort(key=lambda x: abs(x["market_value"]), reverse=True)

        # HHI concentration index (0-10000, higher = more concentrated)
        weights = [abs(p.market_value) / equity * 100 for p in positions]
        hhi = sum(w ** 2 for w in weights)

        # Sector exposure (using yfinance, best-effort)
        sector_map: dict[str, float] = defaultdict(float)
        try:
            import yfinance as yf
            symbols = [p.symbol for p in positions if p.quantity > 0]
            if symbols:
                for sym in symbols[:20]:  # Limit to 20 for speed
                    try:
                        info = yf.Ticker(sym).info
                        sector = info.get("sector", "Unknown")
                        val = next((p.market_value for p in positions if p.symbol == sym), 0)
                        sector_map[sector] += val
                    except Exception:
                        sector_map["Unknown"] += next((p.market_value for p in positions if p.symbol == sym), 0)
        except ImportError:
            pass

        result.update({
            "positions": pos_data,
            "sector_exposure": {k: round(v, 2) for k, v in sorted(sector_map.items(), key=lambda x: x[1], reverse=True)},
            "total_long_value": round(total_long, 2),
            "total_short_value": round(total_short, 2),
            "net_exposure": round(total_long - total_short, 2),
            "position_count": len(positions),
            "largest_position_pct": round(max(weights, default=0), 1),
            "hhi_concentration": round(hhi, 0),
            "equity": round(equity, 2),
        })
    except Exception as e:
        log.warning(f"Risk metrics error: {e}")

    return result


@router.get("/analytics/calendar")
async def get_calendar_returns(
    repo: Repository = Depends(get_repo),
):
    """Get daily returns for calendar heatmap visualization."""
    snapshots = await repo.get_snapshots(limit=365)
    # Group by date and sum daily_pnl
    daily: dict[str, float] = defaultdict(float)
    for s in snapshots:
        date = s["created_at"][:10] if s.get("created_at") else ""
        if date:
            daily[date] += s.get("daily_pnl", 0)

    return [
        {"date": d, "pnl": round(v, 2)}
        for d, v in sorted(daily.items())
    ]


@router.get("/analytics/earnings-check")
async def check_earnings(
    symbols: str = "",
    repo: Repository = Depends(get_repo),
):
    """Check upcoming earnings dates for given symbols."""
    if not symbols:
        # Get symbols from open positions
        return {"earnings": [], "note": "No symbols provided"}

    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    results = []

    try:
        import yfinance as yf
        for sym in symbol_list[:20]:
            try:
                ticker = yf.Ticker(sym)
                cal = ticker.calendar
                if cal is not None and not cal.empty:
                    earnings_date = str(cal.iloc[0, 0]) if len(cal.columns) > 0 else None
                    results.append({
                        "symbol": sym,
                        "next_earnings": earnings_date,
                        "warning": True if earnings_date else False,
                    })
                else:
                    results.append({"symbol": sym, "next_earnings": None, "warning": False})
            except Exception:
                results.append({"symbol": sym, "next_earnings": None, "warning": False})
    except ImportError:
        return {"earnings": [], "error": "yfinance not available"}

    return {"earnings": results}


@router.get("/analytics/correlation")
async def get_correlation_matrix(
    request: Request,
):
    """Get correlation matrix for current portfolio positions."""
    brokers = request.app.state.brokers
    alpaca = brokers.get("alpaca")
    if not alpaca:
        return {"matrix": {}, "symbols": []}

    try:
        account = await alpaca.get_account()
        symbols = [p.symbol for p in account.positions if p.quantity != 0]

        if len(symbols) < 2:
            return {"matrix": {}, "symbols": symbols}

        import yfinance as yf
        import numpy as np

        data = yf.download(symbols, period="3mo", progress=False)["Close"]
        if data.empty:
            return {"matrix": {}, "symbols": symbols}

        returns = data.pct_change().dropna()
        corr = returns.corr()

        matrix = {}
        for sym in symbols:
            if sym in corr.columns:
                matrix[sym] = {
                    s: round(float(corr.loc[sym, s]), 3)
                    for s in symbols if s in corr.columns
                }

        # Find highly correlated pairs (>0.8)
        high_corr_pairs = []
        for i, s1 in enumerate(symbols):
            for s2 in symbols[i + 1:]:
                if s1 in corr.columns and s2 in corr.columns:
                    c = float(corr.loc[s1, s2])
                    if abs(c) > 0.8:
                        high_corr_pairs.append({
                            "pair": f"{s1}/{s2}",
                            "correlation": round(c, 3),
                        })

        return {
            "matrix": matrix,
            "symbols": symbols,
            "high_correlation_pairs": high_corr_pairs,
        }
    except Exception as e:
        log.warning(f"Correlation matrix error: {e}")
        return {"matrix": {}, "symbols": [], "error": str(e)}


@router.get("/analytics/export-csv")
async def export_trades_csv(
    repo: Repository = Depends(get_repo),
):
    """Export all trades as CSV."""
    trades = await repo.get_trades_csv()

    output = io.StringIO()
    if trades:
        writer = csv.DictWriter(output, fieldnames=trades[0].keys())
        writer.writeheader()
        writer.writerows(trades)

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=trades_export.csv"},
    )
