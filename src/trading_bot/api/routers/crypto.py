"""Crypto trading API endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request

from trading_bot.api.deps import get_repo
from trading_bot.db.repository import Repository

router = APIRouter()


@router.get("/crypto/decisions")
async def get_crypto_decisions(
    limit: int = 50,
    symbol: str | None = None,
    repo: Repository = Depends(get_repo),
):
    """Get recent crypto agent decisions from the decision log."""
    return await repo.get_agent_decisions(
        agent_type="crypto_momentum", limit=limit, symbol=symbol,
    )


@router.get("/crypto/signals")
async def get_crypto_signals(
    symbol: str | None = None,
    limit: int = 50,
    repo: Repository = Depends(get_repo),
):
    """Get recent crypto technical signals from DB."""
    return await repo.get_crypto_signals(symbol=symbol, limit=limit)


@router.get("/crypto/signals/{symbol}")
async def get_crypto_signals_for_symbol(
    symbol: str,
    limit: int = 50,
    repo: Repository = Depends(get_repo),
):
    """Get signals for a specific crypto pair."""
    return await repo.get_crypto_signals(symbol=symbol, limit=limit)


@router.get("/crypto/bars/{symbol}")
async def get_crypto_bars(symbol: str, request: Request):
    """Fetch current bars + indicators for a crypto pair."""
    config = request.app.state.config
    from trading_bot.analysis.crypto_data import compute_crypto_technicals, get_crypto_bars as fetch_bars

    bars = await fetch_bars(
        api_key=config.alpaca.api_key,
        secret_key=config.alpaca.secret_key,
        symbol=symbol,
        timeframe=config.crypto.bar_timeframe,
        limit=config.crypto.lookback_bars,
    )
    signals = compute_crypto_technicals(bars, config.crypto)

    return {
        "bars": [b.model_dump(mode="json") for b in bars[-20:]],  # Last 20 bars
        "signals": signals.model_dump(mode="json"),
    }


@router.post("/crypto/scan")
async def trigger_crypto_scan(request: Request, repo: Repository = Depends(get_repo)):
    """Trigger a full crypto watchlist scan."""
    config = request.app.state.config
    broker = request.app.state.brokers.get("alpaca")
    if not broker:
        return {"error": "Alpaca broker not configured"}

    from trading_bot.strategies.crypto_momentum import CryptoMomentumStrategy

    strategy = CryptoMomentumStrategy(config)
    portfolio = await broker.get_account()
    result = await strategy.scan(portfolio=portfolio)

    # Log signals + decisions to DB
    for cd in result.metadata.get("crypto_decisions", []):
        signals = cd.get("technical_signals", {})
        sym = cd.get("symbol", "")
        await repo.insert_crypto_signal(
            symbol=sym,
            rsi_14=signals.get("rsi_14"),
            macd=signals.get("macd"),
            macd_signal=signals.get("macd_signal"),
            bb_pct_b=signals.get("bb_pct_b"),
            momentum_score=signals.get("momentum_score", 0.0),
            mean_reversion_score=signals.get("mean_reversion_score", 0.0),
            composite_signal=signals.get("composite_signal", 0.0),
            signal_direction=signals.get("signal_direction", "hold"),
            current_price=signals.get("current_price", 0.0),
            llm_override=cd.get("llm_override", False),
            llm_reasoning=cd.get("llm_reasoning", ""),
        )
        # Log decision
        direction = signals.get("signal_direction", "hold")
        await repo.insert_agent_decision(
            agent_type="crypto_momentum",
            symbol=sym,
            action=direction,
            confidence=min(0.95, abs(signals.get("composite_signal", 0))),
            reasoning=cd.get("llm_reasoning", "") or f"Composite: {signals.get('composite_signal', 0):.3f}",
            signals_json=json.dumps(signals),
            outcome="scan_result",
        )

    # Log filtered symbols
    for scanned in result.metadata.get("all_scanned", []):
        sym = scanned.get("symbol", "")
        if sym:
            signals = scanned.get("technical_signals", {})
            await repo.insert_agent_decision(
                agent_type="crypto_momentum",
                symbol=sym,
                action="hold",
                confidence=0.0,
                reasoning=f"Filtered ({scanned.get('filtered_reason', 'unknown')})",
                signals_json=json.dumps(signals),
                outcome="filtered_signal",
            )

    return {
        "symbols_scanned": result.metadata.get("symbols_scanned", 0),
        "signals_found": result.metadata.get("signals_found", 0),
        "decisions": [d.model_dump() for d in result.decisions],
        "all_scanned": result.metadata.get("all_scanned", []),
        "crypto_details": result.metadata.get("crypto_decisions", []),
    }


@router.get("/crypto/portfolio")
async def get_crypto_portfolio(request: Request):
    """Get crypto-specific positions from Alpaca."""
    broker = request.app.state.brokers.get("alpaca")
    if not broker:
        return {"error": "Alpaca broker not configured"}

    portfolio = await broker.get_account()
    # Filter to crypto positions (symbols with /)
    crypto_positions = [
        p.model_dump() for p in portfolio.positions if "/" in p.symbol
    ]
    return {
        "positions": crypto_positions,
        "total_value": sum(p.get("market_value", 0) for p in crypto_positions),
    }
