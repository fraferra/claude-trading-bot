"""Temporal momentum arbitrage strategy.

Exploits the time lag between confirmed spot price momentum on Binance
and Polymarket's short-duration binary crypto markets (5/10/15-minute
"Will BTC be higher?" markets).

When Binance shows strong directional momentum (~85% confident direction)
but Polymarket still shows near-50/50 odds, we buy the correctly-priced
side before the market reprices.

No LLM calls — pure math and pattern matching.
"""

from __future__ import annotations

import math
import re
import time
from datetime import datetime, timezone

import httpx

from trading_bot.brokers.exchange_feed import BinanceExchangeFeed, PricePoint
from trading_bot.brokers.polymarket_ws import PolymarketWebSocketFeed
from trading_bot.config import TemporalMomentumConfig
from trading_bot.models import MomentumSignal, OrderBookFrontRunSignal, TemporalArbOpportunity
from trading_bot.utils.logging import log

POLYMARKET_CLOB = "https://clob.polymarket.com"

# Symbol patterns: map Binance symbol → short label
BINANCE_TO_LABEL: dict[str, str] = {
    "btcusdt": "BTC",
    "ethusdt": "ETH",
    "solusdt": "SOL",
}

# Regex to match minute-resolution crypto markets
_CRYPTO_PATTERN = re.compile(
    r"(btc|bitcoin|eth|ethereum|sol|solana)", re.I
)


# ---------------------------------------------------------------------------
# Pure helper functions (all testable without I/O)
# ---------------------------------------------------------------------------

def compute_price_change_pct(
    history: list[PricePoint],
    seconds_ago: int,
) -> float | None:
    """Return (current - reference) / reference for the given lookback.

    Finds the price point closest to `seconds_ago` seconds in the past.
    Returns None if history is insufficient.
    """
    if not history:
        return None
    now = time.time()
    target_ts = now - seconds_ago
    # Accept points within ±20% of the lookback window
    tolerance = max(seconds_ago * 0.20, 5.0)
    candidates = [p for p in history if abs(p.timestamp - target_ts) < tolerance]
    if not candidates:
        return None
    reference = min(candidates, key=lambda p: abs(p.timestamp - target_ts))
    current_price = history[-1].price
    if reference.price == 0:
        return None
    return (current_price - reference.price) / reference.price


def compute_momentum_strength(
    change_1m: float | None,
    change_3m: float | None,
    change_5m: float | None,
) -> float:
    """Weighted sigmoid composite score [0.0, 1.0].

    Weights: 1m=0.50, 3m=0.35, 5m=0.15.
    Sigmoid with k=200 maps 0.3% move → ~0.55, 1% → ~0.88.
    """
    k = 200.0
    components = [
        (change_1m, 0.50),
        (change_3m, 0.35),
        (change_5m, 0.15),
    ]
    total = 0.0
    total_weight = 0.0
    for change, weight in components:
        if change is None:
            continue
        score = 1.0 / (1.0 + math.exp(-k * abs(change)))
        total += score * weight
        total_weight += weight
    return total / total_weight if total_weight > 0 else 0.0


def determine_direction(
    change_1m: float | None,
    change_3m: float | None,
) -> str:
    """Return 'up', 'down', or 'flat'.

    Requires both 1m and 3m windows to agree in direction.
    Conflicting signals → 'flat' (no trade).
    """
    if change_1m is None or change_3m is None:
        return "flat"
    if change_1m > 0 and change_3m > 0:
        return "up"
    if change_1m < 0 and change_3m < 0:
        return "down"
    return "flat"


def compute_velocity(history: list[PricePoint]) -> float:
    """Return the second derivative (acceleration) of price.

    Uses the last 3 equidistant price points to estimate d²price/dt².
    Returns 0.0 if insufficient data.
    """
    if len(history) < 3:
        return 0.0
    p1, p2, p3 = history[-3], history[-2], history[-1]
    dt1 = p2.timestamp - p1.timestamp
    dt2 = p3.timestamp - p2.timestamp
    if dt1 <= 0 or dt2 <= 0:
        return 0.0
    v1 = (p2.price - p1.price) / dt1
    v2 = (p3.price - p2.price) / dt2
    avg_dt = (dt1 + dt2) / 2
    return (v2 - v1) / avg_dt if avg_dt > 0 else 0.0


def compute_fast_rsi(
    history: list[PricePoint],
    period: int = 3,
    bar_seconds: int = 10,
) -> float | None:
    """RSI(period) computed on bar_seconds-second bars.

    Returns None if there is insufficient history.
    """
    if not history:
        return None
    min_points = (period + 1) * max(1, bar_seconds // 2)
    if len(history) < min_points:
        return None

    # Bucket price points into bar_seconds-second bars (use last price per bar)
    earliest = history[0].timestamp
    bar_closes: dict[int, float] = {}
    for p in history:
        bar_idx = int((p.timestamp - earliest) / bar_seconds)
        bar_closes[bar_idx] = p.price  # last price in bar wins

    closes = [bar_closes[k] for k in sorted(bar_closes.keys())]
    if len(closes) < period + 1:
        return None

    closes = closes[-(period + 1):]
    gains = []
    losses = []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(0.0, delta))
        losses.append(max(0.0, -delta))

    avg_gain = sum(gains) / len(gains) if gains else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def estimate_true_probability(
    signal: MomentumSignal,
    config: TemporalMomentumConfig,
) -> float:
    """Map momentum signal to estimated binary market resolution probability.

    Returns P(YES), i.e.:
      - "up" direction → > 0.50
      - "down" direction → < 0.50
      - "flat" → 0.50 (no edge)

    Model: linear interpolation from strength=0.50→prob=0.50
    to strength=1.0→prob=config.prob_full_strength, plus a magnitude bonus.
    """
    if signal.direction == "flat":
        return 0.50

    # Base edge from strength composite
    # strength=0.50 → edge=0, strength=1.0 → edge=(prob_full_strength - 0.50)
    max_edge = config.prob_full_strength - 0.50
    normalised_strength = max(0.0, (signal.strength - 0.50) / 0.50)
    base_edge = normalised_strength * max_edge

    # Magnitude bonus: raw 1m move contributes up to +0.10 extra edge
    magnitude_bonus = min(0.10, abs(signal.change_1m_pct) * 5.0)
    total_edge = min(0.45, base_edge + magnitude_bonus)

    if signal.direction == "up":
        return min(0.95, 0.50 + total_edge)
    else:  # "down"
        return max(0.05, 0.50 - total_edge)


def calculate_edge(
    true_prob_yes: float,
    market_yes_price: float,
    market_no_price: float,
) -> tuple[str, float]:
    """Return (suggested_side, edge_pct) for the most profitable side."""
    yes_edge = true_prob_yes - market_yes_price
    no_edge = (1.0 - true_prob_yes) - market_no_price

    if yes_edge >= no_edge and yes_edge > 0:
        return "yes", yes_edge
    if no_edge > 0:
        return "no", no_edge
    return "yes", max(0.0, yes_edge)


def kelly_size(
    true_prob: float,
    market_price: float,
    kelly_fraction_cap: float,
    max_size_usd: float,
    available_cash: float,
) -> float:
    """Full Kelly position sizing for a binary market contract.

    b  = net odds = (1 - market_price) / market_price
    f* = (p*b - q) / b   where q = 1-p
    Returns fractional Kelly (capped), bounded by max_size_usd.
    """
    if market_price <= 0 or market_price >= 1:
        return 0.0
    b = (1.0 - market_price) / market_price
    q = 1.0 - true_prob
    full_kelly = (true_prob * b - q) / b
    frac = min(kelly_fraction_cap, max(0.0, full_kelly))
    raw = frac * available_cash
    return min(max_size_usd, raw)


# ---------------------------------------------------------------------------
# Strategy class
# ---------------------------------------------------------------------------

class TemporalMomentumArbStrategy:
    """Detects Polymarket binary crypto markets that lag Binance spot momentum.

    Not a BaseStrategy subclass — it requires a live exchange feed injected
    at call time. The monitor calls the public methods directly.
    """

    name = "temporal_momentum_arb"

    def __init__(self, config: TemporalMomentumConfig) -> None:
        self.config = config

    # ------------------------------------------------------------------
    # Signal computation
    # ------------------------------------------------------------------

    def compute_momentum_signal(
        self,
        symbol: str,
        binance_symbol: str,
        feed: BinanceExchangeFeed,
    ) -> MomentumSignal | None:
        """Build a MomentumSignal from the exchange feed's price history."""
        history = feed.get_price_history(
            binance_symbol, seconds=self.config.price_history_seconds
        )
        if len(history) < 10:
            return None

        current_price = feed.get_current_price(binance_symbol)
        if current_price is None:
            return None

        change_1m = compute_price_change_pct(history, seconds_ago=60)
        change_3m = compute_price_change_pct(history, seconds_ago=180)
        change_5m = compute_price_change_pct(history, seconds_ago=300)

        direction = determine_direction(change_1m, change_3m)
        strength = compute_momentum_strength(change_1m, change_3m, change_5m)
        rsi = compute_fast_rsi(history)
        velocity = compute_velocity(history)

        return MomentumSignal(
            symbol=symbol,
            current_price=current_price,
            change_1m_pct=change_1m or 0.0,
            change_3m_pct=change_3m or 0.0,
            change_5m_pct=change_5m or 0.0,
            velocity=velocity,
            rsi_fast=rsi,
            direction=direction,
            strength=strength,
        )

    # ------------------------------------------------------------------
    # Opportunity detection
    # ------------------------------------------------------------------

    def find_opportunities(
        self,
        signals: dict[str, MomentumSignal],
        active_markets: list[dict],
        poly_feed: PolymarketWebSocketFeed,
        available_cash: float,
    ) -> list[TemporalArbOpportunity]:
        """Match momentum signals to under-priced Polymarket markets."""
        cfg = self.config
        opportunities: list[TemporalArbOpportunity] = []

        for market in active_markets:
            symbol = market.get("symbol", "")
            signal = signals.get(symbol)
            if signal is None or signal.direction == "flat":
                continue
            if signal.strength < cfg.momentum_strength_threshold:
                continue

            # Guard: re-check expiry from live timestamp
            end_date_str = market.get("end_date", "")
            try:
                end_dt = datetime.fromisoformat(
                    end_date_str.replace("Z", "+00:00")
                )
                now_utc = datetime.now(timezone.utc)
                minutes_left = (end_dt - now_utc).total_seconds() / 60.0
            except Exception:
                continue
            if minutes_left < cfg.min_minutes_to_expiry:
                continue
            if minutes_left > cfg.max_minutes_to_expiry:
                continue

            # Get current Polymarket prices (prefer WS feed)
            yes_price = poly_feed.get_price_sync(market.get("token_id_yes", ""))
            no_price = poly_feed.get_price_sync(market.get("token_id_no", ""))

            # Fall back to REST-fetched prices from market dict
            if yes_price is None:
                yes_price = market.get("yes_price")
            if no_price is None:
                no_price = market.get("no_price")

            if yes_price is None or no_price is None:
                continue
            if not (0.05 <= yes_price <= 0.95):
                continue  # Already priced in the move

            true_prob = estimate_true_probability(signal, cfg)
            suggested_side, edge_pct = calculate_edge(true_prob, yes_price, no_price)

            if edge_pct < cfg.min_edge_pct or edge_pct > cfg.max_edge_pct:
                continue

            market_price = yes_price if suggested_side == "yes" else no_price
            true_p = true_prob if suggested_side == "yes" else (1.0 - true_prob)
            size = kelly_size(
                true_p, market_price,
                cfg.kelly_fraction_cap, cfg.max_size_usd, available_cash,
            )
            if size < 5.0:
                continue

            kelly_frac = size / available_cash if available_cash > 0 else 0.0
            opportunities.append(TemporalArbOpportunity(
                condition_id=market.get("condition_id", ""),
                token_id_yes=market.get("token_id_yes", ""),
                token_id_no=market.get("token_id_no", ""),
                question=market.get("question", ""),
                market_yes_price=yes_price,
                market_no_price=no_price,
                momentum_signal=signal,
                estimated_true_prob=true_prob,
                edge_pct=edge_pct,
                suggested_side=suggested_side,
                minutes_to_expiry=minutes_left,
                kelly_fraction=kelly_frac,
                suggested_size_usd=size,
            ))

        return sorted(opportunities, key=lambda o: o.edge_pct, reverse=True)

    # ------------------------------------------------------------------
    # Front-running detection
    # ------------------------------------------------------------------

    def compute_frontrun_signals(
        self,
        active_markets: list[dict],
        poly_feed: PolymarketWebSocketFeed,
    ) -> list[OrderBookFrontRunSignal]:
        """Detect large incoming buy orders that will push YES prices up.

        Heuristic: if the best bid in the WS book is within 5% of the best ask
        AND the total ask depth above the ask is thin, a large market-buy is
        likely imminent.  We position just ahead of it.

        Note: This uses the cached price from the WS feed.  For full order-book
        front-running, the PolymarketWebSocketFeed would need to store depth
        data from "book" events (currently it only caches best bid/ask mid).
        This is a lightweight approximation using the existing feed.
        """
        signals: list[OrderBookFrontRunSignal] = []
        cfg = self.config

        if not cfg.frontrun_enabled:
            return signals

        for market in active_markets:
            token_id_yes = market.get("token_id_yes", "")
            if not token_id_yes:
                continue

            entry = poly_feed._price_cache.get(token_id_yes)
            if entry is None:
                continue

            bid = entry.bid
            ask = entry.ask
            if ask <= 0 or bid <= 0:
                continue

            # Large bid close to ask → sign of an incoming large buy order
            spread = ask - bid
            if spread < 0 or spread / ask > 0.05:
                continue  # spread too wide, not a front-run candidate

            # Estimate potential price impact from a large order
            # (thin ask-side liquidity × impact factor)
            volume = market.get("volume", 0.0)
            if volume < cfg.min_volume_usd:
                continue

            # Very rough impact estimate: 1% per $1K of order at the ask
            estimated_impact = min(0.05, cfg.frontrun_min_order_size_usd / (volume * 10))

            signals.append(OrderBookFrontRunSignal(
                token_id=token_id_yes,
                question=market.get("question", ""),
                current_best_ask=ask,
                large_order_size_usd=cfg.frontrun_min_order_size_usd,
                estimated_price_impact=estimated_impact,
                suggested_entry_price=ask,
                suggested_size_usd=cfg.frontrun_max_size_usd,
            ))

        return signals

    # ------------------------------------------------------------------
    # Market discovery (async)
    # ------------------------------------------------------------------

    async def find_active_crypto_markets(self) -> list[dict]:
        """Fetch active Polymarket binary crypto short-duration markets.

        Returns a list of dicts with keys:
          condition_id, token_id_yes, token_id_no, question,
          end_date, minutes_remaining, symbol, yes_price, no_price, volume
        """
        cfg = self.config
        markets: list[dict] = []

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                cursor = ""
                fetched = 0
                while fetched < 500:
                    params: dict = {"active": "true"}
                    if cursor:
                        params["next_cursor"] = cursor

                    resp = await client.get(
                        f"{POLYMARKET_CLOB}/markets",
                        params=params,
                    )
                    if resp.status_code != 200:
                        break
                    payload = resp.json()
                    data = payload if isinstance(payload, list) else payload.get("data", [])
                    if not data:
                        break

                    now_utc = datetime.now(timezone.utc)
                    for market in data:
                        result = _parse_crypto_market(market, now_utc, cfg)
                        if result:
                            markets.append(result)

                    fetched += len(data)
                    cursor = payload.get("next_cursor", "") if isinstance(payload, dict) else ""
                    if not cursor or cursor == "LTE=":
                        break

        except Exception as e:
            log.warning(f"TemporalMomentumArbStrategy: failed to fetch markets: {e}")

        log.debug(
            f"TemporalMomentumArbStrategy: found {len(markets)} active crypto markets "
            f"in expiry window [{cfg.min_minutes_to_expiry}, {cfg.max_minutes_to_expiry}] min"
        )
        return markets


def _parse_crypto_market(
    market: dict,
    now_utc: datetime,
    cfg: TemporalMomentumConfig,
) -> dict | None:
    """Parse a single CLOB market dict.  Returns None if it doesn't qualify."""
    question = market.get("question", "")

    # Must mention a crypto symbol
    sym_match = _CRYPTO_PATTERN.search(question)
    if not sym_match:
        return None

    symbol_text = sym_match.group(1).lower()
    if symbol_text in ("btc", "bitcoin"):
        symbol = "BTC"
    elif symbol_text in ("eth", "ethereum"):
        symbol = "ETH"
    elif symbol_text in ("sol", "solana"):
        symbol = "SOL"
    else:
        return None

    # Check expiry
    end_date_str = market.get("end_date_iso", "") or market.get("end_date", "")
    if not end_date_str:
        return None
    try:
        end_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        minutes_remaining = (end_dt - now_utc).total_seconds() / 60.0
    except Exception:
        return None

    if minutes_remaining < cfg.min_minutes_to_expiry:
        return None
    if minutes_remaining > cfg.max_minutes_to_expiry:
        return None

    # Extract YES/NO token IDs
    yes_token = no_token = ""
    yes_price = no_price = 0.5
    for token in market.get("tokens", []):
        outcome = token.get("outcome", "").lower()
        tid = token.get("token_id", "")
        price = float(token.get("price", 0.5) or 0.5)
        if outcome == "yes":
            yes_token = tid
            yes_price = price
        elif outcome == "no":
            no_token = tid
            no_price = price

    if not yes_token:
        return None

    volume = float(market.get("volume", 0) or 0)
    if volume < cfg.min_volume_usd:
        return None

    return {
        "condition_id": market.get("condition_id", ""),
        "token_id_yes": yes_token,
        "token_id_no": no_token,
        "question": question,
        "end_date": end_date_str,
        "minutes_remaining": minutes_remaining,
        "symbol": symbol,
        "yes_price": yes_price,
        "no_price": no_price,
        "volume": volume,
    }
