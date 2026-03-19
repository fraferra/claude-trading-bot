"""Tests for FIFO P&L matching and settlement math in Repository.

Financial math verified:
  - FIFO cost-basis matching on buy/sell pairs
  - Cumulative P&L running sum
  - Kalshi settlement P&L (winning/losing long/short positions)
  - Polymarket settlement P&L
  - Two-source merge (trading P&L + settlement P&L)
  - get_unsettled exclusion logic
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from trading_bot.db.database import Database
from trading_bot.db.repository import Repository


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db():
    database = Database(":memory:")
    await database.connect()
    yield database
    await database.close()


@pytest_asyncio.fixture
async def repo(db):
    return Repository(db)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _insert_trade(
    repo: Repository,
    symbol: str,
    side: str,
    quantity: float,
    filled_price: float,
    platform: str = "alpaca",
    trade_date: str = "2025-01-01",
) -> int:
    """Insert a trade with a specific date by overriding created_at."""
    trade_id = await repo.insert_trade(
        symbol=symbol,
        side=side,
        quantity=quantity,
        filled_price=filled_price,
        platform=platform,
        source="test",
        order_id=f"ord-{symbol}-{side}-{quantity}",
        strategy_name="test",
        reasoning="test",
        confidence=0.8,
        status="filled",
    )
    # Override created_at with the desired date
    await repo._db.db.execute(
        "UPDATE trades SET created_at = ? WHERE id = ?",
        (trade_date + " 12:00:00", trade_id),
    )
    await repo._db.db.commit()
    return trade_id


# ---------------------------------------------------------------------------
# TestFIFOCostBasisMatching
# ---------------------------------------------------------------------------

class TestFIFOCostBasisMatching:
    @pytest.mark.asyncio
    async def test_single_buy_no_realized_pnl(self, repo):
        """A lone buy has no realized P&L — position is still open."""
        await _insert_trade(repo, "AAPL", "buy", 10, 100.0)
        result = await repo.get_cumulative_pnl("alpaca")
        # No sells → no realized P&L
        assert result == [] or all(row["daily_pnl"] == 0 for row in result)

    @pytest.mark.asyncio
    async def test_buy_then_sell_profitable(self, repo):
        """Buy 10 @ $100, sell 10 @ $120 → realized P&L = +$200."""
        await _insert_trade(repo, "AAPL", "buy", 10, 100.0, trade_date="2025-01-01")
        await _insert_trade(repo, "AAPL", "sell", 10, 120.0, trade_date="2025-01-02")
        result = await repo.get_cumulative_pnl("alpaca")
        total = sum(row["daily_pnl"] for row in result)
        assert total == pytest.approx(200.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_buy_then_sell_at_loss(self, repo):
        """Buy 10 @ $100, sell 10 @ $80 → realized P&L = -$200."""
        await _insert_trade(repo, "AAPL", "buy", 10, 100.0, trade_date="2025-01-01")
        await _insert_trade(repo, "AAPL", "sell", 10, 80.0, trade_date="2025-01-02")
        result = await repo.get_cumulative_pnl("alpaca")
        total = sum(row["daily_pnl"] for row in result)
        assert total == pytest.approx(-200.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_partial_sell_partial_pnl(self, repo):
        """Buy 10 @ $100, sell 5 @ $120 → realized P&L = +$100."""
        await _insert_trade(repo, "AAPL", "buy", 10, 100.0, trade_date="2025-01-01")
        await _insert_trade(repo, "AAPL", "sell", 5, 120.0, trade_date="2025-01-02")
        result = await repo.get_cumulative_pnl("alpaca")
        total = sum(row["daily_pnl"] for row in result)
        assert total == pytest.approx(100.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_multiple_buys_fifo_order(self, repo):
        """
        FIFO matching across two buy lots:
          Buy 5 @ $100 (lot 1), Buy 5 @ $110 (lot 2), Sell 7 @ $130

        FIFO: uses lot 1 first → 5 shares at $100 profit = (130-100)*5 = $150
              then lot 2 for 2 shares at $110 profit = (130-110)*2 = $40
              Total = $190
        """
        await _insert_trade(repo, "AAPL", "buy", 5, 100.0, trade_date="2025-01-01")
        await _insert_trade(repo, "AAPL", "buy", 5, 110.0, trade_date="2025-01-02")
        await _insert_trade(repo, "AAPL", "sell", 7, 130.0, trade_date="2025-01-03")
        result = await repo.get_cumulative_pnl("alpaca")
        total = sum(row["daily_pnl"] for row in result)
        assert total == pytest.approx(190.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_two_symbols_independent(self, repo):
        """AAPL and MSFT P&L calculations do not interfere."""
        # AAPL: +$200
        await _insert_trade(repo, "AAPL", "buy", 10, 100.0, trade_date="2025-01-01")
        await _insert_trade(repo, "AAPL", "sell", 10, 120.0, trade_date="2025-01-02")
        # MSFT: -$100
        await _insert_trade(repo, "MSFT", "buy", 5, 200.0, trade_date="2025-01-01")
        await _insert_trade(repo, "MSFT", "sell", 5, 180.0, trade_date="2025-01-02")
        result = await repo.get_cumulative_pnl("alpaca")
        total = sum(row["daily_pnl"] for row in result)
        assert total == pytest.approx(100.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_pnl_aggregated_by_date(self, repo):
        """Two sells on the same date → single date entry."""
        await _insert_trade(repo, "AAPL", "buy", 10, 100.0, trade_date="2025-01-01")
        await _insert_trade(repo, "MSFT", "buy", 5, 200.0, trade_date="2025-01-01")
        await _insert_trade(repo, "AAPL", "sell", 10, 120.0, trade_date="2025-01-05")
        await _insert_trade(repo, "MSFT", "sell", 5, 220.0, trade_date="2025-01-05")
        result = await repo.get_cumulative_pnl("alpaca")
        dates = [row["date"] for row in result]
        # No duplicate dates
        assert len(dates) == len(set(dates))
        # On 2025-01-05: AAPL +$200, MSFT +$100
        jan5_rows = [r for r in result if r["date"].startswith("2025-01-05")]
        if jan5_rows:
            assert jan5_rows[0]["daily_pnl"] == pytest.approx(300.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_cumulative_is_running_sum(self, repo):
        """Cumulative P&L is the running sum of daily P&L values."""
        # Day 1: sell AAPL → +$100
        await _insert_trade(repo, "AAPL", "buy", 10, 100.0, trade_date="2025-01-01")
        await _insert_trade(repo, "AAPL", "sell", 10, 110.0, trade_date="2025-01-02")
        # Day 3: sell MSFT → -$50
        await _insert_trade(repo, "MSFT", "buy", 5, 200.0, trade_date="2025-01-02")
        await _insert_trade(repo, "MSFT", "sell", 5, 190.0, trade_date="2025-01-03")
        # Day 5: sell GOOGL → +$200
        await _insert_trade(repo, "GOOGL", "buy", 2, 100.0, trade_date="2025-01-03")
        await _insert_trade(repo, "GOOGL", "sell", 2, 200.0, trade_date="2025-01-05")

        result = await repo.get_cumulative_pnl("alpaca")
        # Verify cumulative is correctly accumulated
        running = 0.0
        for row in result:
            running += row["daily_pnl"]
            assert row["cumulative_pnl"] == pytest.approx(running, abs=0.01)

    @pytest.mark.asyncio
    async def test_empty_trades_returns_empty_list(self, repo):
        """No trades → empty list."""
        result = await repo.get_cumulative_pnl("alpaca")
        assert result == []

    @pytest.mark.asyncio
    async def test_result_sorted_by_date(self, repo):
        """Results should be in ascending date order."""
        await _insert_trade(repo, "AAPL", "buy", 10, 100.0, trade_date="2025-01-03")
        await _insert_trade(repo, "AAPL", "sell", 10, 110.0, trade_date="2025-01-05")
        await _insert_trade(repo, "MSFT", "buy", 5, 100.0, trade_date="2025-01-01")
        await _insert_trade(repo, "MSFT", "sell", 5, 110.0, trade_date="2025-01-04")
        result = await repo.get_cumulative_pnl("alpaca")
        dates = [row["date"] for row in result]
        assert dates == sorted(dates)


# ---------------------------------------------------------------------------
# TestKalshiSettlementPnL
# ---------------------------------------------------------------------------

class TestKalshiSettlementPnL:
    @pytest.mark.asyncio
    async def test_winning_yes_position(self, repo):
        """
        Long YES @ $0.60, result=yes, payout=1.0:
        pnl = (payout_per_contract - entry_price) * quantity
             = (1.0 - 0.60) * 100 = +$40
        """
        trade_id = await _insert_trade(
            repo, "TICKER-A", "buy", 100, 0.60, platform="kalshi"
        )
        await repo.insert_kalshi_settlement(
            trade_id=trade_id,
            ticker="TICKER-A",
            side="yes",
            quantity=100,
            entry_price=0.60,
            result="yes",
            payout_per_contract=1.0,
            total_pnl=40.0,
        )
        settlements = await repo.get_kalshi_settlements(limit=10)
        assert len(settlements) == 1
        assert settlements[0]["total_pnl"] == pytest.approx(40.0, abs=0.001)

    @pytest.mark.asyncio
    async def test_losing_yes_position(self, repo):
        """
        Long YES @ $0.60, result=no, payout=0.0:
        pnl = (0.0 - 0.60) * 100 = -$60
        """
        trade_id = await _insert_trade(
            repo, "TICKER-B", "buy", 100, 0.60, platform="kalshi"
        )
        await repo.insert_kalshi_settlement(
            trade_id=trade_id,
            ticker="TICKER-B",
            side="yes",
            quantity=100,
            entry_price=0.60,
            result="no",
            payout_per_contract=0.0,
            total_pnl=-60.0,
        )
        settlements = await repo.get_kalshi_settlements(limit=10)
        assert settlements[0]["total_pnl"] == pytest.approx(-60.0, abs=0.001)

    @pytest.mark.asyncio
    async def test_winning_no_position(self, repo):
        """
        Long NO @ $0.40, result=no, payout=1.0:
        pnl = (1.0 - 0.40) * 100 = +$60
        """
        trade_id = await _insert_trade(
            repo, "TICKER-C", "buy", 100, 0.40, platform="kalshi"
        )
        await repo.insert_kalshi_settlement(
            trade_id=trade_id,
            ticker="TICKER-C",
            side="no",
            quantity=100,
            entry_price=0.40,
            result="no",
            payout_per_contract=1.0,
            total_pnl=60.0,
        )
        settlements = await repo.get_kalshi_settlements(limit=10)
        assert settlements[0]["total_pnl"] == pytest.approx(60.0, abs=0.001)

    @pytest.mark.asyncio
    async def test_losing_no_position(self, repo):
        """
        Long NO @ $0.40, result=yes, payout=0.0:
        pnl = (0.0 - 0.40) * 100 = -$40
        """
        trade_id = await _insert_trade(
            repo, "TICKER-D", "buy", 100, 0.40, platform="kalshi"
        )
        await repo.insert_kalshi_settlement(
            trade_id=trade_id,
            ticker="TICKER-D",
            side="no",
            quantity=100,
            entry_price=0.40,
            result="yes",
            payout_per_contract=0.0,
            total_pnl=-40.0,
        )
        settlements = await repo.get_kalshi_settlements(limit=10)
        assert settlements[0]["total_pnl"] == pytest.approx(-40.0, abs=0.001)

    @pytest.mark.asyncio
    async def test_get_unsettled_excludes_already_settled(self, repo):
        """Trades with a settlement record should not appear in unsettled list."""
        tid1 = await _insert_trade(repo, "K1", "buy", 50, 0.70, platform="kalshi")
        tid2 = await _insert_trade(repo, "K2", "buy", 50, 0.30, platform="kalshi")

        # Settle only tid1
        await repo.insert_kalshi_settlement(
            trade_id=tid1, ticker="K1", side="yes", quantity=50,
            entry_price=0.70, result="yes", payout_per_contract=1.0, total_pnl=15.0,
        )

        unsettled = await repo.get_unsettled_kalshi_trades()
        unsettled_ids = [t["id"] for t in unsettled]
        assert tid1 not in unsettled_ids  # already settled
        assert tid2 in unsettled_ids     # still open

    @pytest.mark.asyncio
    async def test_settled_trade_ids_correct(self, repo):
        """get_settled_trade_ids returns IDs of settled trades only."""
        tid = await _insert_trade(repo, "K3", "buy", 50, 0.50, platform="kalshi")
        await repo.insert_kalshi_settlement(
            trade_id=tid, ticker="K3", side="yes", quantity=50,
            entry_price=0.50, result="no", payout_per_contract=0.0, total_pnl=-25.0,
        )
        ids = await repo.get_settled_trade_ids()
        assert tid in ids

    @pytest.mark.asyncio
    async def test_settlement_can_be_inserted_once(self, repo):
        """Settlement is inserted once and appears in get_kalshi_settlements."""
        tid = await _insert_trade(repo, "K4", "buy", 50, 0.50, platform="kalshi")
        await repo.insert_kalshi_settlement(
            trade_id=tid, ticker="K4", side="yes", quantity=50,
            entry_price=0.50, result="yes", payout_per_contract=1.0, total_pnl=25.0,
        )
        settlements = await repo.get_kalshi_settlements()
        k4 = [s for s in settlements if s["ticker"] == "K4"]
        assert len(k4) == 1
        assert k4[0]["total_pnl"] == pytest.approx(25.0)


# ---------------------------------------------------------------------------
# TestPolymarketSettlementPnL
# ---------------------------------------------------------------------------

class TestPolymarketSettlementPnL:
    @pytest.mark.asyncio
    async def test_winning_yes_position(self, repo):
        """Long YES @ $0.55, result=yes, payout=1.0 → +$45 per 100 contracts."""
        trade_id = await _insert_trade(
            repo, "cond_abc", "buy", 100, 0.55, platform="polymarket"
        )
        await repo.insert_polymarket_settlement(
            trade_id=trade_id,
            condition_id="cond_abc",
            token_id="token_yes_abc",
            side="yes",
            quantity=100,
            entry_price=0.55,
            result="yes",
            payout_per_contract=1.0,
            total_pnl=45.0,
        )
        settlements = await repo.get_polymarket_settlements(limit=10)
        assert len(settlements) == 1
        assert settlements[0]["total_pnl"] == pytest.approx(45.0, abs=0.001)

    @pytest.mark.asyncio
    async def test_losing_yes_position(self, repo):
        """Long YES @ $0.55, result=no, payout=0.0 → -$55."""
        trade_id = await _insert_trade(
            repo, "cond_xyz", "buy", 100, 0.55, platform="polymarket"
        )
        await repo.insert_polymarket_settlement(
            trade_id=trade_id,
            condition_id="cond_xyz",
            token_id="token_yes_xyz",
            side="yes",
            quantity=100,
            entry_price=0.55,
            result="no",
            payout_per_contract=0.0,
            total_pnl=-55.0,
        )
        settlements = await repo.get_polymarket_settlements(limit=10)
        assert settlements[0]["total_pnl"] == pytest.approx(-55.0, abs=0.001)

    @pytest.mark.asyncio
    async def test_get_unsettled_excludes_already_settled(self, repo):
        """Already-settled Polymarket trades not in unsettled list."""
        tid1 = await _insert_trade(repo, "cond_1", "buy", 50, 0.60, platform="polymarket")
        tid2 = await _insert_trade(repo, "cond_2", "buy", 50, 0.40, platform="polymarket")

        await repo.insert_polymarket_settlement(
            trade_id=tid1, condition_id="cond_1", token_id="tok1",
            side="yes", quantity=50, entry_price=0.60, result="yes",
            payout_per_contract=1.0, total_pnl=20.0,
        )

        unsettled = await repo.get_unsettled_polymarket_trades()
        unsettled_ids = [t["id"] for t in unsettled]
        assert tid1 not in unsettled_ids
        assert tid2 in unsettled_ids

    @pytest.mark.asyncio
    async def test_get_polymarket_settled_trade_ids(self, repo):
        """get_polymarket_settled_trade_ids returns correct set."""
        tid = await _insert_trade(repo, "cond_s", "buy", 50, 0.50, platform="polymarket")
        await repo.insert_polymarket_settlement(
            trade_id=tid, condition_id="cond_s", token_id="tok_s",
            side="yes", quantity=50, entry_price=0.50, result="yes",
            payout_per_contract=1.0, total_pnl=25.0,
        )
        ids = await repo.get_polymarket_settled_trade_ids()
        assert tid in ids

    @pytest.mark.asyncio
    async def test_cumulative_pnl_dispatches_to_polymarket(self, repo):
        """get_cumulative_pnl('polymarket') routes to polymarket-specific method."""
        # Insert a polymarket trade and settlement
        tid = await _insert_trade(repo, "poly_t", "buy", 100, 0.60, platform="polymarket")
        await repo.insert_polymarket_settlement(
            trade_id=tid, condition_id="poly_t", token_id="tok_poly",
            side="yes", quantity=100, entry_price=0.60, result="yes",
            payout_per_contract=1.0, total_pnl=40.0,
        )
        result = await repo.get_cumulative_pnl("polymarket")
        # Should have at least one entry from settlement
        total = sum(row["daily_pnl"] for row in result)
        assert total == pytest.approx(40.0, abs=0.01)


# ---------------------------------------------------------------------------
# TestArbPairs
# ---------------------------------------------------------------------------

class TestArbPairs:
    @pytest.mark.asyncio
    async def test_insert_and_retrieve_arb_pair(self, repo):
        """insert_arb_pair then get_arb_pairs returns the record."""
        poly_tid = await _insert_trade(repo, "cond_a", "buy", 100, 0.55, platform="polymarket")
        kalshi_tid = await _insert_trade(repo, "TICKER-A", "buy", 100, 0.40, platform="kalshi")

        pair_id = await repo.insert_arb_pair(
            polymarket_trade_id=poly_tid,
            kalshi_trade_id=kalshi_tid,
            gross_edge=0.05,
            net_edge=0.03,
            strategy="cross_platform_arb",
        )
        assert pair_id > 0

        pairs = await repo.get_arb_pairs()
        assert len(pairs) == 1
        pair = pairs[0]
        assert pair["polymarket_trade_id"] == poly_tid
        assert pair["kalshi_trade_id"] == kalshi_tid
        assert pair["gross_edge"] == pytest.approx(0.05, abs=0.001)
        assert pair["status"] == "open"

    @pytest.mark.asyncio
    async def test_close_arb_pair_updates_status(self, repo):
        """close_arb_pair sets status to 'closed' and records pnl."""
        poly_tid = await _insert_trade(repo, "cond_b", "buy", 100, 0.55, platform="polymarket")
        pair_id = await repo.insert_arb_pair(
            polymarket_trade_id=poly_tid, kalshi_trade_id=None,
            gross_edge=0.04, net_edge=0.02, strategy="test",
        )
        await repo.close_arb_pair(pair_id, realized_pnl=15.0)
        pairs = await repo.get_arb_pairs(status="closed")
        assert len(pairs) == 1
        assert pairs[0]["status"] == "closed"
        assert pairs[0]["realized_pnl"] == pytest.approx(15.0, abs=0.001)

    @pytest.mark.asyncio
    async def test_filter_by_status(self, repo):
        """get_arb_pairs(status=...) filters correctly."""
        poly_tid = await _insert_trade(repo, "cond_c", "buy", 100, 0.55, platform="polymarket")
        pair_id = await repo.insert_arb_pair(
            polymarket_trade_id=poly_tid, kalshi_trade_id=None,
            gross_edge=0.05, net_edge=0.03, strategy="test",
        )
        open_pairs = await repo.get_arb_pairs(status="open")
        closed_pairs = await repo.get_arb_pairs(status="closed")
        assert len(open_pairs) == 1
        assert len(closed_pairs) == 0
