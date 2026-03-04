from __future__ import annotations

import asyncio
from datetime import datetime
from functools import partial
from uuid import uuid4

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType as ClobOrderType

from trading_bot.brokers.base import BaseBroker
from trading_bot.config import PolymarketConfig
from trading_bot.models import (
    OrderRequest,
    OrderResult,
    OrderStatus,
    Platform,
    PortfolioSummary,
    Position,
    Side,
)
from trading_bot.utils.logging import log

POLYMARKET_HOST = "https://clob.polymarket.com"
CHAIN_ID = 137  # Polygon mainnet


class PolymarketBroker(BaseBroker):
    """Live Polymarket broker using py-clob-client.

    WARNING: This executes real trades with real money on Polymarket.
    """

    platform = Platform.POLYMARKET

    def __init__(self, config: PolymarketConfig) -> None:
        self.config = config

        self.client = ClobClient(
            host=POLYMARKET_HOST,
            chain_id=CHAIN_ID,
            key=config.private_key,
            creds={
                "apiKey": config.api_key,
                "secret": config.api_secret,
                "passphrase": config.api_passphrase,
            },
        )
        log.info("Polymarket LIVE broker initialized")

    async def get_account(self) -> PortfolioSummary:
        """Get account balance and positions from Polymarket."""
        positions = await self.get_positions()
        # Polymarket doesn't have a single "account" endpoint — derive from positions
        total_value = sum(p.market_value for p in positions)

        return PortfolioSummary(
            cash=0.0,  # Would need to check on-chain USDC balance
            equity=total_value,
            positions=positions,
            daily_pnl=0.0,
            platform=Platform.POLYMARKET,
        )

    async def get_positions(self) -> list[Position]:
        """Fetch open positions from Polymarket."""
        loop = asyncio.get_event_loop()

        try:
            orders = await loop.run_in_executor(None, self.client.get_orders)
        except Exception as e:
            log.error(f"Failed to fetch Polymarket positions: {e}")
            return []

        # Aggregate filled orders into positions
        positions_map: dict[str, dict] = {}
        for order in orders:
            if order.get("status") != "MATCHED":
                continue
            asset_id = order.get("asset_id", "")
            if asset_id not in positions_map:
                positions_map[asset_id] = {"quantity": 0.0, "total_cost": 0.0}

            qty = float(order.get("original_size", 0))
            price = float(order.get("price", 0))
            side = order.get("side", "BUY")

            if side == "BUY":
                positions_map[asset_id]["quantity"] += qty
                positions_map[asset_id]["total_cost"] += qty * price
            else:
                positions_map[asset_id]["quantity"] -= qty
                positions_map[asset_id]["total_cost"] -= qty * price

        return [
            Position(
                symbol=asset_id,
                quantity=data["quantity"],
                avg_entry_price=data["total_cost"] / data["quantity"] if data["quantity"] > 0 else 0,
                current_price=0.0,  # Would need a separate price lookup
                market_value=data["quantity"] * (data["total_cost"] / data["quantity"]) if data["quantity"] > 0 else 0,
                unrealized_pnl=0.0,
                platform=Platform.POLYMARKET,
            )
            for asset_id, data in positions_map.items()
            if data["quantity"] > 0
        ]

    async def submit_order(self, order: OrderRequest) -> OrderResult:
        """Submit a limit order on Polymarket."""
        loop = asyncio.get_event_loop()

        # Polymarket uses token IDs, not condition IDs for orders
        # The caller needs to provide the correct token_id as the symbol
        token_id = order.symbol
        side_str = "BUY" if order.side == Side.BUY else "SELL"
        price = order.limit_price or 0.5  # Default to 0.5 if no price set

        log.info(f"Submitting Polymarket order: {side_str} {order.quantity} @ ${price}")

        try:
            order_args = OrderArgs(
                price=price,
                size=order.quantity,
                side=side_str,
                token_id=token_id,
            )
            signed_order = await loop.run_in_executor(
                None, partial(self.client.create_and_post_order, order_args)
            )

            order_id = signed_order.get("orderID", str(uuid4()))
            status = OrderStatus.PENDING if signed_order.get("success") else OrderStatus.REJECTED

            return OrderResult(
                order_id=order_id,
                symbol=token_id,
                side=order.side,
                quantity=order.quantity,
                status=status,
                filled_price=price if status == OrderStatus.FILLED else None,
                filled_at=datetime.now() if status == OrderStatus.FILLED else None,
                platform=Platform.POLYMARKET,
            )
        except Exception as e:
            log.error(f"Polymarket order failed: {e}")
            return OrderResult(
                order_id=str(uuid4()),
                symbol=token_id,
                side=order.side,
                quantity=order.quantity,
                status=OrderStatus.REJECTED,
                platform=Platform.POLYMARKET,
            )

    async def cancel_order(self, order_id: str) -> bool:
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                None, partial(self.client.cancel, order_id)
            )
            log.info(f"Cancelled Polymarket order {order_id}")
            return True
        except Exception as e:
            log.error(f"Failed to cancel Polymarket order {order_id}: {e}")
            return False

    async def get_order_status(self, order_id: str) -> OrderStatus:
        loop = asyncio.get_event_loop()
        try:
            order = await loop.run_in_executor(
                None, partial(self.client.get_order, order_id)
            )
            status_str = order.get("status", "").upper()
            if status_str == "MATCHED":
                return OrderStatus.FILLED
            elif status_str == "CANCELLED":
                return OrderStatus.CANCELLED
            return OrderStatus.PENDING
        except Exception:
            return OrderStatus.REJECTED

    async def get_quote(self, symbol: str) -> float:
        from trading_bot.analysis.market_data import get_polymarket_data

        market = await get_polymarket_data(symbol)
        return market.yes_price
