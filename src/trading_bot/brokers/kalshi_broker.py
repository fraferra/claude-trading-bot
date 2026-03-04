"""Kalshi prediction market broker using kalshi-python SDK."""

from __future__ import annotations

import asyncio
from functools import partial

from trading_bot.brokers.base import BaseBroker
from trading_bot.config import KalshiConfig
from trading_bot.models import (
    KalshiEventData,
    KalshiMarketData,
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderType,
    Platform,
    PortfolioSummary,
    Position,
    Side,
)
from trading_bot.utils.logging import log

_DEMO_HOST = "https://demo-api.kalshi.co/trade-api/v2"
_PROD_HOST = "https://api.elections.kalshi.com/trade-api/v2"

_STATUS_MAP = {
    "resting": OrderStatus.PENDING,
    "pending": OrderStatus.PENDING,
    "executed": OrderStatus.FILLED,
    "canceled": OrderStatus.CANCELLED,
    "expired": OrderStatus.CANCELLED,
}


class KalshiBroker(BaseBroker):
    """Kalshi prediction market broker.

    Prices are stored internally in decimal (0.01-0.99).
    Conversion to/from cents (1-99) happens at the broker boundary.
    """

    platform = Platform.KALSHI

    def __init__(self, config: KalshiConfig) -> None:
        self.config = config
        self._client = self._build_client(config)
        mode = "DEMO" if config.demo else "LIVE"
        log.info(f"Kalshi broker initialized in {mode} mode")

    @staticmethod
    def _build_client(config: KalshiConfig):
        from kalshi_python import Configuration, KalshiClient

        host = _DEMO_HOST if config.demo else _PROD_HOST
        cfg = Configuration(host=host)

        if config.api_key_id and config.private_key:
            # Handle escaped newlines from env vars (e.g. literal \n → actual newlines)
            key_content = config.private_key.replace("\\n", "\n")
            # SDK reads api_key_id + private_key_pem from Configuration in __init__
            cfg.api_key_id = config.api_key_id
            cfg.private_key_pem = key_content
            log.info(f"Kalshi auth configured: key_id={config.api_key_id[:8]}...")

        client = KalshiClient(configuration=cfg)
        return client

    # --- Price conversion helpers ---

    @staticmethod
    def cents_to_decimal(cents: int) -> float:
        """Convert Kalshi cents (1-99) to decimal (0.01-0.99)."""
        return cents / 100.0

    @staticmethod
    def decimal_to_cents(dec: float) -> int:
        """Convert decimal (0.01-0.99) to Kalshi cents (1-99)."""
        return max(1, min(99, round(dec * 100)))

    # --- BaseBroker implementation ---

    async def get_account(self) -> PortfolioSummary:
        loop = asyncio.get_event_loop()
        balance_resp = await loop.run_in_executor(
            None, self._client._portfolio_api.get_balance
        )
        balance_cents = balance_resp.balance if balance_resp.balance else 0
        balance_usd = balance_cents / 100.0

        positions = await self.get_positions()
        equity = balance_usd + sum(p.market_value for p in positions)

        return PortfolioSummary(
            cash=balance_usd,
            equity=equity,
            positions=positions,
            daily_pnl=0.0,
            platform=Platform.KALSHI,
        )

    async def get_positions(self) -> list[Position]:
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(
            None, partial(self._client._portfolio_api.get_positions, limit=200)
        )
        positions = []
        market_positions = resp.positions if resp.positions else []
        for p in market_positions:
            qty = p.position if p.position else 0
            if qty == 0:
                continue
            # Get current price
            try:
                price = await self.get_quote(p.ticker)
            except Exception:
                price = 0.0
            cost_cents = p.total_cost if p.total_cost else 0
            positions.append(Position(
                symbol=p.ticker,
                quantity=float(abs(qty)),
                avg_entry_price=abs(cost_cents / qty / 100.0) if qty != 0 else 0.0,
                current_price=price,
                market_value=abs(qty) * price,
                unrealized_pnl=(abs(qty) * price) - abs(cost_cents / 100.0) if qty > 0 else 0.0,
                platform=Platform.KALSHI,
            ))
        return positions

    async def submit_order(self, order: OrderRequest) -> OrderResult:
        """Submit a limit order to Kalshi.

        Kalshi only supports limit orders. Prices must be in cents.
        """
        loop = asyncio.get_event_loop()

        # Determine Kalshi-native side and action
        if order.side == Side.BUY:
            kalshi_side = "yes"
            kalshi_action = "buy"
        else:
            kalshi_side = "yes"
            kalshi_action = "sell"

        limit_price_cents = self.decimal_to_cents(order.limit_price or 0.50)
        count = max(1, int(order.quantity))

        log.info(
            f"Submitting Kalshi order: {kalshi_action} {count} {order.symbol} "
            f"YES @ {limit_price_cents}c"
        )

        try:
            from kalshi_python.models import CreateOrderRequest as KalshiOrderRequest
            order_req = KalshiOrderRequest(
                ticker=order.symbol,
                side=kalshi_side,
                action=kalshi_action,
                count=count,
                type="limit",
                yes_price=limit_price_cents,
            )
            resp = await loop.run_in_executor(
                None,
                partial(
                    self._client._portfolio_api.create_order,
                    create_order_request=order_req,
                ),
            )
            result_order = resp.order
            status = _STATUS_MAP.get(
                result_order.status if result_order.status else "pending",
                OrderStatus.PENDING,
            )

            filled_price = None
            if status == OrderStatus.FILLED and result_order.yes_price:
                filled_price = self.cents_to_decimal(result_order.yes_price)

            return OrderResult(
                order_id=result_order.order_id or "",
                symbol=order.symbol,
                side=order.side,
                quantity=float(count),
                status=status,
                filled_price=filled_price,
                platform=Platform.KALSHI,
            )

        except Exception as e:
            log.error(f"Kalshi order failed: {e}")
            return OrderResult(
                order_id="",
                symbol=order.symbol,
                side=order.side,
                quantity=float(count),
                status=OrderStatus.REJECTED,
                platform=Platform.KALSHI,
            )

    async def cancel_order(self, order_id: str) -> bool:
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                None, partial(self._client._portfolio_api.cancel_order, order_id)
            )
            log.info(f"Cancelled Kalshi order {order_id}")
            return True
        except Exception as e:
            log.error(f"Failed to cancel Kalshi order {order_id}: {e}")
            return False

    async def get_order_status(self, order_id: str) -> OrderStatus:
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(
            None, partial(self._client._portfolio_api.get_order, order_id)
        )
        order = resp.order
        return _STATUS_MAP.get(
            order.status if order.status else "pending",
            OrderStatus.PENDING,
        )

    async def get_quote(self, symbol: str) -> float:
        """Get current YES mid-price for a market ticker, in decimal."""
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(
            None, partial(self._client._markets_api.get_market, symbol)
        )
        market = resp.market
        yes_bid = market.yes_bid if market.yes_bid else 0
        yes_ask = market.yes_ask if market.yes_ask else 0
        if yes_bid and yes_ask:
            return self.cents_to_decimal((yes_bid + yes_ask) // 2)
        if market.last_price:
            return self.cents_to_decimal(market.last_price)
        return 0.50

    # --- Kalshi-specific methods ---

    async def get_events(
        self, category: str = "", limit: int = 100
    ) -> list[KalshiEventData]:
        """Fetch events from Kalshi, optionally filtered by category."""
        loop = asyncio.get_event_loop()

        kwargs: dict = {"limit": limit, "status": "open"}
        if category:
            kwargs["series_ticker"] = category

        resp = await loop.run_in_executor(
            None, partial(self._client._events_api.get_events, **kwargs)
        )

        events = []
        for e in (resp.events or []):
            markets = []
            if hasattr(e, "markets") and e.markets:
                for m in e.markets:
                    markets.append(self._parse_market(m))

            events.append(KalshiEventData(
                event_ticker=e.event_ticker or "",
                title=e.title or "",
                category=getattr(e, "series_ticker", "") or "",
                markets=markets,
            ))
        return events

    async def get_markets_for_event(self, event_ticker: str) -> list[KalshiMarketData]:
        """Get all markets for a specific event."""
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(
            None,
            partial(
                self._client._markets_api.get_markets,
                event_ticker=event_ticker,
                limit=100,
            ),
        )
        return [self._parse_market(m) for m in (resp.markets or [])]

    async def get_market(self, ticker: str) -> KalshiMarketData:
        """Get data for a single market."""
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(
            None, partial(self._client._markets_api.get_market, ticker)
        )
        return self._parse_market(resp.market)

    def _parse_market(self, m) -> KalshiMarketData:
        """Parse a Kalshi Market object into our KalshiMarketData model."""
        yes_bid = m.yes_bid if m.yes_bid else 0
        yes_ask = m.yes_ask if m.yes_ask else 0
        no_bid = m.no_bid if m.no_bid else 0
        no_ask = m.no_ask if m.no_ask else 0

        yes_price = self.cents_to_decimal((yes_bid + yes_ask) // 2) if (yes_bid and yes_ask) else 0.50
        no_price = self.cents_to_decimal((no_bid + no_ask) // 2) if (no_bid and no_ask) else 0.50

        return KalshiMarketData(
            ticker=m.ticker or "",
            event_ticker=m.event_ticker or "",
            title=m.title or "",
            subtitle=m.subtitle or "",
            yes_price=yes_price,
            no_price=no_price,
            volume=m.volume or 0,
            open_interest=0,
            open_time=str(m.open_time or ""),
            close_time=str(m.close_time or ""),
            result=m.result or "",
            category="",
            status=m.status or "",
        )
