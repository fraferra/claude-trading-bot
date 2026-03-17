"""Regime classifier monitor.

Runs every N minutes (default 60), fetches daily bars for each crypto symbol,
fits the OU-based regime classifier, and writes results to the module-level
cache in `analysis.regime_classifier`.  The crypto momentum strategy then reads
the cache synchronously during its scan cycle — no extra I/O needed there.

A REGIME_UPDATE WebSocket event is broadcast whenever any symbol's regime
changes from the previous classification.
"""

from __future__ import annotations

from trading_bot.analysis.crypto_data import get_crypto_bars
from trading_bot.analysis.regime_classifier import (
    RegimeState,
    classify_regime_for_symbol,
    get_regime,
)
from trading_bot.models import WSEvent, WSEventType
from trading_bot.monitors.base import BaseMonitor
from trading_bot.utils.logging import log


class RegimeClassifierMonitor(BaseMonitor):
    """Periodically re-classifies the market regime for all crypto symbols.

    Uses 1-day bars with a 200-bar lookback (~6.5 months of crypto history)
    to estimate:
      - Lag-1 return autocorrelation  →  trending / mean-reverting
      - OU mean-reversion speed κ
      - Rolling realized-vol percentile  →  high / low volatility
    """

    monitor_type = "regime_classifier"

    def get_interval_seconds(self) -> int:
        return self.config.regime.scan_interval_minutes * 60

    async def run_cycle(self) -> None:
        cfg = self.config.regime
        crypto_cfg = self.config.crypto
        symbols: list[str] = cfg.symbols or crypto_cfg.watchlist

        log.info(f"[regime] Classifying {len(symbols)} symbols …")

        for symbol in symbols:
            try:
                await self._classify_symbol(symbol, cfg)
            except Exception as e:
                log.warning(f"[regime] Failed for {symbol}: {e}")

    async def _classify_symbol(self, symbol: str, cfg) -> None:
        bars = await get_crypto_bars(
            api_key=self.config.alpaca.api_key,
            secret_key=self.config.alpaca.secret_key,
            symbol=symbol,
            timeframe="1Day",
            limit=cfg.lookback_bars,
        )

        if len(bars) < 70:
            log.debug(f"[regime] Not enough daily bars for {symbol}: {len(bars)}")
            return

        prices = [b.close for b in bars]
        previous: RegimeState | None = get_regime(symbol)

        state = classify_regime_for_symbol(
            symbol,
            prices,
            autocorr_window=cfg.autocorr_window,
            vol_window=cfg.vol_window,
            bars_per_year=365.0,          # crypto trades 24/7 all year
            trend_threshold=cfg.trend_threshold,
            vol_high_pct=cfg.vol_high_pct,
            vol_low_pct=cfg.vol_low_pct,
        )

        if state is None:
            return

        # Broadcast only when regime changes
        if previous is None or previous.regime != state.regime:
            await self.event_bus.broadcast(WSEvent(
                type=WSEventType.REGIME_UPDATE,
                data={
                    "symbol": symbol,
                    "regime": state.regime.value,
                    "previous_regime": previous.regime.value if previous else None,
                    "autocorr": state.autocorr,
                    "kappa": state.kappa,
                    "vol_annualized": state.vol_annualized,
                    "vol_percentile": state.vol_percentile,
                    "trend_slope": state.trend_slope,
                    "confidence": state.confidence,
                },
            ))
            log.info(
                f"[regime] {symbol} regime changed: "
                f"{previous.regime.value if previous else 'none'} → {state.regime.value}"
            )
