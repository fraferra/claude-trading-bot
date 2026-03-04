from __future__ import annotations

import json

import anthropic

from trading_bot.analysis.market_data import (
    get_news,
    get_polymarket_data,
    get_stock_data,
    get_stock_fundamentals,
)
from trading_bot.analysis.prompts import (
    POLYMARKET_ANALYSIS_SYSTEM,
    POLYMARKET_ANALYSIS_USER,
    STOCK_ANALYSIS_SYSTEM,
    STOCK_ANALYSIS_USER,
)
from trading_bot.config import Config
from trading_bot.models import (
    Platform,
    PolymarketData,
    PortfolioSummary,
    Position,
    StockData,
    StockFundamentals,
    TradeDecision,
)
from trading_bot.utils.logging import log


class LLMAnalyst:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        self.model = config.llm.model
        self.max_tokens = config.llm.max_tokens

    async def analyze_stock(
        self,
        symbol: str,
        portfolio: PortfolioSummary | None = None,
    ) -> TradeDecision:
        """Analyze a stock and return a trading decision."""
        log.info(f"Analyzing stock: {symbol}")

        # Gather data concurrently
        import asyncio

        stock_data, fundamentals, news = await asyncio.gather(
            get_stock_data(symbol, self.config.stocks.default_period),
            get_stock_fundamentals(symbol),
            get_news(f"{symbol} stock", limit=5),
        )

        # Find current position for this symbol
        current_pos = "None"
        available_cash = portfolio.cash if portfolio else 0.0
        if portfolio:
            for pos in portfolio.positions:
                if pos.symbol == symbol:
                    current_pos = f"{pos.quantity} shares @ ${pos.avg_entry_price:.2f} (P&L: ${pos.unrealized_pnl:.2f})"
                    break

        # Build the prompt
        news_text = "\n".join(
            f"- [{n.source}] {n.title}" for n in news
        ) if news else "No recent news found."

        price_history_text = "\n".join(
            f"  {d['date']}: O=${d['open']} H=${d['high']} L=${d['low']} C=${d['close']} V={d['volume']:,}"
            for d in stock_data.price_history[-10:]  # Last 10 days to keep prompt concise
        )

        user_msg = STOCK_ANALYSIS_USER.format(
            symbol=symbol,
            current_price=stock_data.current_price,
            sma_20=stock_data.sma_20 or "N/A",
            sma_50=stock_data.sma_50 or "N/A",
            rsi_14=stock_data.rsi_14 or "N/A",
            macd=stock_data.macd or "N/A",
            macd_signal=stock_data.macd_signal or "N/A",
            open=stock_data.open,
            high=stock_data.high,
            low=stock_data.low,
            volume=f"{stock_data.volume:,}",
            market_cap=_format_large_number(fundamentals.market_cap),
            pe_ratio=fundamentals.pe_ratio or "N/A",
            forward_pe=fundamentals.forward_pe or "N/A",
            sector=fundamentals.sector or "N/A",
            fifty_two_week_low=fundamentals.fifty_two_week_low or "N/A",
            fifty_two_week_high=fundamentals.fifty_two_week_high or "N/A",
            price_history=price_history_text,
            news=news_text,
            current_position=current_pos,
            available_cash=f"{available_cash:,.2f}",
        )

        return await self._call_llm(STOCK_ANALYSIS_SYSTEM, user_msg, symbol)

    async def analyze_polymarket(
        self,
        condition_id: str,
        portfolio: PortfolioSummary | None = None,
    ) -> TradeDecision:
        """Analyze a Polymarket market and return a trading decision."""
        log.info(f"Analyzing Polymarket market: {condition_id}")

        import asyncio

        market_data, news = await asyncio.gather(
            get_polymarket_data(condition_id),
            get_news(condition_id, limit=5),  # Will be refined based on question
        )

        # Also search news for the market question
        question_news = await get_news(market_data.question[:80], limit=5)
        all_news = news + [n for n in question_news if n.title not in {n2.title for n2 in news}]

        current_pos = "None"
        available_balance = portfolio.cash if portfolio else 0.0
        if portfolio:
            for pos in portfolio.positions:
                if pos.symbol == condition_id:
                    current_pos = f"{pos.quantity} shares @ ${pos.avg_entry_price:.2f}"
                    break

        news_text = "\n".join(
            f"- [{n.source}] {n.title}" for n in all_news[:8]
        ) if all_news else "No recent news found."

        user_msg = POLYMARKET_ANALYSIS_USER.format(
            question=market_data.question,
            description=market_data.description[:500] if market_data.description else "No description available.",
            yes_price=market_data.yes_price,
            no_price=market_data.no_price,
            yes_prob=round(market_data.yes_price * 100, 1),
            no_prob=round(market_data.no_price * 100, 1),
            volume=f"{market_data.volume:,.0f}",
            liquidity=f"{market_data.liquidity:,.0f}",
            end_date=market_data.end_date or "Unknown",
            news=news_text,
            current_position=current_pos,
            available_balance=f"{available_balance:,.2f}",
        )

        return await self._call_llm(POLYMARKET_ANALYSIS_SYSTEM, user_msg, condition_id)

    async def _call_llm(
        self, system: str, user_msg: str, symbol: str, model_override: str | None = None
    ) -> TradeDecision:
        """Call Claude API and parse the response into a TradeDecision."""
        import asyncio

        loop = asyncio.get_event_loop()
        model = model_override or self.model

        log.info(f"Calling Claude ({model}) for analysis...")
        response = await loop.run_in_executor(
            None,
            lambda: self.client.messages.create(
                model=model,
                max_tokens=self.max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_msg}],
            ),
        )

        raw_text = response.content[0].text.strip()
        log.debug(f"LLM raw response: {raw_text}")

        # Parse JSON from the response (handle potential markdown wrapping)
        json_str = raw_text
        if json_str.startswith("```"):
            # Strip markdown code fences
            lines = json_str.split("\n")
            json_str = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            log.error(f"Failed to parse LLM response as JSON: {e}")
            log.error(f"Raw response: {raw_text}")
            # Return a conservative HOLD decision
            return TradeDecision(
                action="hold",
                symbol=symbol,
                confidence=0.0,
                reasoning=f"Failed to parse LLM response: {e}",
            )

        # Ensure symbol is set
        data.setdefault("symbol", symbol)
        return TradeDecision(**data)

    async def _call_llm_raw(self, system: str, user_msg: str, model_override: str | None = None) -> str:
        """Call Claude API and return the raw text response (no parsing)."""
        import asyncio

        loop = asyncio.get_event_loop()
        model = model_override or self.model

        log.info(f"Calling Claude ({model}) for raw analysis...")
        response = await loop.run_in_executor(
            None,
            lambda: self.client.messages.create(
                model=model,
                max_tokens=self.max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_msg}],
            ),
        )

        return response.content[0].text.strip()


def _format_large_number(n: float | None) -> str:
    if n is None:
        return "N/A"
    if n >= 1e12:
        return f"{n / 1e12:.1f}T"
    if n >= 1e9:
        return f"{n / 1e9:.1f}B"
    if n >= 1e6:
        return f"{n / 1e6:.1f}M"
    return f"{n:,.0f}"
