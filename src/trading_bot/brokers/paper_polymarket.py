from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from trading_bot.brokers.base import BaseBroker
from trading_bot.analysis.market_data import get_polymarket_data
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

STATE_FILE = Path("paper_positions.json")


class PaperPolymarketBroker(BaseBroker):
    """Local paper trading simulator for Polymarket.

    Uses real Polymarket prices but tracks virtual positions in a JSON file.
    """

    platform = Platform.POLYMARKET

    def __init__(self, initial_balance: float = 10_000.0) -> None:
        self._initial_balance = initial_balance
        self._state = self._load_state()
        log.info(f"Paper Polymarket broker initialized with ${self._state['cash']:,.2f} balance")

    def _load_state(self) -> dict:
        if STATE_FILE.exists():
            with open(STATE_FILE) as f:
                return json.load(f)
        return {
            "cash": self._initial_balance,
            "positions": {},  # condition_id -> {quantity, avg_entry_price, side}
            "orders": [],     # Order history
        }

    def _save_state(self) -> None:
        with open(STATE_FILE, "w") as f:
            json.dump(self._state, f, indent=2, default=str)

    async def get_account(self) -> PortfolioSummary:
        positions = await self.get_positions()
        total_value = self._state["cash"] + sum(p.market_value for p in positions)

        return PortfolioSummary(
            cash=self._state["cash"],
            equity=total_value,
            positions=positions,
            daily_pnl=total_value - self._initial_balance,
            platform=Platform.POLYMARKET,
        )

    async def get_positions(self) -> list[Position]:
        positions: list[Position] = []
        for cid, pos_data in self._state["positions"].items():
            if pos_data["quantity"] <= 0:
                continue

            try:
                market = await get_polymarket_data(cid)
                current_price = market.yes_price if pos_data["side"] == "buy" else market.no_price
            except Exception:
                current_price = pos_data["avg_entry_price"]

            qty = pos_data["quantity"]
            avg_entry = pos_data["avg_entry_price"]

            positions.append(
                Position(
                    symbol=cid,
                    quantity=qty,
                    avg_entry_price=avg_entry,
                    current_price=current_price,
                    market_value=qty * current_price,
                    unrealized_pnl=qty * (current_price - avg_entry),
                    platform=Platform.POLYMARKET,
                )
            )
        return positions

    async def submit_order(self, order: OrderRequest) -> OrderResult:
        cid = order.symbol
        side_str = order.side.value

        # Get current market price
        try:
            market = await get_polymarket_data(cid)
            fill_price = market.yes_price if order.side == Side.BUY else market.no_price
        except Exception as e:
            log.error(f"Cannot get market price for {cid}: {e}")
            return OrderResult(
                order_id=str(uuid4()),
                symbol=cid,
                side=order.side,
                quantity=order.quantity,
                status=OrderStatus.REJECTED,
                platform=Platform.POLYMARKET,
            )

        cost = order.quantity * fill_price

        # Check if we have enough cash for buys
        if order.side == Side.BUY:
            if cost > self._state["cash"]:
                log.warning(f"Insufficient funds: need ${cost:.2f}, have ${self._state['cash']:.2f}")
                return OrderResult(
                    order_id=str(uuid4()),
                    symbol=cid,
                    side=order.side,
                    quantity=order.quantity,
                    status=OrderStatus.REJECTED,
                    platform=Platform.POLYMARKET,
                )

            self._state["cash"] -= cost

            # Update position
            if cid in self._state["positions"]:
                existing = self._state["positions"][cid]
                old_qty = existing["quantity"]
                old_avg = existing["avg_entry_price"]
                new_qty = old_qty + order.quantity
                new_avg = (old_qty * old_avg + order.quantity * fill_price) / new_qty
                existing["quantity"] = new_qty
                existing["avg_entry_price"] = new_avg
            else:
                self._state["positions"][cid] = {
                    "quantity": order.quantity,
                    "avg_entry_price": fill_price,
                    "side": side_str,
                }

        elif order.side == Side.SELL:
            if cid not in self._state["positions"] or self._state["positions"][cid]["quantity"] < order.quantity:
                log.warning(f"Insufficient position to sell {order.quantity} of {cid}")
                return OrderResult(
                    order_id=str(uuid4()),
                    symbol=cid,
                    side=order.side,
                    quantity=order.quantity,
                    status=OrderStatus.REJECTED,
                    platform=Platform.POLYMARKET,
                )

            self._state["positions"][cid]["quantity"] -= order.quantity
            self._state["cash"] += cost

            # Clean up empty positions
            if self._state["positions"][cid]["quantity"] <= 0:
                del self._state["positions"][cid]

        order_id = str(uuid4())
        now = datetime.now()

        # Record the order
        self._state["orders"].append({
            "order_id": order_id,
            "symbol": cid,
            "side": side_str,
            "quantity": order.quantity,
            "fill_price": fill_price,
            "timestamp": now.isoformat(),
        })

        self._save_state()

        log.info(f"Paper fill: {side_str.upper()} {order.quantity} of {cid} @ ${fill_price:.4f}")

        return OrderResult(
            order_id=order_id,
            symbol=cid,
            side=order.side,
            quantity=order.quantity,
            status=OrderStatus.FILLED,
            filled_price=fill_price,
            filled_at=now,
            platform=Platform.POLYMARKET,
        )

    async def cancel_order(self, order_id: str) -> bool:
        # Paper orders fill immediately, nothing to cancel
        log.info(f"Paper orders fill instantly — nothing to cancel for {order_id}")
        return False

    async def get_order_status(self, order_id: str) -> OrderStatus:
        for order in self._state["orders"]:
            if order["order_id"] == order_id:
                return OrderStatus.FILLED
        return OrderStatus.REJECTED

    async def get_quote(self, symbol: str) -> float:
        market = await get_polymarket_data(symbol)
        return market.yes_price

    def reset(self) -> None:
        """Reset paper trading state."""
        self._state = {
            "cash": self._initial_balance,
            "positions": {},
            "orders": [],
        }
        self._save_state()
        log.info(f"Paper trading state reset to ${self._initial_balance:,.2f}")
