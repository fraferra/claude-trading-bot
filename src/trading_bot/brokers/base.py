from __future__ import annotations

from abc import ABC, abstractmethod

from trading_bot.models import OrderRequest, OrderResult, OrderStatus, Platform, PortfolioSummary, Position


class BaseBroker(ABC):
    """Abstract base class for all broker implementations."""

    platform: Platform

    @abstractmethod
    async def get_account(self) -> PortfolioSummary:
        """Get account summary including cash, equity, and positions."""
        ...

    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """Get all open positions."""
        ...

    @abstractmethod
    async def submit_order(self, order: OrderRequest) -> OrderResult:
        """Submit a new order. Returns the order result."""
        ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order. Returns True if successful."""
        ...

    @abstractmethod
    async def get_order_status(self, order_id: str) -> OrderStatus:
        """Get the current status of an order."""
        ...

    @abstractmethod
    async def get_quote(self, symbol: str) -> float:
        """Get the current price for a symbol."""
        ...
