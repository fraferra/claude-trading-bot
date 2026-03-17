"""Crypto momentum/mean-reversion strategy with optional LLM confirmation."""

from __future__ import annotations

import json

from trading_bot.agents.crypto_prompts import CRYPTO_CONFIRMATION_SYSTEM, CRYPTO_CONFIRMATION_USER
from trading_bot.analysis.crypto_data import compute_crypto_technicals, get_crypto_bars
from trading_bot.analysis.llm_analyst import LLMAnalyst
from trading_bot.analysis.regime_classifier import REGIME_PARAMS, get_regime
from trading_bot.config import Config
from trading_bot.models import (
    Action,
    CryptoTradeDecision,
    MarketRegime,
    OrderType,
    PortfolioSummary,
    StrategyResult,
    TradeDecision,
)
from trading_bot.strategies import BaseStrategy
from trading_bot.utils.logging import log


class CryptoMomentumStrategy(BaseStrategy):
    """Technical indicator-based crypto trading strategy with optional LLM confirmation.

    Computes RSI, MACD, and Bollinger Bands on 15-minute bars, generates
    momentum and mean-reversion scores, then optionally uses LLM for confirmation.
    """

    name = "crypto_momentum"

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self.crypto_cfg = config.crypto
        self.analyst = LLMAnalyst(config)

    async def scan(
        self,
        symbols: list[str] | None = None,
        portfolio: PortfolioSummary | None = None,
    ) -> StrategyResult:
        """Scan crypto watchlist for momentum/mean-reversion signals."""
        symbols = symbols or self.crypto_cfg.watchlist
        decisions: list[TradeDecision] = []
        crypto_decisions: list[CryptoTradeDecision] = []
        all_scanned: list[dict] = []  # All symbols including filtered ones

        for symbol in symbols:
            try:
                decision = await self._analyze_symbol(symbol, portfolio)
                if decision and decision.action != Action.HOLD:
                    crypto_decisions.append(decision)
                    # Convert to TradeDecision for unified interface
                    decisions.append(TradeDecision(
                        action=decision.action,
                        symbol=decision.symbol,
                        confidence=decision.confidence,
                        reasoning=decision.llm_reasoning or (
                            f"Signal: {decision.technical_signals.composite_signal:+.4f}, "
                            f"RSI: {decision.technical_signals.rsi_14}, "
                            f"MACD_H: {decision.technical_signals.macd_histogram}"
                        ),
                        suggested_size_usd=decision.suggested_size_usd,
                    ))
                elif decision and decision.action == Action.HOLD:
                    # LLM vetoed or action changed to hold
                    all_scanned.append({
                        "symbol": symbol,
                        "technical_signals": decision.technical_signals.model_dump(mode="json"),
                        "filtered_reason": "llm_vetoed" if decision.llm_override else "hold_signal",
                        "llm_reasoning": decision.llm_reasoning or "",
                    })
                else:
                    # Signal too weak or not enough data — include basic info
                    all_scanned.append({
                        "symbol": symbol,
                        "technical_signals": {},
                        "filtered_reason": "weak_signal_or_insufficient_data",
                    })
            except Exception as e:
                log.warning(f"Crypto scan failed for {symbol}: {e}")

        return StrategyResult(
            strategy_name=self.name,
            decisions=decisions,
            metadata={
                "symbols_scanned": len(symbols),
                "signals_found": len(crypto_decisions),
                "crypto_decisions": [d.model_dump(mode="json") for d in crypto_decisions],
                "all_scanned": all_scanned,
            },
        )

    async def _analyze_symbol(
        self, symbol: str, portfolio: PortfolioSummary | None
    ) -> CryptoTradeDecision | None:
        """Analyze a single crypto pair: compute signals, optionally confirm with LLM."""
        # Fetch bars
        bars = await get_crypto_bars(
            api_key=self.config.alpaca.api_key,
            secret_key=self.config.alpaca.secret_key,
            symbol=symbol,
            timeframe=self.crypto_cfg.bar_timeframe,
            limit=self.crypto_cfg.lookback_bars,
        )

        if len(bars) < 30:
            log.debug(f"Not enough bars for {symbol}: {len(bars)}")
            return None

        # --- Regime gating ---
        regime_state = get_regime(symbol)
        if regime_state is not None:
            rp = REGIME_PARAMS[regime_state.regime]
            mom_w = rp["momentum_weight"]
            mr_w = rp["mean_rev_weight"]
            min_score = self.crypto_cfg.min_signal_score * rp["min_signal_multiplier"]
            size_multiplier = rp["position_size_multiplier"]
            log.debug(
                f"[regime] {symbol}: {regime_state.regime.value} | "
                f"min_score={min_score:.3f} size_mult={size_multiplier:.2f}"
            )
        else:
            mom_w, mr_w = 0.5, 0.5
            min_score = self.crypto_cfg.min_signal_score
            size_multiplier = 1.0

        # Compute technical indicators
        signals = compute_crypto_technicals(bars, self.crypto_cfg)

        # Re-weight composite signal based on regime
        if regime_state is not None:
            regime_composite = max(
                -1.0,
                min(1.0, mom_w * signals.momentum_score + mr_w * signals.mean_reversion_score),
            )
            # Patch the composite_signal on the signals object so LLM sees the adjusted value
            signals.composite_signal = round(regime_composite, 4)
            if regime_composite >= min_score:
                signals.signal_direction = Action.BUY
            elif regime_composite <= -min_score:
                signals.signal_direction = Action.SELL
            else:
                signals.signal_direction = Action.HOLD

        # Check if signal is strong enough
        if abs(signals.composite_signal) < min_score:
            return None

        # Base decision from technicals
        confidence = min(0.95, abs(signals.composite_signal))
        size_usd = self._calculate_position_size(
            confidence, portfolio, signals.current_price, size_multiplier
        )

        # Compute limit price with slight offset for better fills
        if signals.signal_direction == Action.BUY:
            limit_price = round(signals.current_price * 0.999, 2)  # 0.1% below
        elif signals.signal_direction == Action.SELL:
            limit_price = round(signals.current_price * 1.001, 2)  # 0.1% above
        else:
            limit_price = signals.current_price

        regime_label = regime_state.regime.value if regime_state else MarketRegime.LOW_VOLATILITY.value
        decision = CryptoTradeDecision(
            symbol=symbol,
            action=signals.signal_direction,
            confidence=confidence,
            technical_signals=signals,
            suggested_size_usd=size_usd,
            order_type=OrderType.LIMIT,
            limit_price=limit_price,
            llm_reasoning=f"[regime:{regime_label}]",
        )

        # Optional LLM confirmation
        if self.crypto_cfg.llm_confirmation_enabled:
            decision = await self._llm_confirm(decision, bars, portfolio)

        return decision

    async def _llm_confirm(
        self,
        decision: CryptoTradeDecision,
        bars,
        portfolio: PortfolioSummary | None,
    ) -> CryptoTradeDecision:
        """Ask LLM to confirm or override the technical signal."""
        signals = decision.technical_signals

        # Build recent bars summary
        recent_bars = "\n".join(
            f"  {b.timestamp.strftime('%H:%M')}: O=${b.open:,.2f} H=${b.high:,.2f} "
            f"L=${b.low:,.2f} C=${b.close:,.2f} V={b.volume:,.0f}"
            for b in bars[-5:]
        )

        # Crypto exposure info
        crypto_exposure = "None"
        if portfolio:
            crypto_positions = [
                p for p in portfolio.positions
                if "/" in p.symbol  # Simple heuristic for crypto
            ]
            if crypto_positions:
                total = sum(p.market_value for p in crypto_positions)
                crypto_exposure = f"${total:,.2f} across {len(crypto_positions)} positions"

        user_msg = CRYPTO_CONFIRMATION_USER.format(
            symbol=decision.symbol,
            signal_direction=signals.signal_direction.value,
            composite_signal=signals.composite_signal,
            current_price=signals.current_price,
            rsi_14=f"{signals.rsi_14:.1f}" if signals.rsi_14 else "N/A",
            macd=f"{signals.macd:.6f}" if signals.macd else "N/A",
            macd_signal=f"{signals.macd_signal:.6f}" if signals.macd_signal else "N/A",
            macd_histogram=f"{signals.macd_histogram:.6f}" if signals.macd_histogram else "N/A",
            bb_upper=f"{signals.bb_upper:,.2f}" if signals.bb_upper else "N/A",
            bb_middle=f"{signals.bb_middle:,.2f}" if signals.bb_middle else "N/A",
            bb_lower=f"{signals.bb_lower:,.2f}" if signals.bb_lower else "N/A",
            bb_pct_b=f"{signals.bb_pct_b:.4f}" if signals.bb_pct_b is not None else "N/A",
            momentum_score=signals.momentum_score,
            mean_reversion_score=signals.mean_reversion_score,
            recent_bars=recent_bars,
            crypto_exposure=crypto_exposure,
        )

        try:
            raw = await self.analyst._call_llm_raw(CRYPTO_CONFIRMATION_SYSTEM, user_msg)

            # Parse response
            json_str = raw.strip()
            if json_str.startswith("```"):
                lines = json_str.split("\n")
                end = -1 if lines[-1].strip() == "```" else len(lines)
                json_str = "\n".join(lines[1:end])

            data = json.loads(json_str)
            confirmed = data.get("confirm", True)
            reasoning = data.get("reasoning", "")

            if not confirmed:
                override = data.get("override_action", "hold")
                if override == "hold":
                    decision.action = Action.HOLD
                elif override == "buy":
                    decision.action = Action.BUY
                elif override == "sell":
                    decision.action = Action.SELL
                decision.llm_override = True

            decision.confidence = float(data.get("confidence_adjustment", decision.confidence))
            decision.llm_reasoning = reasoning

        except Exception as e:
            log.warning(f"Crypto LLM confirmation failed for {decision.symbol}: {e}")
            decision.llm_reasoning = f"LLM confirmation unavailable: {e}"

        return decision

    def _calculate_position_size(
        self,
        confidence: float,
        portfolio: PortfolioSummary | None,
        current_price: float,
        regime_size_multiplier: float = 1.0,
    ) -> float:
        """Crypto-specific position sizing, optionally scaled by regime."""
        if portfolio is None or portfolio.equity <= 0:
            return 0.0

        base_pct = self.crypto_cfg.max_position_pct * confidence
        raw_size = portfolio.equity * base_pct * regime_size_multiplier

        return min(raw_size, self.crypto_cfg.max_size_usd * regime_size_multiplier)
