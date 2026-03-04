from __future__ import annotations

from abc import ABC, abstractmethod

from trading_bot.config import Config
from trading_bot.models import StrategyResult


class BaseStrategy(ABC):
    """Abstract base for all trading strategies."""

    name: str

    def __init__(self, config: Config) -> None:
        self.config = config

    @abstractmethod
    async def scan(self) -> StrategyResult:
        """Scan for opportunities. Returns a StrategyResult."""
        ...
