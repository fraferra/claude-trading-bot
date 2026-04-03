from __future__ import annotations

import asyncio
import json as json_module
from functools import partial

import httpx
import yfinance as yf

from trading_bot.models import EventData, MarketOutcome, NewsItem, PolymarketData, StockData, StockFundamentals
from trading_bot.utils.logging import log


async def get_stock_data(symbol: str, period: str = "3mo") -> StockData:
    """Fetch OHLCV data and compute basic technicals using yfinance."""
    loop = asyncio.get_event_loop()
    ticker = yf.Ticker(symbol)
    hist = await loop.run_in_executor(None, partial(ticker.history, period=period))

    if hist.empty:
        raise ValueError(f"No price data found for {symbol}")

    latest = hist.iloc[-1]
    current_price = float(latest["Close"])

    # Compute technicals
    closes = hist["Close"]
    sma_20 = float(closes.rolling(20).mean().iloc[-1]) if len(closes) >= 20 else None
    sma_50 = float(closes.rolling(50).mean().iloc[-1]) if len(closes) >= 50 else None

    # RSI (14-period)
    rsi_14 = _compute_rsi(closes, 14)

    # MACD (12, 26, 9)
    macd_val, macd_signal = _compute_macd(closes)

    # Recent price history (last 20 days) for the LLM
    recent = hist.tail(20)
    price_history = [
        {
            "date": idx.strftime("%Y-%m-%d"),
            "open": round(float(row["Open"]), 2),
            "high": round(float(row["High"]), 2),
            "low": round(float(row["Low"]), 2),
            "close": round(float(row["Close"]), 2),
            "volume": int(row["Volume"]),
        }
        for idx, row in recent.iterrows()
    ]

    return StockData(
        symbol=symbol,
        current_price=round(current_price, 2),
        open=round(float(latest["Open"]), 2),
        high=round(float(latest["High"]), 2),
        low=round(float(latest["Low"]), 2),
        volume=int(latest["Volume"]),
        sma_20=round(sma_20, 2) if sma_20 is not None else None,
        sma_50=round(sma_50, 2) if sma_50 is not None else None,
        rsi_14=round(rsi_14, 2) if rsi_14 is not None else None,
        macd=round(macd_val, 4) if macd_val is not None else None,
        macd_signal=round(macd_signal, 4) if macd_signal is not None else None,
        price_history=price_history,
    )


async def get_stock_fundamentals(symbol: str) -> StockFundamentals:
    """Fetch fundamental data from yfinance."""
    loop = asyncio.get_event_loop()
    ticker = yf.Ticker(symbol)
    info = await loop.run_in_executor(None, lambda: ticker.info)

    return StockFundamentals(
        symbol=symbol,
        market_cap=info.get("marketCap"),
        pe_ratio=info.get("trailingPE"),
        forward_pe=info.get("forwardPE"),
        dividend_yield=info.get("dividendYield"),
        beta=info.get("beta"),
        fifty_two_week_high=info.get("fiftyTwoWeekHigh"),
        fifty_two_week_low=info.get("fiftyTwoWeekLow"),
        sector=info.get("sector"),
        industry=info.get("industry"),
    )


async def get_news(query: str, limit: int = 5) -> list[NewsItem]:
    """Fetch recent news headlines using Google News RSS feed."""
    url = "https://news.google.com/rss/search"
    params = {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()

        # Parse the XML RSS feed
        items = _parse_rss(resp.text, limit)
        return items
    except Exception as e:
        log.warning(f"Failed to fetch news for '{query}': {e}")
        return []


async def web_search(query: str, max_results: int = 8) -> str:
    """Perform a real web search using DuckDuckGo and return formatted results.

    Returns a text block with titles, snippets, and sources — suitable for
    inclusion in an LLM prompt as research context. Falls back to Google News
    RSS if DuckDuckGo is unavailable.
    """
    results_text = ""

    # --- Primary: DuckDuckGo text search (actual snippets) ---
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS

        loop = asyncio.get_event_loop()
        ddgs = DDGS()
        # Run synchronous search in executor to avoid blocking
        search_results = await loop.run_in_executor(
            None,
            lambda: list(ddgs.text(query, max_results=max_results, timelimit="w")),
        )

        if search_results:
            parts = []
            for r in search_results:
                title = r.get("title", "")
                body = r.get("body", "")
                source = r.get("href", "")
                parts.append(f"- [{title}] {body} (source: {source})")
            results_text = "\n".join(parts)
            log.info(f"Web search for '{query}': {len(search_results)} results from DuckDuckGo")
    except Exception as e:
        log.warning(f"DuckDuckGo search failed for '{query}': {e}")

    # --- Also get Google News headlines for recency ---
    try:
        news_items = await get_news(query, limit=5)
        if news_items:
            news_parts = [f"- [NEWS: {n.source}] {n.title} ({n.published})" for n in news_items]
            news_text = "\n".join(news_parts)
            if results_text:
                results_text = results_text + "\n\nLatest news headlines:\n" + news_text
            else:
                results_text = news_text
    except Exception:
        pass

    if not results_text:
        results_text = "No search results found. Exercise caution — you may lack current information."

    return results_text


async def get_polymarket_data(condition_id: str) -> PolymarketData:
    """Fetch market data from Polymarket's public API."""
    if not condition_id:
        raise ValueError("condition_id must not be empty")
    url = f"https://clob.polymarket.com/markets/{condition_id}"

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()

        tokens = data.get("tokens", [])
        yes_price = 0.5
        no_price = 0.5
        for token in tokens:
            outcome = token.get("outcome", "").lower()
            price = float(token.get("price", 0.5))
            if outcome == "yes":
                yes_price = price
            elif outcome == "no":
                no_price = price

        return PolymarketData(
            condition_id=condition_id,
            question=data.get("question", ""),
            yes_price=round(yes_price, 4),
            no_price=round(no_price, 4),
            volume=float(data.get("volume", 0)),
            liquidity=float(data.get("liquidity", 0)),
            end_date=data.get("end_date_iso", ""),
            description=data.get("description", ""),
            tokens=tokens,
        )
    except Exception as e:
        log.error(f"Failed to fetch Polymarket data for {condition_id}: {e}")
        raise


async def search_polymarket_markets(query: str, limit: int = 10) -> list[dict]:
    """Search Polymarket for active markets matching a query."""
    url = "https://gamma-api.polymarket.com/markets"
    params = {"_limit": limit, "active": "true", "closed": "false"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            markets = resp.json()

        # Filter by query in question text
        query_lower = query.lower()
        results = [
            {
                "condition_id": m.get("conditionId", m.get("condition_id", "")),
                "question": m.get("question", ""),
                "volume": m.get("volume", 0),
                "liquidity": m.get("liquidity", 0),
                "end_date": m.get("endDate", m.get("end_date", "")),
            }
            for m in markets
            if query_lower in m.get("question", "").lower()
        ]
        return results[:limit]
    except Exception as e:
        log.warning(f"Failed to search Polymarket markets: {e}")
        return []


def _markets_to_events(markets: list[dict]) -> list[dict]:
    """Group a flat list of markets into synthetic event dicts by parent event ID."""
    event_map: dict[str, dict] = {}
    for m in markets:
        event_list = m.get("events") or []
        if not event_list:
            synthetic_id = f"market_{m.get('id', '')}"
            event_map[synthetic_id] = {
                "id": synthetic_id,
                "title": m.get("question", ""),
                "slug": m.get("slug", ""),
                "endDate": m.get("endDate", ""),
                "markets": [m],
            }
            continue
        for ev in event_list:
            eid = str(ev.get("id", ""))
            if not eid:
                continue
            if eid not in event_map:
                event_map[eid] = {
                    "id": eid,
                    "title": ev.get("title", ""),
                    "slug": ev.get("slug", ""),
                    "endDate": ev.get("endDate", ""),
                    "markets": [],
                }
            event_map[eid]["markets"].append(m)
    return list(event_map.values())


async def _fetch_clob_markets_as_events(clob_client: object, limit: int) -> list[dict]:
    """Fetch markets via py-clob-client cursor pagination and group into events.

    The CLOB API supports proper cursor-based pagination and returns ALL active
    markets (thousands), unlike the Gamma /events endpoint which is capped at 20.
    """
    loop = asyncio.get_running_loop()
    all_markets: list[dict] = []
    cursor = "MA=="  # base64("0") — start cursor

    while len(all_markets) < limit:
        try:
            resp = await loop.run_in_executor(
                None, lambda c=cursor: clob_client.get_markets(next_cursor=c)
            )
            if isinstance(resp, dict):
                data = resp.get("data", [])
                cursor = resp.get("next_cursor", "LTE=")
            elif isinstance(resp, list):
                data = resp
                cursor = "LTE="  # no more pages
            else:
                break

            if not data:
                break

            # Convert CLOB market format to Gamma-compatible format
            for m in data:
                tokens = m.get("tokens", [])
                outcome_prices = []
                clob_token_ids = []
                for t in tokens:
                    outcome_prices.append(str(t.get("price", "0.5")))
                    clob_token_ids.append(t.get("token_id", ""))
                all_markets.append({
                    "id": m.get("condition_id", m.get("market_slug", "")),
                    "question": m.get("question", ""),
                    "conditionId": m.get("condition_id", ""),
                    "slug": m.get("market_slug", ""),
                    "endDate": m.get("end_date_iso", ""),
                    "liquidity": 0,
                    "liquidityNum": 0,
                    "outcomePrices": json_module.dumps(outcome_prices),
                    "clobTokenIds": json_module.dumps(clob_token_ids),
                    "active": m.get("active", True),
                    "closed": m.get("closed", False),
                    "acceptingOrders": m.get("accepting_orders", True),
                    "events": [],
                    "groupItemTitle": m.get("question", ""),
                })

            # LTE= means end of results
            if cursor in ("LTE=", "", None):
                break

        except Exception as e:
            log.warning(f"CLOB market fetch error at cursor {cursor}: {e}")
            break

    log.info(f"CLOB pagination fetched {len(all_markets)} markets")
    return _markets_to_events(all_markets[:limit])


async def get_all_events(limit: int = 200, active_only: bool = True, clob_client: object = None) -> list[dict]:
    """Fetch events from Polymarket.

    Tries CLOB API first (full pagination, thousands of markets) when a clob_client
    is provided. Falls back to Gamma /events (curated ~20 events) otherwise.
    """
    # If we have a CLOB client, use it for full market coverage
    if clob_client is not None:
        try:
            return await _fetch_clob_markets_as_events(clob_client, limit)
        except Exception as e:
            log.warning(f"CLOB market fetch failed, falling back to Gamma API: {e}")

    # Gamma API fallback — hard-capped at ~20 unique events regardless of params
    base_params: dict = {"_limit": 20}
    if active_only:
        base_params["active"] = "true"
        base_params["closed"] = "false"

    async def fetch_gamma(client: httpx.AsyncClient, url: str, params: dict) -> list[dict]:
        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            log.warning(f"Gamma API fetch failed ({url}): {e}")
            return []

    sort_orders = [
        ("liquidityClob", "desc"),
        ("volume24hr", "desc"),
        ("volume1wk", "desc"),
        ("endDate", "asc"),
    ]

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            results = await asyncio.gather(
                fetch_gamma(client, "https://gamma-api.polymarket.com/events", base_params),
                *[
                    fetch_gamma(client, "https://gamma-api.polymarket.com/markets",
                                {**base_params, "_order": o, "_orderDirection": d})
                    for o, d in sort_orders
                ],
            )

        all_events: list[dict] = []
        seen: set[str] = set()

        # First result is /events (already event-shaped)
        for event in results[0]:
            eid = str(event.get("id", ""))
            if eid and eid not in seen:
                seen.add(eid)
                all_events.append(event)

        # Remaining results are /markets — group into events first
        for market_list in results[1:]:
            for event in _markets_to_events(market_list):
                eid = str(event.get("id", ""))
                if eid and eid not in seen:
                    seen.add(eid)
                    all_events.append(event)

        log.info(f"Gamma API returned {len(all_events)} unique events (capped at ~20 by API)")
        return all_events[:limit]
    except Exception as e:
        log.error(f"Failed to fetch Polymarket events: {e}")
        return []


def parse_event_to_model(raw_event: dict) -> EventData:
    """Convert a raw Gamma API event response to our EventData model."""
    import json as _json

    markets = raw_event.get("markets", [])
    outcomes: list[MarketOutcome] = []

    for m in markets:
        # Primary: outcomePrices + clobTokenIds (present in /events endpoint)
        op_raw = m.get("outcomePrices")
        tid_raw = m.get("clobTokenIds")

        op = _json.loads(op_raw) if isinstance(op_raw, str) else (op_raw or [])
        tids = _json.loads(tid_raw) if isinstance(tid_raw, str) else (tid_raw or [])

        if op and len(op) >= 2:
            try:
                yes_price = float(op[0])
                no_price = float(op[1])
            except (ValueError, TypeError):
                yes_price, no_price = 0.5, 0.5
            token_id = str(tids[0]) if len(tids) > 0 else ""
            no_token_id = str(tids[1]) if len(tids) > 1 else ""
        else:
            # Fallback: tokens array (present in /markets endpoint)
            tokens = m.get("tokens", [])
            yes_price = 0.5
            no_price = 0.5
            token_id = ""
            no_token_id = ""
            for t in tokens:
                outcome_str = t.get("outcome", "").lower()
                price = float(t.get("price", 0.5))
                if outcome_str == "yes":
                    yes_price = price
                    token_id = t.get("token_id", "")
                elif outcome_str == "no":
                    no_price = price
                    no_token_id = t.get("token_id", "")

        liq = float(m.get("liquidityNum") or m.get("liquidity") or 0)

        outcomes.append(MarketOutcome(
            condition_id=m.get("conditionId", m.get("condition_id", "")),
            question=m.get("question", ""),
            outcome_label=m.get("groupItemTitle", m.get("question", "")),
            yes_price=round(yes_price, 4),
            no_price=round(no_price, 4),
            token_id=token_id,
            no_token_id=no_token_id,
            liquidity=liq,
        ))

    return EventData(
        event_id=str(raw_event.get("id", "")),
        title=raw_event.get("title", ""),
        slug=raw_event.get("slug", ""),
        outcomes=outcomes,
        end_date=raw_event.get("endDate", raw_event.get("end_date", "")),
    )


# --- Private helpers ---

def _compute_rsi(closes, period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gain.iloc[-1] / loss.iloc[-1] if loss.iloc[-1] != 0 else float("inf")
    return 100 - (100 / (1 + rs))


def _compute_macd(closes, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[float | None, float | None]:
    if len(closes) < slow + signal:
        return None, None
    ema_fast = closes.ewm(span=fast, adjust=False).mean()
    ema_slow = closes.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return float(macd_line.iloc[-1]), float(signal_line.iloc[-1])


def _parse_rss(xml_text: str, limit: int) -> list[NewsItem]:
    """Minimal RSS XML parser — avoids heavy XML dependencies."""
    import re

    items: list[NewsItem] = []
    # Find all <item> blocks
    item_blocks = re.findall(r"<item>(.*?)</item>", xml_text, re.DOTALL)

    for block in item_blocks[:limit]:
        title_match = re.search(r"<title>(.*?)</title>", block)
        source_match = re.search(r"<source.*?>(.*?)</source>", block)
        pub_match = re.search(r"<pubDate>(.*?)</pubDate>", block)
        link_match = re.search(r"<link>(.*?)</link>", block)

        title = title_match.group(1) if title_match else ""
        # Clean HTML entities
        title = title.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'").replace("&quot;", '"')

        items.append(
            NewsItem(
                title=title,
                source=source_match.group(1) if source_match else "",
                published=pub_match.group(1) if pub_match else "",
                url=link_match.group(1) if link_match else "",
            )
        )

    return items
