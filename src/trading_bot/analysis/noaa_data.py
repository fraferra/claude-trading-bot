"""NOAA Weather.gov API client — free, no API key required.

Fetches 7-day weather forecasts for US cities and extracts probability
estimates that can be compared against Polymarket weather event prices.

API flow:
  1. GET api.weather.gov/points/{lat},{lon}  → gridpoint metadata
  2. GET {properties.forecast}               → 12-hour forecast periods
  3. Parse probabilityOfPrecipitation, temperature, windSpeed
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import httpx

from trading_bot.utils.logging import log

NOAA_BASE = "https://api.weather.gov"

# NOAA requires a descriptive User-Agent
_HEADERS = {
    "User-Agent": "claude-trading-bot/1.0 weather-arb-research",
    "Accept": "application/geo+json",
}

# Supported US cities → (latitude, longitude)
CITY_COORDS: dict[str, tuple[float, float]] = {
    "new york":         (40.7128, -74.0060),
    "new york city":    (40.7128, -74.0060),
    "nyc":              (40.7128, -74.0060),
    "los angeles":      (34.0522, -118.2437),
    "la":               (34.0522, -118.2437),
    "chicago":          (41.8781, -87.6298),
    "houston":          (29.7604, -95.3698),
    "phoenix":          (33.4484, -112.0740),
    "philadelphia":     (39.9526, -75.1652),
    "san antonio":      (29.4241, -98.4936),
    "san diego":        (32.7157, -117.1611),
    "dallas":           (32.7767, -96.7970),
    "san jose":         (37.3382, -121.8863),
    "austin":           (30.2672, -97.7431),
    "san francisco":    (37.7749, -122.4194),
    "sf":               (37.7749, -122.4194),
    "seattle":          (47.6062, -122.3321),
    "denver":           (39.7392, -104.9903),
    "washington":       (38.9072, -77.0369),
    "washington dc":    (38.9072, -77.0369),
    "dc":               (38.9072, -77.0369),
    "nashville":        (36.1627, -86.7816),
    "boston":           (42.3601, -71.0589),
    "portland":         (45.5051, -122.6750),
    "las vegas":        (36.1699, -115.1398),
    "memphis":          (35.1495, -90.0490),
    "louisville":       (38.2527, -85.7585),
    "baltimore":        (39.2904, -76.6122),
    "milwaukee":        (43.0389, -87.9065),
    "albuquerque":      (35.0853, -106.6056),
    "kansas city":      (39.0997, -94.5786),
    "atlanta":          (33.7490, -84.3880),
    "raleigh":          (35.7796, -78.6382),
    "minneapolis":      (44.9778, -93.2650),
    "miami":            (25.7617, -80.1918),
    "new orleans":      (29.9511, -90.0715),
    "tampa":            (27.9506, -82.4572),
    "detroit":          (42.3314, -83.0458),
    "pittsburgh":       (40.4406, -79.9959),
    "cincinnati":       (39.1031, -84.5120),
    "cleveland":        (41.4993, -81.6944),
    "salt lake city":   (40.7608, -111.8910),
    "st louis":         (38.6270, -90.1994),
    "saint louis":      (38.6270, -90.1994),
    "charlotte":        (35.2271, -80.8431),
    "indianapolis":     (39.7684, -86.1581),
    "columbus":         (39.9612, -82.9988),
    "el paso":          (31.7619, -106.4850),
    "fort worth":       (32.7555, -97.3308),
    "jacksonville":     (30.3322, -81.6557),
    "sacramento":       (38.5816, -121.4944),
    "tucson":           (32.2226, -110.9747),
    "fresno":           (36.7378, -119.7871),
    "colorado springs": (38.8339, -104.8214),
    "virginia beach":   (36.8529, -75.9780),
    "omaha":            (41.2565, -95.9345),
    "long beach":       (33.7701, -118.1937),
    "mesa":             (33.4152, -111.8315),
}


@dataclass
class ForecastPeriod:
    """A single forecast period (typically 12-hour daytime or nighttime)."""
    name: str                        # e.g. "Tonight", "Thursday"
    start: datetime
    end: datetime
    is_daytime: bool
    temperature_f: float | None      # Forecast temperature in °F
    precip_probability: float | None # 0.0–1.0 probability of precipitation
    short_forecast: str = ""


@dataclass
class CityForecast:
    """Full 7-day forecast for a city."""
    city: str
    lat: float
    lon: float
    periods: list[ForecastPeriod] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


async def _get_gridpoint_url(lat: float, lon: float, client: httpx.AsyncClient) -> str | None:
    """Resolve (lat, lon) to the NOAA gridpoint forecast URL."""
    url = f"{NOAA_BASE}/points/{lat:.4f},{lon:.4f}"
    try:
        resp = await client.get(url, headers=_HEADERS, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
        return data["properties"]["forecast"]
    except Exception as e:
        log.warning(f"NOAA points lookup failed for ({lat},{lon}): {e}")
        return None


def _parse_period(raw: dict) -> ForecastPeriod | None:
    """Parse a raw NOAA forecast period dict into a ForecastPeriod."""
    try:
        start = datetime.fromisoformat(raw["startTime"])
        end = datetime.fromisoformat(raw["endTime"])
        temp = raw.get("temperature")
        temp_unit = raw.get("temperatureUnit", "F")
        if temp is not None and temp_unit == "C":
            temp = temp * 9 / 5 + 32  # Convert Celsius to Fahrenheit

        pop_obj = raw.get("probabilityOfPrecipitation") or {}
        pop_value = pop_obj.get("value")  # 0–100 or None
        precip_prob = (float(pop_value) / 100.0) if pop_value is not None else None

        return ForecastPeriod(
            name=raw.get("name", ""),
            start=start,
            end=end,
            is_daytime=raw.get("isDaytime", True),
            temperature_f=float(temp) if temp is not None else None,
            precip_probability=precip_prob,
            short_forecast=raw.get("shortForecast", ""),
        )
    except Exception as e:
        log.debug(f"Failed to parse NOAA period: {e}")
        return None


async def get_city_forecast(city_name: str) -> CityForecast | None:
    """Fetch and return the 7-day forecast for a known US city.

    Returns None if the city is unknown or the API call fails.
    """
    key = city_name.lower().strip()
    coords = CITY_COORDS.get(key)
    if not coords:
        return None
    lat, lon = coords

    async with httpx.AsyncClient() as client:
        forecast_url = await _get_gridpoint_url(lat, lon, client)
        if not forecast_url:
            return None
        try:
            resp = await client.get(forecast_url, headers=_HEADERS, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
            raw_periods = data["properties"]["periods"]
        except Exception as e:
            log.warning(f"NOAA forecast fetch failed for {city_name}: {e}")
            return None

    periods = [p for raw in raw_periods if (p := _parse_period(raw)) is not None]
    return CityForecast(city=city_name, lat=lat, lon=lon, periods=periods)


def get_precip_probability_for_date(forecast: CityForecast, target_date: date) -> float | None:
    """Return the max precipitation probability for target_date across all periods.

    Uses the maximum across all forecast periods that overlap with target_date,
    which conservatively represents the chance of rain at any point during the day.
    """
    matching: list[float] = []
    for period in forecast.periods:
        period_date = period.start.date()
        if period_date == target_date and period.precip_probability is not None:
            matching.append(period.precip_probability)

    if not matching:
        return None
    return max(matching)


def get_high_temp_for_date(forecast: CityForecast, target_date: date) -> float | None:
    """Return the daytime high temperature (°F) for target_date, or None."""
    for period in forecast.periods:
        if period.start.date() == target_date and period.is_daytime and period.temperature_f is not None:
            return period.temperature_f
    return None


def get_low_temp_for_date(forecast: CityForecast, target_date: date) -> float | None:
    """Return the nighttime low temperature (°F) for target_date, or None."""
    for period in forecast.periods:
        if period.start.date() == target_date and not period.is_daytime and period.temperature_f is not None:
            return period.temperature_f
    return None


def estimate_temp_exceed_probability(forecast_temp: float, threshold_f: float) -> float:
    """Estimate P(high temp > threshold) using forecast temp as the mode.

    Uses a simple ±8°F standard deviation (typical NOAA forecast accuracy for
    the 1-7 day window) with a normal CDF approximation.

    Returns a probability in [0.0, 1.0].
    """
    import math
    std_dev = 8.0  # °F — typical NOAA forecast MAE for 3-day window
    z = (forecast_temp - threshold_f) / std_dev
    # Approximation of the normal CDF: Φ(z)
    # Uses the error function: Φ(z) = 0.5 * (1 + erf(z / sqrt(2)))
    prob = 0.5 * (1.0 + math.erf(z / math.sqrt(2)))
    return round(max(0.01, min(0.99, prob)), 4)


def detect_city_in_title(title: str) -> tuple[str, tuple[float, float]] | None:
    """Scan a market title for a known US city name. Returns (city, coords) or None."""
    lower = title.lower()
    # Try longest-match first (avoid "la" matching inside "dallas")
    for city in sorted(CITY_COORDS.keys(), key=len, reverse=True):
        # Word-boundary check: city should appear as a whole phrase
        pattern = r"\b" + re.escape(city) + r"\b"
        if re.search(pattern, lower):
            return city, CITY_COORDS[city]
    return None


def detect_weather_event(title: str) -> str | None:
    """Detect the type of weather event in a market title.

    Returns one of: 'precipitation', 'rain', 'snow', 'temperature_high',
    'temperature_low', 'wind', or None if unrecognized.
    """
    lower = title.lower()
    if any(w in lower for w in ("snow", "snowfall", "blizzard")):
        return "snow"
    if any(w in lower for w in ("rain", "rainfall", "precipitation", "precip")):
        return "precipitation"
    if any(w in lower for w in ("high temperature", "high temp", "high of", "exceed", "above", "degrees")):
        if any(w in lower for w in ("temperature", "temp", "°f", "°c", "degrees")):
            return "temperature_high"
    if any(w in lower for w in ("low temperature", "low temp", "below", "drop")):
        if any(w in lower for w in ("temperature", "temp", "°f", "°c", "degrees")):
            return "temperature_low"
    if "wind" in lower:
        return "wind"
    return None


def extract_temperature_threshold(title: str) -> float | None:
    """Extract a numeric temperature threshold from a market title.

    Handles patterns like:
      "exceed 85°F", "above 90 degrees", "below 32°F", "high of 75"
    """
    patterns = [
        r"(\d+(?:\.\d+)?)\s*°?\s*f\b",   # 85°F or 85F
        r"(\d+(?:\.\d+)?)\s*degrees?\s*f", # 85 degrees F
        r"(\d+(?:\.\d+)?)\s*degrees?",     # 85 degrees (assume F)
    ]
    for pat in patterns:
        m = re.search(pat, title.lower())
        if m:
            return float(m.group(1))
    return None


def extract_target_date(title: str) -> date | None:
    """Extract a target date from a market title.

    Handles patterns like: "March 21", "March 21, 2025", "3/21", "3/21/2025".
    Defaults to current year if not specified.
    """
    today = date.today()
    month_names = {
        "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
        "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6,
        "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sep": 9,
        "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
    }

    lower = title.lower()

    # Pattern: "March 21" or "March 21, 2025"
    for month_str, month_num in month_names.items():
        pat = rf"\b{month_str}\s+(\d{{1,2}})(?:,?\s+(\d{{4}}))?"
        m = re.search(pat, lower)
        if m:
            day = int(m.group(1))
            year = int(m.group(2)) if m.group(2) else today.year
            try:
                d = date(year, month_num, day)
                # If parsed date is far in the past, try next year
                if (today - d).days > 30:
                    d = date(year + 1, month_num, day)
                return d
            except ValueError:
                continue

    # Pattern: "3/21" or "3/21/2025"
    m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\b", title)
    if m:
        month_num = int(m.group(1))
        day = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else today.year
        try:
            return date(year, month_num, day)
        except ValueError:
            pass

    return None
