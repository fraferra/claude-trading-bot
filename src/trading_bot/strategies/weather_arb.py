"""Weather forecast arbitrage strategy.

Scans Polymarket for short-term weather event markets (rain, temperature, snow)
and compares market prices against NOAA Weather.gov forecast probabilities.

When NOAA's forecast diverges from the market price by more than min_edge_pct,
generates a trade decision.

No LLM calls — pure data comparison.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

from trading_bot.analysis.market_data import get_all_events, parse_event_to_model
from trading_bot.analysis.noaa_data import (
    CityForecast,
    detect_city_in_title,
    detect_weather_event,
    estimate_temp_exceed_probability,
    extract_target_date,
    extract_temperature_threshold,
    get_city_forecast,
    get_high_temp_for_date,
    get_low_temp_for_date,
    get_precip_probability_for_date,
)
from trading_bot.config import WeatherArbConfig
from trading_bot.models import Action, Side, StrategyResult, TradeDecision
from trading_bot.utils.logging import log

# Keywords that indicate a weather-related market
_WEATHER_KEYWORDS = {
    "rain", "rainfall", "precipitation", "precip",
    "snow", "snowfall", "blizzard",
    "temperature", "degrees", "°f", "°c",
    "wind", "hurricane", "tornado", "storm",
    "weather",
}


def _is_weather_market(title: str) -> bool:
    """Return True if the market title appears to be weather-related."""
    lower = title.lower()
    return any(kw in lower for kw in _WEATHER_KEYWORDS)


def _days_to_resolution(end_date_str: str | None) -> int | None:
    """Parse an event end date string and return days until resolution.

    Returns None if the end date cannot be parsed.
    """
    if not end_date_str:
        return None
    try:
        # Gamma API returns ISO format like "2025-03-21T23:59:00Z"
        if "T" in end_date_str:
            dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
            days = (dt.date() - date.today()).days
        else:
            d = date.fromisoformat(end_date_str[:10])
            days = (d - date.today()).days
        return max(0, days)
    except Exception:
        return None


class WeatherMarketSignal:
    """Encapsulates a single weather market with NOAA-derived edge."""

    def __init__(
        self,
        condition_id: str,
        question: str,
        yes_price: float,
        no_price: float,
        end_date: str | None,
        noaa_prob: float,
        event_type: str,
        city: str,
        target_date: date | None,
        forecast_detail: str,
        yes_token_id: str = "",
        no_token_id: str = "",
    ) -> None:
        self.condition_id = condition_id
        self.question = question
        self.yes_price = yes_price
        self.no_price = no_price
        self.end_date = end_date
        self.noaa_prob = noaa_prob
        self.event_type = event_type
        self.city = city
        self.target_date = target_date
        self.forecast_detail = forecast_detail
        self.yes_token_id = yes_token_id
        self.no_token_id = no_token_id

        # Edge = NOAA probability - market YES price (positive → buy YES, negative → buy NO)
        self.edge = noaa_prob - yes_price

    @property
    def abs_edge(self) -> float:
        return abs(self.edge)

    @property
    def is_no_bet(self) -> bool:
        """True when NOAA probability < market YES price (buy NO is the trade)."""
        return self.edge < 0

    @property
    def suggested_side(self) -> Side:
        # Always BUY — either the YES token or the NO token
        return Side.BUY

    @property
    def suggested_action(self) -> Action:
        return Action.BUY

    @property
    def trade_token_id(self) -> str:
        """The token_id to submit the order against (YES or NO token)."""
        if self.is_no_bet:
            return self.no_token_id or self.condition_id
        return self.yes_token_id or self.condition_id

    @property
    def trade_price(self) -> float:
        """The market price of the token being bought."""
        return self.no_price if self.is_no_bet else self.yes_price

    @property
    def confidence(self) -> float:
        # Scale: 0.60 at min_edge → 0.95 at 30%+ edge
        return round(min(0.95, 0.60 + self.abs_edge * 1.2), 4)

    def to_reasoning(self) -> str:
        side_str = "BUY NO" if self.is_no_bet else "BUY YES"
        return (
            f"[WEATHER|{self.city}] {self.event_type} | "
            f"NOAA={self.noaa_prob:.1%} vs market={self.yes_price:.1%} | "
            f"edge={self.edge:+.1%} → {side_str} | "
            f"forecast: {self.forecast_detail}"
        )


async def _fetch_noaa_for_market(
    title: str,
    end_date_str: str | None,
    city_forecasts: dict[str, CityForecast | None],
) -> tuple[float | None, str, str, date | None, str]:
    """Derive NOAA probability for a single market.

    Returns (noaa_prob, event_type, city_name, target_date, forecast_detail).
    Returns (None, ...) if the market cannot be matched to a NOAA forecast.
    """
    city_result = detect_city_in_title(title)
    if city_result is None:
        return None, "", "", None, ""
    city_name, _ = city_result

    event_type = detect_weather_event(title)
    if event_type is None:
        return None, "", city_name, None, ""

    # Determine target date (from title, falling back to end_date)
    target_date = extract_target_date(title)
    if target_date is None and end_date_str:
        try:
            if "T" in end_date_str:
                target_date = datetime.fromisoformat(
                    end_date_str.replace("Z", "+00:00")
                ).date()
            else:
                target_date = date.fromisoformat(end_date_str[:10])
        except Exception:
            pass

    if target_date is None:
        return None, event_type, city_name, None, ""

    # Fetch or reuse city forecast (cached in city_forecasts dict)
    if city_name not in city_forecasts:
        city_forecasts[city_name] = await get_city_forecast(city_name)
    forecast = city_forecasts[city_name]

    if forecast is None:
        return None, event_type, city_name, target_date, ""

    noaa_prob: float | None = None
    forecast_detail = ""

    if event_type in ("precipitation", "rain", "snow"):
        noaa_prob = get_precip_probability_for_date(forecast, target_date)
        if noaa_prob is not None:
            forecast_detail = f"{int(noaa_prob * 100)}% PoP on {target_date}"

    elif event_type == "temperature_high":
        threshold = extract_temperature_threshold(title)
        high_temp = get_high_temp_for_date(forecast, target_date)
        if high_temp is not None:
            if threshold is not None:
                noaa_prob = estimate_temp_exceed_probability(high_temp, threshold)
                forecast_detail = f"forecast high {high_temp:.0f}°F vs threshold {threshold:.0f}°F"
            else:
                # No threshold parseable — skip
                pass

    elif event_type == "temperature_low":
        threshold = extract_temperature_threshold(title)
        low_temp = get_low_temp_for_date(forecast, target_date)
        if low_temp is not None and threshold is not None:
            # P(low temp < threshold) — reverse: P(below)
            noaa_prob = 1.0 - estimate_temp_exceed_probability(low_temp, threshold)
            forecast_detail = f"forecast low {low_temp:.0f}°F vs threshold {threshold:.0f}°F"

    return noaa_prob, event_type, city_name, target_date, forecast_detail


class WeatherArbScanner:
    """Scans Polymarket for short-term weather markets and compares against NOAA data.

    For each weather market resolving within max_days_to_resolution:
    1. Detect city + event type from the market title
    2. Fetch NOAA forecast for that city
    3. Compute edge = |NOAA probability - market YES price|
    4. Generate BUY YES / BUY NO decision when edge > min_edge_pct
    """

    def __init__(self, config: WeatherArbConfig) -> None:
        self.config = config

    async def scan(self) -> StrategyResult:
        log.info(
            f"WeatherArbScanner: scanning Polymarket for weather events "
            f"(window: {self.config.min_days_to_resolution}–{self.config.max_days_to_resolution} days)"
        )

        # Fetch all active events and filter for weather relevance
        raw_events = await get_all_events(limit=500)
        events = [parse_event_to_model(e) for e in raw_events]

        weather_markets: list[tuple] = []  # (condition_id, question, yes_price, no_price, end_date)
        for event in events:
            days = _days_to_resolution(event.end_date)
            if days is None:
                continue
            if days < self.config.min_days_to_resolution:
                continue
            if days > self.config.max_days_to_resolution:
                continue

            for outcome in event.outcomes:
                if not _is_weather_market(outcome.question):
                    continue
                if outcome.liquidity < self.config.min_volume_usd:
                    continue
                if outcome.yes_price <= 0 or outcome.yes_price >= 1:
                    continue
                weather_markets.append((
                    outcome.condition_id,
                    outcome.question,
                    outcome.yes_price,
                    outcome.no_price,
                    event.end_date,
                    outcome.token_id,
                    outcome.no_token_id,
                ))

        log.info(f"WeatherArbScanner: {len(weather_markets)} weather markets in time window")

        # Fetch NOAA forecasts (city-level cache to avoid duplicate API calls)
        city_forecasts: dict[str, CityForecast | None] = {}
        signals: list[WeatherMarketSignal] = []

        for condition_id, question, yes_price, no_price, end_date, yes_token_id, no_token_id in weather_markets:
            try:
                noaa_prob, event_type, city_name, target_date, detail = await _fetch_noaa_for_market(
                    question, end_date, city_forecasts
                )
            except Exception as e:
                log.debug(f"NOAA lookup failed for '{question}': {e}")
                continue

            if noaa_prob is None or event_type == "" or city_name == "":
                continue

            signal = WeatherMarketSignal(
                condition_id=condition_id,
                question=question,
                yes_price=yes_price,
                no_price=no_price,
                end_date=end_date,
                noaa_prob=noaa_prob,
                event_type=event_type,
                city=city_name,
                target_date=target_date,
                forecast_detail=detail,
                yes_token_id=yes_token_id,
                no_token_id=no_token_id,
            )

            if signal.abs_edge >= self.config.min_edge_pct:
                signals.append(signal)

        # Sort by edge descending
        signals.sort(key=lambda s: s.abs_edge, reverse=True)
        log.info(f"WeatherArbScanner: {len(signals)} opportunities with edge >= {self.config.min_edge_pct:.1%}")

        decisions = [self._signal_to_decision(s) for s in signals]

        return StrategyResult(
            strategy_name="weather_arb",
            decisions=decisions,
            metadata={
                "weather_markets_found": len(weather_markets),
                "noaa_signals": len(signals),
                "opportunities": [
                    {
                        "condition_id": s.condition_id,
                        "question": s.question[:80],
                        "city": s.city,
                        "event_type": s.event_type,
                        "target_date": s.target_date.isoformat() if s.target_date else None,
                        "market_yes_price": s.yes_price,
                        "noaa_probability": s.noaa_prob,
                        "edge_pct": round(s.edge, 4),
                        "suggested_side": s.suggested_side.value,
                        "forecast_detail": s.forecast_detail,
                    }
                    for s in signals
                ],
            },
        )

    def _signal_to_decision(self, signal: WeatherMarketSignal) -> TradeDecision:
        return TradeDecision(
            action=signal.suggested_action,
            symbol=signal.trade_token_id,
            confidence=signal.confidence,
            reasoning=signal.to_reasoning(),
            suggested_size_usd=self.config.max_size_usd,
            side=signal.suggested_side,
        )
