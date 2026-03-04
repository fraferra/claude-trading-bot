"""Base class for all autonomous monitors."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

from trading_bot.db.repository import Repository
from trading_bot.models import MonitorStatus, WSEvent, WSEventType
from trading_bot.utils.logging import log


class EventBus:
    """Simple in-process event broadcast to WebSocket clients."""

    async def broadcast(self, event: WSEvent) -> None:
        """Override in WebSocketManager to push to connected clients."""
        pass


class BaseMonitor(ABC):
    """Abstract base for autonomous trading monitors."""

    monitor_type: str

    def __init__(
        self,
        monitor_id: str,
        config,
        repo: Repository,
        event_bus: EventBus,
        brokers: dict,
        risk_manager,
    ) -> None:
        self.monitor_id = monitor_id
        self.config = config
        self.repo = repo
        self.event_bus = event_bus
        self.brokers = brokers
        self.risk_manager = risk_manager
        self.status = MonitorStatus.STOPPED
        self._task: asyncio.Task | None = None
        self._paused = asyncio.Event()
        self._paused.set()

    @abstractmethod
    async def run_cycle(self) -> None:
        """Execute one monitoring cycle."""
        ...

    @abstractmethod
    def get_interval_seconds(self) -> int:
        """Return seconds between cycles."""
        ...

    async def start(self) -> None:
        self.status = MonitorStatus.RUNNING
        self._paused.set()
        self._task = asyncio.create_task(self._run_loop())
        await self.repo.update_monitor_status(self.monitor_id, "running")
        await self._broadcast_status()
        log.info(f"Monitor {self.monitor_id} started")

    async def stop(self) -> None:
        self.status = MonitorStatus.STOPPED
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self.repo.update_monitor_status(self.monitor_id, "stopped")
        await self._broadcast_status()
        log.info(f"Monitor {self.monitor_id} stopped")

    async def pause(self) -> None:
        self.status = MonitorStatus.PAUSED
        self._paused.clear()
        await self.repo.update_monitor_status(self.monitor_id, "paused")
        await self._broadcast_status()

    async def resume(self) -> None:
        self.status = MonitorStatus.RUNNING
        self._paused.set()
        await self.repo.update_monitor_status(self.monitor_id, "running")
        await self._broadcast_status()

    async def _run_loop(self) -> None:
        while True:
            await self._paused.wait()
            try:
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
                log.error(f"Monitor {self.monitor_id} error: {e}")
            await asyncio.sleep(self.get_interval_seconds())

    async def _broadcast_status(self) -> None:
        await self.event_bus.broadcast(WSEvent(
            type=WSEventType.MONITOR_STATUS,
            data={
                "monitor_id": self.monitor_id,
                "monitor_type": self.monitor_type,
                "status": self.status.value,
            },
        ))
