from __future__ import annotations

import asyncio
from datetime import date, datetime
from functools import partial
from uuid import uuid4

import httpx
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
        self._daily_pnl: float = 0.0
        self._daily_pnl_date: date = date.today()
        log.info("Polymarket LIVE broker initialized")

    async def get_account(self) -> PortfolioSummary:
        """Get account balance and positions from Polymarket."""
        positions = await self.get_positions()
        total_value = sum(p.market_value for p in positions)
        cash = await self._get_usdc_balance()

        return PortfolioSummary(
            cash=cash,
            equity=total_value + cash,
            positions=positions,
            daily_pnl=self._get_daily_pnl(),
            platform=Platform.POLYMARKET,
        )

    async def _get_usdc_balance(self) -> float:
        """Fetch USDC.e balance from CLOB API."""
        try:
            loop = asyncio.get_running_loop()
            balance_data = await loop.run_in_executor(None, self.client.get_balance_allowance)
            if isinstance(balance_data, dict):
                # Returns asset balances; USDC/collateral is the cash balance
                raw = balance_data.get("balance", balance_data.get("collateral_balance", 0))
                return float(raw)
        except Exception as e:
            log.debug(f"Polymarket balance fetch failed: {e}")
        return 0.0

    def _get_daily_pnl(self) -> float:
        """Return today's running P&L, resetting the counter at midnight."""
        today = date.today()
        if today != self._daily_pnl_date:
            self._daily_pnl = 0.0
            self._daily_pnl_date = today
        return self._daily_pnl

    def record_settlement_pnl(self, pnl: float) -> None:
        """Called by settlement monitors to accumulate realized P&L for the daily loss check."""
        today = date.today()
        if today != self._daily_pnl_date:
            self._daily_pnl = 0.0
            self._daily_pnl_date = today
        self._daily_pnl += pnl

    async def get_positions(self) -> list[Position]:
        """Fetch open positions from Polymarket using the positions endpoint."""
        loop = asyncio.get_running_loop()

        try:
            # Try the dedicated positions endpoint first
            positions_data = await loop.run_in_executor(None, self.client.get_positions)
            if positions_data:
                return self._parse_positions(positions_data)
        except Exception:
            pass

        # Fallback: infer from filled orders
        try:
            orders = await loop.run_in_executor(None, self.client.get_orders)
        except Exception as e:
            log.error(f"Failed to fetch Polymarket positions: {e}")
            return []

        positions_map: dict[str, dict] = {}
        for order in orders:
            if order.get("status") != "MATCHED":
                continue
            asset_id = order.get("asset_id", "")
            if not asset_id:
                continue
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
                current_price=0.0,
                market_value=data["total_cost"] if data["quantity"] > 0 else 0,
                unrealized_pnl=0.0,
                platform=Platform.POLYMARKET,
            )
            for asset_id, data in positions_map.items()
            if data["quantity"] > 0.001
        ]

    def _parse_positions(self, positions_data: list[dict]) -> list[Position]:
        """Parse positions from the /positions endpoint response."""
        result = []
        for p in positions_data:
            size = float(p.get("size", p.get("quantity", 0)))
            if size <= 0:
                continue
            avg_price = float(p.get("average_price", p.get("avgPrice", 0)))
            token_id = p.get("asset", p.get("token_id", p.get("asset_id", "")))
            current = float(p.get("cur_price", p.get("price", avg_price)))

            result.append(Position(
                symbol=token_id,
                quantity=size,
                avg_entry_price=avg_price,
                current_price=current,
                market_value=size * current,
                unrealized_pnl=(current - avg_price) * size,
                platform=Platform.POLYMARKET,
            ))
        return result

    async def submit_order(self, order: OrderRequest) -> OrderResult:
        """Submit a limit order on Polymarket."""
        loop = asyncio.get_running_loop()

        token_id = order.symbol
        side_str = "BUY" if order.side == Side.BUY else "SELL"
        price = order.limit_price or 0.5

        log.info(f"Submitting Polymarket order: {side_str} {order.quantity:.4f} @ ${price:.4f}")

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
            # CLOB API returns orderID on success; no "success" field exists
            success = bool(signed_order.get("orderID"))
            status_str = signed_order.get("status", "").upper()
            if status_str in ("MATCHED", "FILLED"):
                status = OrderStatus.FILLED
            elif status_str in ("CANCELLED", "CANCELED"):
                status = OrderStatus.CANCELLED
            elif success:
                status = OrderStatus.PENDING
            else:
                status = OrderStatus.REJECTED

            log.info(f"Polymarket order {order_id}: status={status.value} raw={signed_order}")

            return OrderResult(
                order_id=order_id,
                symbol=token_id,
                side=order.side,
                quantity=order.quantity,
                status=status,
                filled_price=price if status in (OrderStatus.FILLED, OrderStatus.PENDING) else None,
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
        loop = asyncio.get_running_loop()
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
        loop = asyncio.get_running_loop()
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
        """Get the midpoint price for a token using CLOB midpoint endpoint."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{POLYMARKET_HOST}/midpoint",
                    params={"token_id": symbol},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    mid = data.get("mid")
                    if mid is not None:
                        return float(mid)
        except Exception:
            pass

        # Fallback to market data
        try:
            from trading_bot.analysis.market_data import get_polymarket_data
            market = await get_polymarket_data(symbol)
            return market.yes_price
        except Exception as e:
            log.debug(f"Polymarket quote fallback failed for {symbol}: {e}")
            return 0.0

    async def check_market_settled(self, token_id: str) -> tuple[bool, str | None]:
        """Check if a Polymarket market has resolved. Returns (is_settled, result)."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{POLYMARKET_HOST}/markets",
                    params={"clob_token_ids": token_id},
                )
                if resp.status_code != 200:
                    return False, None

                markets = resp.json()
                if not markets:
                    return False, None

                market = markets[0] if isinstance(markets, list) else markets
                is_resolved = market.get("closed", False) or market.get("resolved", False)
                if not is_resolved:
                    return False, None

                for token in market.get("tokens", []):
                    if token.get("token_id") == token_id and token.get("winner", False):
                        return True, token.get("outcome", "").lower()

                # If resolved but no winner token found, check all tokens
                for token in market.get("tokens", []):
                    if token.get("winner", False):
                        return True, token.get("outcome", "").lower()

        except Exception as e:
            log.debug(f"Polymarket settlement check failed for {token_id}: {e}")

        return False, None
