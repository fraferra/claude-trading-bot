"""Monitor manager — lifecycle management for all monitors."""

from __future__ import annotations

import asyncio

from trading_bot.config import Config
from trading_bot.db.repository import Repository
from trading_bot.monitors.base import BaseMonitor, EventBus
from trading_bot.monitors.cross_market import CrossMarketMonitor
from trading_bot.monitors.crypto_momentum import CryptoMomentumMonitor
from trading_bot.monitors.kalshi_prediction import KalshiPredictionMonitor
from trading_bot.monitors.polymarket_arb import PolymarketArbMonitor
from trading_bot.monitors.polymarket_probability import PolymarketProbabilityMonitor
from trading_bot.monitors.research_agent import ResearchAgentMonitor
from trading_bot.monitors.stock_watchlist import StockWatchlistMonitor
from trading_bot.monitors.strategy_review import StrategyReviewMonitor
from trading_bot.utils.logging import log

MONITOR_TYPES: dict[str, type[BaseMonitor]] = {
    "stock_watchlist": StockWatchlistMonitor,
    "polymarket_arb": PolymarketArbMonitor,
    "polymarket_probability": PolymarketProbabilityMonitor,
    "cross_market": CrossMarketMonitor,
    "research_agent": ResearchAgentMonitor,
    "strategy_review": StrategyReviewMonitor,
    "kalshi_prediction": KalshiPredictionMonitor,
    "crypto_momentum": CryptoMomentumMonitor,
}


class MonitorManager:
    """Manages the lifecycle of all trading monitors."""

    def __init__(
        self,
        config: Config,
        repo: Repository,
        event_bus: EventBus,
        brokers: dict,
        risk_manager,
    ) -> None:
        self.config = config
        self.repo = repo
        self.event_bus = event_bus
        self.brokers = brokers
        self.risk_manager = risk_manager
        self._monitors: dict[str, BaseMonitor] = {}
        self._counter = 0

    async def restore_from_db(self) -> None:
        """On startup, restore previously-running monitors."""
        states = await self.repo.get_all_monitor_states()
        for state in states:
            if state["status"] == "running":
                try:
                    monitor = self._create_monitor(state["monitor_type"], state["monitor_id"])
                    if monitor:
                        self._monitors[state["monitor_id"]] = monitor
                        await monitor.start()
                        log.info(f"Restored monitor: {state['monitor_id']}")
                except Exception as e:
                    log.warning(f"Failed to restore monitor {state['monitor_id']}: {e}")

    def _create_monitor(self, monitor_type: str, monitor_id: str) -> BaseMonitor | None:
        cls = MONITOR_TYPES.get(monitor_type)
        if cls is None:
            return None
        return cls(
            monitor_id=monitor_id,
            config=self.config,
            repo=self.repo,
            event_bus=self.event_bus,
            brokers=self.brokers,
            risk_manager=self.risk_manager,
        )

    async def start_monitor(self, monitor_type: str) -> dict:
        """Start a new monitor of the given type. Returns its state."""
        if monitor_type not in MONITOR_TYPES:
            raise ValueError(f"Unknown monitor type: {monitor_type}. Available: {list(MONITOR_TYPES)}")

        self._counter += 1
        monitor_id = f"{monitor_type}_{self._counter}"

        monitor = self._create_monitor(monitor_type, monitor_id)
        if not monitor:
            raise ValueError(f"Failed to create monitor: {monitor_type}")

        await self.repo.upsert_monitor_state(monitor_id, monitor_type, "running")
        self._monitors[monitor_id] = monitor
        await monitor.start()

        state = await self.repo.get_monitor_state(monitor_id)
        return state or {"monitor_id": monitor_id, "status": "running"}

    async def stop_monitor(self, monitor_id: str) -> dict | None:
        monitor = self._monitors.get(monitor_id)
        if monitor:
            await monitor.stop()
            del self._monitors[monitor_id]
        return await self.repo.get_monitor_state(monitor_id)

    async def pause_monitor(self, monitor_id: str) -> dict | None:
        monitor = self._monitors.get(monitor_id)
        if monitor:
            await monitor.pause()
        return await self.repo.get_monitor_state(monitor_id)

    async def resume_monitor(self, monitor_id: str) -> dict | None:
        monitor = self._monitors.get(monitor_id)
        if monitor:
            await monitor.resume()
        return await self.repo.get_monitor_state(monitor_id)

    def list_monitors(self) -> list[dict]:
        return [
            {
                "monitor_id": m.monitor_id,
                "monitor_type": m.monitor_type,
                "status": m.status.value,
            }
            for m in self._monitors.values()
        ]

    async def shutdown(self) -> None:
        """Stop all monitors gracefully."""
        for monitor in list(self._monitors.values()):
            try:
                await monitor.stop()
            except Exception as e:
                log.warning(f"Error stopping monitor {monitor.monitor_id}: {e}")
        self._monitors.clear()
