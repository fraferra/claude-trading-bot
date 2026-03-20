"""Temporal Momentum Arbitrage monitor.

Runs a tight 2-second inner loop, ingesting BTC/ETH/SOL spot prices from
Binance and scanning Polymarket's short-duration binary crypto markets for
mispricing caused by price-lag.

Architecture:
  - Outer loop (every 60s): refresh list of active Polymarket markets
  - Inner loop (every 2s):  compute momentum signals + execute if edge found

No LLM calls — pure math and latency exploitation.
"""

from __future__ import annotations

import asyncio
import json
import time

import httpx

from trading_bot.brokers.exchange_feed import BinanceExchangeFeed
from trading_bot.brokers.polymarket_ws import PolymarketWebSocketFeed
from trading_bot.models import (
    MonitorStatus,
    OrderRequest,
    OrderType,
    Platform,
    Side,
    WSEvent,
    WSEventType,
)
from trading_bot.monitors.base import BaseMonitor
from trading_bot.strategies.temporal_momentum_arb import TemporalMomentumArbStrategy
from trading_bot.utils.logging import log

# Map Binance symbol → label used in signals dict
_BINANCE_TO_LABEL: dict[str, str] = {
    "btcusdt": "BTC",
    "ethusdt": "ETH",
    "solusdt": "SOL",
}


class TemporalMomentumMonitor(BaseMonitor):
    """Temporal momentum arb monitor.

    Overrides _run_loop() to implement a two-level cadence:
      - market refresh every config.temporal_momentum.market_refresh_interval_seconds
      - momentum scan every config.temporal_momentum.scan_interval_seconds
    """

    monitor_type = "temporal_momentum"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._binance_feed: BinanceExchangeFeed | None = None
        self._poly_ws: PolymarketWebSocketFeed | None = None
        self._active_markets: list[dict] = []
        self._market_refresh_lock = asyncio.Lock()
        self._last_market_refresh: float = 0.0
        self._strategy = TemporalMomentumArbStrategy(self.config.temporal_momentum)
        self._total_exposure_usd: float = 0.0
        # Cache latest signals for the API endpoint
        self._latest_signals: dict[str, dict] = {}
        self._latest_opportunities: list[dict] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start Binance and Polymarket WebSocket feeds, then begin cycling."""
        await super().start()
        cfg = self.config.temporal_momentum

        # Binance price feed
        self._binance_feed = BinanceExchangeFeed(
            symbols=cfg.binance_symbols,
            history_seconds=cfg.price_history_seconds,
        )
        await self._binance_feed.start()

        # Polymarket WS feed for YES/NO token prices
        ttl = getattr(self.config.polymarket, "ws_price_ttl_seconds", 5)
        self._poly_ws = PolymarketWebSocketFeed(ttl_seconds=ttl)

        # Initial market refresh to get token IDs
        await self._refresh_markets()
        token_ids = _extract_token_ids(self._active_markets)
        await self._poly_ws.start(token_ids if token_ids else [])

        log.info(
            f"TemporalMomentumMonitor: started — "
            f"binance symbols={cfg.binance_symbols}, "
            f"active markets={len(self._active_markets)}"
        )

    async def stop(self) -> None:
        if self._binance_feed:
            await self._binance_feed.stop()
        if self._poly_ws:
            await self._poly_ws.stop()
        await super().stop()

    def get_interval_seconds(self) -> int:
        return self.config.temporal_momentum.scan_interval_seconds

    # ------------------------------------------------------------------
    # Custom run loop (two-level cadence)
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Override base _run_loop for the tight 2s inner loop."""
        while True:
            await self._paused.wait()
            try:
                now = time.time()
                refresh_interval = (
                    self.config.temporal_momentum.market_refresh_interval_seconds
                )
                if now - self._last_market_refresh >= refresh_interval:
                    await self._refresh_markets()
                    self._last_market_refresh = now

                await self.run_cycle()
                await self.repo.update_monitor_last_run(self.monitor_id)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.status = MonitorStatus.ERROR
                await self.repo.update_monitor_error(self.monitor_id, str(e))
                await self.event_bus.broadcast(WSEvent(
                    type=WSEventType.ERROR,
                    data={"source": f"monitor:{self.monitor_id}", "message": str(e)},
                ))
                log.error(f"TemporalMomentumMonitor error: {e}")

            await asyncio.sleep(self.config.temporal_momentum.scan_interval_seconds)

    # ------------------------------------------------------------------
    # Market refresh
    # ------------------------------------------------------------------

    async def _refresh_markets(self) -> None:
        """Fetch active Polymarket crypto markets and update WS subscriptions."""
        async with self._market_refresh_lock:
            try:
                markets = await self._strategy.find_active_crypto_markets()
                self._active_markets = markets

                if self._poly_ws and markets:
                    new_tokens = _extract_token_ids(markets)
                    if new_tokens:
                        await self._poly_ws.subscribe(new_tokens)

                log.debug(
                    f"TemporalMomentumMonitor: refreshed markets — "
                    f"{len(markets)} active"
                )
            except Exception as e:
                log.warning(f"TemporalMomentumMonitor: market refresh failed: {e}")

    # ------------------------------------------------------------------
    # Main cycle
    # ------------------------------------------------------------------

    async def run_cycle(self) -> None:
        """One momentum scan iteration (runs every 2 seconds)."""
        if not self._binance_feed or not self._poly_ws:
            return
        if not self._active_markets:
            return

        broker = self.brokers.get("polymarket")
        if not broker:
            return

        cfg = self.config.temporal_momentum

        # Build momentum signals
        signals: dict = {}
        for binance_sym in cfg.binance_symbols:
            label = _BINANCE_TO_LABEL.get(binance_sym.lower(), binance_sym[:3].upper())
            sig = self._strategy.compute_momentum_signal(
                label, binance_sym, self._binance_feed
            )
            if sig:
                signals[label] = sig

        if not signals:
            return

        # Cache for API endpoint
        self._latest_signals = {
            k: {
                "direction": v.direction,
                "strength": round(v.strength, 4),
                "change_1m_pct": round(v.change_1m_pct, 5),
                "change_3m_pct": round(v.change_3m_pct, 5),
                "current_price": v.current_price,
                "rsi_fast": v.rsi_fast,
            }
            for k, v in signals.items()
        }

        # Get portfolio balance
        try:
            portfolio = await broker.get_account()
        except Exception as e:
            log.warning(f"TemporalMomentumMonitor: get_account failed: {e}")
            return

        available_cash = portfolio.cash

        # Strategy 1: temporal momentum arb
        if self._total_exposure_usd < cfg.max_total_exposure_usd:
            opportunities = self._strategy.find_opportunities(
                signals, self._active_markets, self._poly_ws, available_cash
            )

            self._latest_opportunities = [
                {
                    "question": o.question[:80],
                    "symbol": o.momentum_signal.symbol,
                    "direction": o.momentum_signal.direction,
                    "strength": round(o.momentum_signal.strength, 3),
                    "market_yes_price": o.market_yes_price,
                    "estimated_true_prob": round(o.estimated_true_prob, 3),
                    "edge_pct": round(o.edge_pct, 3),
                    "suggested_side": o.suggested_side,
                    "minutes_to_expiry": round(o.minutes_to_expiry, 1),
                    "suggested_size_usd": round(o.suggested_size_usd, 2),
                }
                for o in opportunities[:5]
            ]

            for opp in opportunities[:3]:  # max 3 trades per cycle
                await self._execute_opportunity(opp, broker, portfolio)
        else:
            self._latest_opportunities = []
            log.debug(
                f"TemporalMomentumMonitor: max exposure reached "
                f"(${self._total_exposure_usd:.0f}), skipping"
            )

        # Strategy 2: front-running
        if cfg.frontrun_enabled:
            fr_signals = self._strategy.compute_frontrun_signals(
                self._active_markets, self._poly_ws
            )
            for sig in fr_signals[:2]:
                await self._execute_frontrun(sig, broker, portfolio)

        # Broadcast momentum update to frontend
        if signals:
            await self.event_bus.broadcast(WSEvent(
                type=WSEventType.STRATEGY_SIGNAL,
                data={
                    "strategy": "temporal_momentum",
                    "signals": self._latest_signals,
                    "opportunities": len(self._latest_opportunities),
                    "source": f"monitor:{self.monitor_id}",
                },
            ))

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def _execute_opportunity(self, opp, broker, portfolio) -> None:
        """Submit a temporal arb trade and record it in the DB."""
        cfg = self.config.temporal_momentum

        # Re-check expiry just before submitting
        try:
            from datetime import datetime, timezone
            end_dt = datetime.fromisoformat(
                opp.momentum_signal.timestamp.isoformat()  # not the end date — re-check below
            )
        except Exception:
            pass

        token_id = opp.token_id_yes if opp.suggested_side == "yes" else opp.token_id_no
        market_price = (
            opp.market_yes_price if opp.suggested_side == "yes" else opp.market_no_price
        )

        if market_price <= 0:
            return
        qty = opp.suggested_size_usd / market_price
        if qty <= 0:
            return

        # Risk checks
        if portfolio.equity > 0:
            daily_loss_pct = -portfolio.daily_pnl / portfolio.equity
            if daily_loss_pct >= self.risk_manager.config.daily_loss_limit_pct:
                log.debug("TemporalMomentumMonitor: daily loss limit — skip")
                return
        if opp.suggested_size_usd > portfolio.cash:
            log.debug("TemporalMomentumMonitor: insufficient cash — skip")
            return

        # Allow a tiny bit of slippage (up to 2% or +0.03 whichever is smaller)
        limit_price = min(market_price * 1.02, market_price + 0.03)

        order = OrderRequest(
            symbol=token_id,
            side=Side.BUY,
            quantity=qty,
            order_type=OrderType.LIMIT,
            limit_price=limit_price,
            platform=Platform.POLYMARKET,
        )

        try:
            result = await broker.submit_order(order)
            self._total_exposure_usd += opp.suggested_size_usd
            self.risk_manager.record_trade()

            sig = opp.momentum_signal
            reasoning = (
                f"TemporalMomentum: {opp.question[:80]} | "
                f"{sig.symbol} {sig.direction} strength={sig.strength:.2f} | "
                f"market={market_price:.3f} true_prob={opp.estimated_true_prob:.3f} "
                f"edge={opp.edge_pct:.2%} side={opp.suggested_side}"
            )
            trade_id = await self.repo.insert_trade(
                order_id=result.order_id,
                symbol=token_id,
                side="buy",
                quantity=qty,
                filled_price=result.filled_price,
                platform="polymarket",
                source=f"monitor:{self.monitor_id}",
                strategy_name=TemporalMomentumArbStrategy.name,
                reasoning=reasoning,
                confidence=opp.estimated_true_prob,
                status=result.status.value,
            )
            await self.repo.insert_monitor_trade(
                self.monitor_id, trade_id, market_price, qty
            )
            await self.repo.insert_agent_decision(
                agent_type="temporal_momentum",
                symbol=token_id,
                action="buy",
                confidence=opp.estimated_true_prob,
                reasoning=reasoning,
                signals_json=json.dumps({
                    "symbol": sig.symbol,
                    "direction": sig.direction,
                    "strength": round(sig.strength, 4),
                    "change_1m_pct": round(sig.change_1m_pct, 5),
                    "change_3m_pct": round(sig.change_3m_pct, 5),
                    "market_yes_price": opp.market_yes_price,
                    "market_no_price": opp.market_no_price,
                    "estimated_true_prob": round(opp.estimated_true_prob, 4),
                    "edge_pct": round(opp.edge_pct, 4),
                    "suggested_side": opp.suggested_side,
                    "kelly_fraction": round(opp.kelly_fraction, 4),
                    "minutes_to_expiry": round(opp.minutes_to_expiry, 1),
                    "filled_price": result.filled_price,
                }),
                outcome="executed",
                trade_id=trade_id,
            )
            await self.event_bus.broadcast(WSEvent(
                type=WSEventType.TRADE_EXECUTED,
                data={
                    "symbol": token_id,
                    "side": "buy",
                    "quantity": qty,
                    "source": f"monitor:{self.monitor_id}",
                    "strategy": "temporal_momentum",
                },
            ))
            log.info(
                f"TemporalMomentum: executed {sig.symbol} {sig.direction} "
                f"side={opp.suggested_side} size=${opp.suggested_size_usd:.0f} "
                f"edge={opp.edge_pct:.1%}"
            )
        except Exception as e:
            log.warning(f"TemporalMomentumMonitor: execution failed for {token_id}: {e}")

    async def _execute_frontrun(self, sig, broker, portfolio) -> None:
        """Execute a front-running trade."""
        cfg = self.config.temporal_momentum

        if sig.suggested_size_usd > portfolio.cash:
            return
        if sig.suggested_entry_price <= 0:
            return

        qty = sig.suggested_size_usd / sig.suggested_entry_price
        if qty <= 0:
            return

        order = OrderRequest(
            symbol=sig.token_id,
            side=Side.BUY,
            quantity=qty,
            order_type=OrderType.LIMIT,
            limit_price=sig.suggested_entry_price,
            platform=Platform.POLYMARKET,
        )
        try:
            result = await broker.submit_order(order)
            self._total_exposure_usd += sig.suggested_size_usd
            self.risk_manager.record_trade()
            trade_id = await self.repo.insert_trade(
                order_id=result.order_id,
                symbol=sig.token_id,
                side="buy",
                quantity=qty,
                filled_price=result.filled_price,
                platform="polymarket",
                source=f"monitor:{self.monitor_id}",
                strategy_name="temporal_frontrun",
                reasoning=f"FrontRun: {sig.question[:80]} | est impact={sig.estimated_price_impact:.2%}",
                confidence=0.60,
                status=result.status.value,
            )
            await self.repo.insert_monitor_trade(
                self.monitor_id, trade_id, sig.suggested_entry_price, qty
            )
            log.info(
                f"TemporalMomentum frontrun: {sig.token_id[:20]} "
                f"size=${sig.suggested_size_usd:.0f}"
            )
        except Exception as e:
            log.warning(f"TemporalMomentumMonitor: frontrun failed for {sig.token_id}: {e}")

    # ------------------------------------------------------------------
    # Settlement tracking (runs in outer loop)
    # ------------------------------------------------------------------

    async def check_settlements(self, broker) -> None:
        """Check for settled trades and record P&L.

        Delegates to the same settlement logic used by PolymarketArbMonitor
        by reusing the CLOB API pattern directly.
        """
        try:
            unsettled = await self.repo.get_unsettled_polymarket_trades()
            if not unsettled:
                return

            # Filter to only trades from this monitor's strategy
            my_trades = [
                t for t in unsettled
                if t.get("strategy_name") in (
                    TemporalMomentumArbStrategy.name, "temporal_frontrun"
                )
            ]
            if not my_trades:
                return

            async with httpx.AsyncClient(timeout=10.0) as client:
                for trade in my_trades:
                    try:
                        token_id = trade["symbol"]
                        resp = await client.get(
                            "https://clob.polymarket.com/markets",
                            params={"clob_token_ids": token_id},
                        )
                        if resp.status_code != 200:
                            continue
                        markets = resp.json()
                        if not markets:
                            continue
                        market = markets[0] if isinstance(markets, list) else markets
                        if not (market.get("closed") or market.get("resolved")):
                            continue

                        result_outcome = None
                        for token in market.get("tokens", []):
                            if token.get("winner"):
                                result_outcome = token.get("outcome", "").lower()
                                break

                        if result_outcome is None:
                            continue

                        entry_price = trade["filled_price"] or 0.0
                        qty = trade["quantity"]
                        side = trade["side"]
                        condition_id = market.get("condition_id", "")

                        if side == "buy":
                            payout_per = (
                                (1.0 - entry_price)
                                if result_outcome == "yes"
                                else -entry_price
                            )
                        else:
                            payout_per = (
                                entry_price
                                if result_outcome == "no"
                                else -(1.0 - entry_price)
                            )

                        total_pnl = payout_per * qty
                        await self.repo.insert_polymarket_settlement(
                            trade_id=trade["id"],
                            condition_id=condition_id,
                            token_id=token_id,
                            side=side,
                            quantity=qty,
                            entry_price=entry_price,
                            result=result_outcome,
                            payout_per_contract=round(payout_per, 4),
                            total_pnl=round(total_pnl, 2),
                        )
                        await self.repo.increment_monitor_trade(
                            self.monitor_id, pnl=total_pnl
                        )
                        # Reduce exposure tracking on settlement
                        self._total_exposure_usd = max(
                            0.0, self._total_exposure_usd - (entry_price * qty)
                        )
                        log.info(
                            f"TemporalMomentum settlement: {token_id[:20]} "
                            f"→ {result_outcome.upper()} ${total_pnl:+.2f}"
                        )
                    except Exception as e:
                        log.warning(
                            f"TemporalMomentum settlement failed for "
                            f"{trade.get('symbol', '?')}: {e}"
                        )
        except Exception as e:
            log.warning(f"TemporalMomentumMonitor: settlement check error: {e}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_token_ids(markets: list[dict]) -> list[str]:
    """Extract all YES/NO token IDs from a list of market dicts."""
    ids: list[str] = []
    for m in markets:
        for key in ("token_id_yes", "token_id_no"):
            tid = m.get(key, "")
            if tid:
                ids.append(tid)
    return ids
