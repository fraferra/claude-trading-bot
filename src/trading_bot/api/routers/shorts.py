"""Short selling endpoints — proposals, approve/reject, manual scan."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException

from trading_bot.api.deps import get_brokers, get_config, get_repo, get_risk_manager
from trading_bot.config import Config
from trading_bot.db.repository import Repository
from trading_bot.models import OrderRequest, OrderType, Platform, Side
from trading_bot.risk.manager import RiskManager
from trading_bot.strategies.short_scorer import broad_market_short_scan, score_short
from trading_bot.utils.logging import log

router = APIRouter()


@router.get("/shorts/proposals")
async def get_proposals(
    status: str = "pending_approval",
    limit: int = 50,
    repo: Repository = Depends(get_repo),
):
    """List short proposals filtered by status."""
    return await repo.get_agent_decisions(
        agent_type="short_scorer", outcome=status, limit=limit,
    )


@router.get("/shorts/decisions")
async def get_short_decisions(
    limit: int = 50,
    repo: Repository = Depends(get_repo),
):
    """List all short scorer decisions (any status)."""
    return await repo.get_agent_decisions(
        agent_type="short_scorer", limit=limit,
    )


@router.post("/shorts/{decision_id}/approve")
async def approve_short(
    decision_id: int,
    repo: Repository = Depends(get_repo),
    config: Config = Depends(get_config),
    risk_manager: RiskManager = Depends(get_risk_manager),
    brokers: dict = Depends(get_brokers),
):
    """Approve a short proposal — run risk checks and execute SELL order."""
    decision = await repo.get_agent_decision_by_id(decision_id)
    if not decision:
        raise HTTPException(404, "Decision not found")
    if decision["outcome"] != "pending_approval":
        raise HTTPException(400, f"Decision already {decision['outcome']}")

    symbol = decision["symbol"]
    signals = json.loads(decision.get("signals_json", "{}"))
    current_price = signals.get("current_price", 0)
    atr = signals.get("atr_14", 0)

    if current_price <= 0:
        await repo.update_agent_decision_outcome(decision_id, "rejected_error")
        raise HTTPException(400, "No price data available for this symbol")

    # Get Alpaca broker
    alpaca = brokers.get("alpaca")
    if not alpaca:
        raise HTTPException(400, "Alpaca broker not configured")

    # Calculate position size using ATR
    portfolio = await alpaca.get_account()
    short_cfg = config.shorts

    if atr and atr > 0:
        shares = risk_manager.calculate_short_position_size(
            portfolio.equity, current_price, atr, short_cfg,
        )
    else:
        # Fallback: simple risk-based sizing
        risk_amount = portfolio.equity * short_cfg.risk_per_trade_pct
        shares = risk_amount / current_price if current_price > 0 else 0

    shares = max(1, int(shares))  # At least 1 share, integer

    # Build order
    order = OrderRequest(
        symbol=symbol,
        side=Side.SELL,
        quantity=float(shares),
        order_type=OrderType.MARKET,
        platform=Platform.ALPACA,
    )

    # Risk check
    risk_check = risk_manager.check_short_order(order, portfolio, current_price, short_cfg)
    if not risk_check.approved:
        await repo.update_agent_decision_outcome(decision_id, "rejected_risk")
        raise HTTPException(400, f"Risk check failed: {risk_check.reason}")

    if risk_check.adjusted_quantity is not None:
        order.quantity = max(1, int(risk_check.adjusted_quantity))

    # Execute
    try:
        result = await alpaca.submit_order(order)
        risk_manager.record_trade()

        trade_id = await repo.insert_trade(
            order_id=result.order_id,
            symbol=symbol,
            side="sell",
            quantity=order.quantity,
            filled_price=result.filled_price,
            platform="alpaca",
            source="short_approval",
            strategy_name="short_scorer",
            reasoning=decision.get("reasoning", "")[:500],
            confidence=decision.get("confidence"),
            status=result.status.value,
        )
        await repo.update_agent_decision_outcome(decision_id, "approved", trade_id)

        return {
            "status": "approved",
            "trade_id": trade_id,
            "order_id": result.order_id,
            "symbol": symbol,
            "shares": order.quantity,
            "filled_price": result.filled_price,
        }
    except Exception as e:
        await repo.update_agent_decision_outcome(decision_id, "execution_failed")
        raise HTTPException(500, f"Order execution failed: {e}")


@router.post("/shorts/{decision_id}/reject")
async def reject_short(
    decision_id: int,
    repo: Repository = Depends(get_repo),
):
    """Reject a short proposal."""
    decision = await repo.get_agent_decision_by_id(decision_id)
    if not decision:
        raise HTTPException(404, "Decision not found")
    if decision["outcome"] != "pending_approval":
        raise HTTPException(400, f"Decision already {decision['outcome']}")

    await repo.update_agent_decision_outcome(decision_id, "rejected")
    return {"status": "rejected", "decision_id": decision_id}


@router.post("/shorts/scan")
async def manual_scan(
    config: Config = Depends(get_config),
    repo: Repository = Depends(get_repo),
):
    """Manually trigger a short scan — broad market or watchlist."""
    short_cfg = config.shorts

    # Decide: broad market scan vs watchlist-only
    if short_cfg.broad_market_scan and not short_cfg.watchlist:
        scored_results = await broad_market_short_scan(
            rsi_min=short_cfg.prefilter_rsi_min,
            near_high_pct=short_cfg.prefilter_near_high_pct,
            max_prefilter=short_cfg.max_prefilter_candidates,
        )
        scanned_label = "broad market (~500 tickers)"
    else:
        watchlist = short_cfg.watchlist or config.stocks.watchlist
        if not watchlist:
            return {"proposals": 0, "scanned": "0", "error": "No watchlist configured"}

        sem = asyncio.Semaphore(5)

        async def _score(sym: str):
            async with sem:
                return await score_short(sym)

        raw = await asyncio.gather(
            *[_score(s) for s in watchlist], return_exceptions=True,
        )
        scored_results = [r for r in raw if not isinstance(r, Exception)]
        scanned_label = f"{len(watchlist)} watchlist symbols"

    # Create proposals for those passing the threshold
    proposals = []
    for r in scored_results:
        signals_data = {
            "rsi_2": r.rsi_2,
            "rsi_14": r.rsi_14,
            "bb_pct_b": r.bb_pct_b,
            "macd_histogram": r.macd_histogram,
            "macd_hist_declining": r.macd_hist_declining,
            "volume_ratio": r.volume_ratio,
            "price_vs_sma200": r.price_vs_sma200,
            "atr_14": r.atr_14,
            "pe_ratio": r.pe_ratio,
            "current_price": r.current_price,
            "short_score": r.short_score,
            "signal_breakdown": r.signal_breakdown,
        }

        if r.short_score <= short_cfg.min_short_score:
            decision_id = await repo.insert_agent_decision(
                agent_type="short_scorer",
                symbol=r.symbol,
                action="sell",
                confidence=min(0.95, abs(r.short_score)),
                reasoning=f"Short score: {r.short_score:.2f}",
                signals_json=json.dumps(signals_data),
                outcome="pending_approval",
            )
            proposals.append({
                "decision_id": decision_id,
                "symbol": r.symbol,
                "short_score": r.short_score,
                "current_price": r.current_price,
            })

    return {
        "proposals": len(proposals),
        "scanned": scanned_label,
        "scored": len(scored_results),
        "results": proposals,
    }
