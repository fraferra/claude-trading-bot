"""Lightweight backtesting engine.

Replays historical price data through the stock-scoring strategy
using technical + fundamental signals (no LLM sentiment calls).
Simulates portfolio growth with configurable parameters.
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime

import yfinance as yf

from trading_bot.utils.logging import log


@dataclass
class BacktestParams:
    """Parameters for a backtest run."""
    symbols: list[str]
    start_date: str  # YYYY-MM-DD
    end_date: str  # YYYY-MM-DD
    initial_capital: float = 10_000.0
    trade_amount_usd: float = 500.0
    stop_loss_pct: float = 8.0
    take_profit_pct: float = 25.0
    # Signal weights
    technical_weight: float = 0.35
    fundamental_weight: float = 0.35
    momentum_weight: float = 0.30
    # Thresholds
    buy_threshold: float = 0.15
    sell_threshold: float = -0.15


@dataclass
class BacktestTrade:
    """A single backtest trade."""
    date: str
    symbol: str
    side: str  # "buy" or "sell"
    price: float
    quantity: float
    pnl: float = 0.0
    reason: str = ""


@dataclass
class BacktestResult:
    """Results from a backtest run."""
    params: BacktestParams
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[dict] = field(default_factory=list)  # [{date, equity}]
    total_return_pct: float = 0.0
    buy_hold_return_pct: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    final_equity: float = 0.0


def _compute_sma(prices: list[float], window: int) -> float | None:
    """Simple moving average of last `window` values."""
    if len(prices) < window:
        return None
    return sum(prices[-window:]) / window


def _compute_rsi(prices: list[float], period: int = 14) -> float | None:
    """RSI from price series."""
    if len(prices) < period + 1:
        return None
    deltas = [prices[i] - prices[i - 1] for i in range(len(prices) - period, len(prices))]
    gains = [d for d in deltas if d > 0]
    losses = [-d for d in deltas if d < 0]
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _compute_momentum(prices: list[float], lookback: int = 20) -> float:
    """Momentum as % change over lookback period."""
    if len(prices) < lookback:
        return 0.0
    old = prices[-lookback]
    if old <= 0:
        return 0.0
    return (prices[-1] - old) / old


def _score_technical(prices: list[float]) -> float:
    """Score -1 to 1 from price technicals."""
    if len(prices) < 5:
        return 0.0

    price = prices[-1]
    sma20 = _compute_sma(prices, 20)
    sma50 = _compute_sma(prices, 50)
    rsi = _compute_rsi(prices)

    sma_signal = 0.0
    if sma20 and sma50:
        if price > sma20 > sma50:
            sma_signal = 1.0
        elif price < sma20 < sma50:
            sma_signal = -1.0
        elif price > sma20:
            sma_signal = 0.5
        else:
            sma_signal = -0.5

    rsi_signal = 0.0
    if rsi is not None:
        if rsi < 30:
            rsi_signal = 1.0
        elif rsi < 40:
            rsi_signal = 0.5
        elif rsi > 70:
            rsi_signal = -1.0
        elif rsi > 60:
            rsi_signal = -0.5

    momentum = max(-1.0, min(1.0, _compute_momentum(prices) * 5))

    return max(-1.0, min(1.0, (sma_signal + rsi_signal + momentum) / 3.0))


def _score_fundamental_static(pe: float | None, fwd_pe: float | None, beta: float | None) -> float:
    """Simplified fundamental score from static fundamentals."""
    pe_score = 0.0
    if pe:
        if pe < 15:
            pe_score = 0.8
        elif pe < 25:
            pe_score = 0.3
        elif pe < 35:
            pe_score = -0.3
        else:
            pe_score = -0.8

    growth = 0.0
    if pe and fwd_pe and pe > 0:
        ratio = fwd_pe / pe
        if ratio < 0.8:
            growth = 0.8
        elif ratio < 1.0:
            growth = 0.3
        elif ratio > 1.2:
            growth = -0.5

    quality = 0.0
    if beta:
        if beta < 0.8:
            quality += 0.3
        elif beta > 1.5:
            quality -= 0.3

    return max(-1.0, min(1.0, (pe_score + growth + quality) / 3.0))


def _download_close_prices(symbols: list[str], start: str, end: str):
    """Download close prices, handling yfinance column format differences.

    Modern yfinance (>=0.2.x) ALWAYS returns MultiIndex columns even for
    a single symbol: (Price, Ticker).  We must flatten to simple string
    column names matching the ticker symbols.

    Returns a DataFrame with one column per symbol named by the symbol ticker.
    """
    import pandas as pd

    data = yf.download(symbols, start=start, end=end, progress=False, auto_adjust=True)
    if data.empty:
        return pd.DataFrame()

    # --- Always handle MultiIndex (modern yfinance default) ---
    if isinstance(data.columns, pd.MultiIndex):
        # Select "Close" price group → drops first level, leaves ticker names
        if "Close" in data.columns.get_level_values(0):
            close_df = data["Close"]
        else:
            # Fallback: take first column group
            first_level = data.columns.get_level_values(0).unique()[0]
            close_df = data[first_level]

        # data["Close"] for a single symbol returns a Series, not DataFrame
        if isinstance(close_df, pd.Series):
            close_df = close_df.to_frame(name=symbols[0])
        else:
            # Flatten any remaining MultiIndex and ensure plain string names
            close_df.columns = [str(c) for c in close_df.columns]

        return close_df

    # --- Flat columns (older yfinance or edge cases) ---
    if "Close" in data.columns:
        if len(symbols) == 1:
            return data[["Close"]].rename(columns={"Close": symbols[0]})
        return data[["Close"]]

    return data


async def run_backtest(params: BacktestParams) -> BacktestResult:
    """Execute a backtest with the given parameters.

    Downloads historical data, replays day-by-day through
    simplified technical + fundamental scoring (no LLM calls),
    and simulates trades with stop-loss/take-profit and signal-based exits.
    """
    result = BacktestResult(params=params, final_equity=params.initial_capital)

    if not params.symbols:
        return result

    # Download data for all symbols
    log.info(f"Backtest: downloading data for {params.symbols} from {params.start_date} to {params.end_date}")

    # Need extra history for indicators (SMA50 needs 50 bars)
    import pandas as pd
    warmup_start = pd.Timestamp(params.start_date) - pd.Timedelta(days=80)

    try:
        close_df = _download_close_prices(
            params.symbols,
            warmup_start.strftime("%Y-%m-%d"),
            params.end_date,
        )
    except Exception as e:
        log.warning(f"Backtest data download failed: {e}")
        return result

    if close_df.empty:
        log.warning("Backtest: no data returned from yfinance")
        return result

    log.info(f"Backtest: loaded {len(close_df)} rows, columns: {list(close_df.columns)}")

    # Get fundamentals (static, fetched once)
    fundamentals: dict[str, dict] = {}
    for sym in params.symbols:
        try:
            info = yf.Ticker(sym).info
            fundamentals[sym] = {
                "pe": info.get("trailingPE"),
                "fwd_pe": info.get("forwardPE"),
                "beta": info.get("beta"),
            }
        except Exception:
            fundamentals[sym] = {"pe": None, "fwd_pe": None, "beta": None}

    # Portfolio state
    cash = params.initial_capital
    positions: dict[str, dict] = {}  # {symbol: {qty, entry_price, high_price}}
    equity_curve: list[dict] = []
    trades: list[BacktestTrade] = []

    # Iterate day by day starting from start_date
    try:
        trading_dates = close_df.loc[params.start_date:].index
    except Exception:
        trading_dates = close_df.index

    log.info(f"Backtest: {len(trading_dates)} trading days to simulate")

    for date in trading_dates:
        date_str = str(date.date()) if hasattr(date, 'date') else str(date)[:10]

        for sym in params.symbols:
            # Get today's price
            try:
                if sym in close_df.columns:
                    price = float(close_df.at[date, sym])
                else:
                    continue
            except (KeyError, TypeError, ValueError):
                continue

            if math.isnan(price) or price <= 0:
                continue

            # Get price history up to this date for indicators
            try:
                hist_series = close_df[sym].loc[:date].dropna()
                hist_prices = hist_series.tolist()
            except Exception:
                continue

            # --- Check exits for open positions ---
            if sym in positions:
                pos = positions[sym]
                entry = pos["entry_price"]
                pnl_pct = (price - entry) / entry * 100

                # Update trailing high
                if price > pos["high_price"]:
                    pos["high_price"] = price

                trailing_drop = (pos["high_price"] - price) / pos["high_price"] * 100

                should_sell = False
                reason = ""

                # Hard stop-loss
                if pnl_pct <= -params.stop_loss_pct:
                    should_sell = True
                    reason = f"stop-loss ({pnl_pct:.1f}%)"

                # Trailing stop (only if in profit)
                elif trailing_drop >= params.stop_loss_pct and pnl_pct > 0:
                    should_sell = True
                    reason = f"trailing-stop ({trailing_drop:.1f}% from peak)"

                # Take-profit
                elif pnl_pct >= params.take_profit_pct:
                    should_sell = True
                    reason = f"take-profit ({pnl_pct:.1f}%)"

                # Signal-based exit: sell if composite score goes bearish
                elif len(hist_prices) >= 50:
                    tech = _score_technical(hist_prices)
                    momentum = max(-1.0, min(1.0, _compute_momentum(hist_prices) * 5))
                    exit_score = (tech + momentum) / 2.0
                    if exit_score <= params.sell_threshold:
                        should_sell = True
                        reason = f"signal-exit ({exit_score:.2f})"

                if should_sell:
                    pnl = (price - entry) * pos["qty"]
                    cash += price * pos["qty"]
                    trades.append(BacktestTrade(
                        date=date_str, symbol=sym, side="sell",
                        price=price, quantity=pos["qty"], pnl=pnl, reason=reason,
                    ))
                    del positions[sym]
                    continue

            # --- Check entry for new positions ---
            if sym not in positions and len(hist_prices) >= 50:
                tech = _score_technical(hist_prices)
                fund_data = fundamentals.get(sym, {})
                fund = _score_fundamental_static(
                    fund_data.get("pe"), fund_data.get("fwd_pe"), fund_data.get("beta")
                )
                momentum = max(-1.0, min(1.0, _compute_momentum(hist_prices) * 5))

                composite = (
                    params.technical_weight * tech
                    + params.fundamental_weight * fund
                    + params.momentum_weight * momentum
                )

                if composite >= params.buy_threshold and cash >= params.trade_amount_usd:
                    qty = params.trade_amount_usd / price
                    cash -= params.trade_amount_usd
                    positions[sym] = {"qty": qty, "entry_price": price, "high_price": price}
                    trades.append(BacktestTrade(
                        date=date_str, symbol=sym, side="buy",
                        price=price, quantity=qty,
                        reason=f"signal={composite:.2f} (t={tech:.2f} f={fund:.2f} m={momentum:.2f})",
                    ))

        # Calculate equity at end of day
        pos_value = 0.0
        for sym, pos in positions.items():
            try:
                if sym in close_df.columns:
                    p = float(close_df.at[date, sym])
                    if not math.isnan(p):
                        pos_value += p * pos["qty"]
                    else:
                        pos_value += pos["entry_price"] * pos["qty"]
                else:
                    pos_value += pos["entry_price"] * pos["qty"]
            except (KeyError, TypeError, ValueError):
                pos_value += pos["entry_price"] * pos["qty"]

        equity = cash + pos_value
        equity_curve.append({"date": date_str, "equity": round(equity, 2)})

    # Close remaining open positions at last price for accurate stats
    if equity_curve:
        last_date = trading_dates[-1] if len(trading_dates) > 0 else None
        for sym in list(positions.keys()):
            pos = positions[sym]
            try:
                if sym in close_df.columns and last_date is not None:
                    last_price = float(close_df.at[last_date, sym])
                    if not math.isnan(last_price):
                        pnl = (last_price - pos["entry_price"]) * pos["qty"]
                        cash += last_price * pos["qty"]
                        trades.append(BacktestTrade(
                            date=equity_curve[-1]["date"], symbol=sym, side="sell",
                            price=last_price, quantity=pos["qty"], pnl=pnl,
                            reason="end-of-backtest close",
                        ))
                        del positions[sym]
            except (KeyError, TypeError, ValueError):
                pass

    # Calculate buy-and-hold return
    buy_hold = 0.0
    if len(trading_dates) >= 2:
        initial_prices = {}
        for sym in params.symbols:
            try:
                if sym in close_df.columns:
                    p = float(close_df.at[trading_dates[0], sym])
                    if not math.isnan(p):
                        initial_prices[sym] = p
            except (KeyError, TypeError, ValueError):
                pass
        if initial_prices:
            per_stock = params.initial_capital / len(initial_prices)
            final_value = 0.0
            for sym, init_price in initial_prices.items():
                try:
                    final_price = float(close_df.at[trading_dates[-1], sym])
                    if not math.isnan(final_price):
                        final_value += per_stock * (final_price / init_price)
                except (KeyError, TypeError, ValueError):
                    final_value += per_stock
            buy_hold = (final_value - params.initial_capital) / params.initial_capital * 100

    # Statistics
    sell_trades = [t for t in trades if t.side == "sell"]
    wins = [t for t in sell_trades if t.pnl > 0]
    losses = [t for t in sell_trades if t.pnl < 0]

    total_win = sum(t.pnl for t in wins) if wins else 0
    total_loss = abs(sum(t.pnl for t in losses)) if losses else 0

    # Sharpe from equity curve
    if len(equity_curve) > 1:
        daily_returns = []
        for i in range(1, len(equity_curve)):
            prev = equity_curve[i - 1]["equity"]
            curr = equity_curve[i]["equity"]
            if prev > 0:
                daily_returns.append((curr - prev) / prev)
        if daily_returns:
            avg_r = sum(daily_returns) / len(daily_returns)
            std_r = math.sqrt(sum((r - avg_r) ** 2 for r in daily_returns) / max(len(daily_returns) - 1, 1))
            sharpe = (avg_r / std_r * math.sqrt(252)) if std_r > 0 else 0
        else:
            sharpe = 0
    else:
        sharpe = 0

    # Max drawdown
    peak = 0.0
    max_dd = 0.0
    for point in equity_curve:
        eq = point["equity"]
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    # Recalculate final equity including closed-out positions
    if equity_curve:
        final_equity = equity_curve[-1]["equity"]
    else:
        final_equity = params.initial_capital

    result.trades = trades
    result.equity_curve = equity_curve
    result.total_return_pct = round((final_equity - params.initial_capital) / params.initial_capital * 100, 2)
    result.buy_hold_return_pct = round(buy_hold, 2)
    result.sharpe_ratio = round(sharpe, 2)
    result.max_drawdown_pct = round(max_dd, 2)
    result.total_trades = len(sell_trades)
    result.winning_trades = len(wins)
    result.losing_trades = len(losses)
    result.win_rate = round(len(wins) / max(len(sell_trades), 1) * 100, 1)
    result.avg_win = round(total_win / max(len(wins), 1), 2)
    result.avg_loss = round(-total_loss / max(len(losses), 1), 2)
    result.profit_factor = round(total_win / max(total_loss, 0.01), 2)
    result.final_equity = round(final_equity, 2)

    log.info(
        f"Backtest complete: {len(trades)} trades, "
        f"return={result.total_return_pct}%, "
        f"buy&hold={result.buy_hold_return_pct}%, "
        f"final=${result.final_equity}"
    )

    return result
