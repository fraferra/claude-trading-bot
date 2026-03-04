from __future__ import annotations

import asyncio
from datetime import datetime
from functools import partial

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, OrderType as AlpacaOrderType, TimeInForce
from alpaca.trading.requests import (
    LimitOrderRequest,
    MarketOrderRequest,
    StopOrderRequest,
)
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest

from trading_bot.brokers.base import BaseBroker
from trading_bot.config import AlpacaConfig
from trading_bot.models import (
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

_STATUS_MAP = {
    "new": OrderStatus.PENDING,
    "accepted": OrderStatus.PENDING,
    "pending_new": OrderStatus.PENDING,
    "partially_filled": OrderStatus.PARTIALLY_FILLED,
    "filled": OrderStatus.FILLED,
    "canceled": OrderStatus.CANCELLED,
    "expired": OrderStatus.CANCELLED,
    "rejected": OrderStatus.REJECTED,
    "pending_cancel": OrderStatus.PENDING,
    "pending_replace": OrderStatus.PENDING,
}


class AlpacaBroker(BaseBroker):
    platform = Platform.ALPACA

    def __init__(self, config: AlpacaConfig) -> None:
        self.config = config
        self.trading_client = TradingClient(
            api_key=config.api_key,
            secret_key=config.secret_key,
            paper=config.paper,
        )
        self.data_client = StockHistoricalDataClient(
            api_key=config.api_key,
            secret_key=config.secret_key,
        )
        mode = "PAPER" if config.paper else "LIVE"
        log.info(f"Alpaca broker initialized in {mode} mode")

    async def get_account(self) -> PortfolioSummary:
        loop = asyncio.get_event_loop()
        account = await loop.run_in_executor(None, self.trading_client.get_account)
        positions = await self.get_positions()

        return PortfolioSummary(
            cash=float(account.cash),
            equity=float(account.equity),
            positions=positions,
            daily_pnl=float(account.equity) - float(account.last_equity),
            platform=Platform.ALPACA,
        )

    async def get_positions(self) -> list[Position]:
        loop = asyncio.get_event_loop()
        raw_positions = await loop.run_in_executor(None, self.trading_client.get_all_positions)

        return [
            Position(
                symbol=p.symbol,
                quantity=float(p.qty),
                avg_entry_price=float(p.avg_entry_price),
                current_price=float(p.current_price),
                market_value=float(p.market_value),
                unrealized_pnl=float(p.unrealized_pl),
                platform=Platform.ALPACA,
            )
            for p in raw_positions
        ]

    async def submit_order(self, order: OrderRequest) -> OrderResult:
        loop = asyncio.get_event_loop()
        side = OrderSide.BUY if order.side == Side.BUY else OrderSide.SELL

        # Crypto uses GTC (24/7 market), stocks use DAY
        is_crypto = order.platform == Platform.ALPACA_CRYPTO
        tif = TimeInForce.GTC if is_crypto else TimeInForce.DAY

        if order.order_type == OrderType.MARKET:
            req = MarketOrderRequest(
                symbol=order.symbol,
                qty=order.quantity,
                side=side,
                time_in_force=tif,
            )
        elif order.order_type == OrderType.LIMIT:
            req = LimitOrderRequest(
                symbol=order.symbol,
                qty=order.quantity,
                side=side,
                time_in_force=tif,
                limit_price=order.limit_price,
            )
        elif order.order_type == OrderType.STOP:
            req = StopOrderRequest(
                symbol=order.symbol,
                qty=order.quantity,
                side=side,
                time_in_force=tif,
                stop_price=order.stop_price,
            )
        else:
            raise ValueError(f"Unsupported order type: {order.order_type}")

        log.info(f"Submitting Alpaca order: {side.value} {order.quantity} {order.symbol}")
        result = await loop.run_in_executor(
            None, partial(self.trading_client.submit_order, req)
        )

        # Poll briefly for fill (market orders usually fill within seconds)
        order_id = str(result.id)
        for _ in range(5):
            status = _STATUS_MAP.get(result.status.value, OrderStatus.PENDING)
            if status == OrderStatus.FILLED:
                break
            await asyncio.sleep(0.5)
            result = await loop.run_in_executor(
                None, partial(self.trading_client.get_order_by_id, order_id)
            )

        status = _STATUS_MAP.get(result.status.value, OrderStatus.PENDING)
        filled_price = float(result.filled_avg_price) if result.filled_avg_price else None
        filled_at = result.filled_at

        return OrderResult(
            order_id=order_id,
            symbol=result.symbol,
            side=order.side,
            quantity=float(result.qty),
            status=status,
            filled_price=filled_price,
            filled_at=filled_at,
            platform=Platform.ALPACA,
        )

    async def cancel_order(self, order_id: str) -> bool:
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                None, partial(self.trading_client.cancel_order_by_id, order_id)
            )
            log.info(f"Cancelled order {order_id}")
            return True
        except Exception as e:
            log.error(f"Failed to cancel order {order_id}: {e}")
            return False

    async def get_order_status(self, order_id: str) -> OrderStatus:
        loop = asyncio.get_event_loop()
        order = await loop.run_in_executor(
            None, partial(self.trading_client.get_order_by_id, order_id)
        )
        return _STATUS_MAP.get(order.status.value, OrderStatus.PENDING)

    async def get_quote(self, symbol: str) -> float:
        loop = asyncio.get_event_loop()
        req = StockLatestQuoteRequest(symbol_or_symbols=symbol)
        quotes = await loop.run_in_executor(
            None, partial(self.data_client.get_stock_latest_quote, req)
        )
        quote = quotes[symbol]
        # Use mid-point of bid/ask, fallback to ask
        if quote.bid_price and quote.ask_price:
            return (float(quote.bid_price) + float(quote.ask_price)) / 2
        return float(quote.ask_price or 0)

    async def get_crypto_quote(self, symbol: str) -> float:
        """Get latest quote for a crypto pair via Alpaca Crypto API."""
        from alpaca.data.historical import CryptoHistoricalDataClient
        from alpaca.data.requests import CryptoLatestQuoteRequest

        loop = asyncio.get_event_loop()
        crypto_client = CryptoHistoricalDataClient(
            api_key=self.config.api_key, secret_key=self.config.secret_key,
        )
        req = CryptoLatestQuoteRequest(symbol_or_symbols=symbol)
        quotes = await loop.run_in_executor(
            None, partial(crypto_client.get_crypto_latest_quote, req)
        )
        quote = quotes.get(symbol)
        if quote:
            bid = float(quote.bid_price) if quote.bid_price else 0.0
            ask = float(quote.ask_price) if quote.ask_price else 0.0
            if bid and ask:
                return (bid + ask) / 2
            return ask or bid
        return 0.0
