"""Tests for stock scorer pure computation functions."""

from __future__ import annotations

import pytest

from trading_bot.models import MarketRegime, StockData, StockFundamentals
from trading_bot.strategies.stock_scorer import (
    compute_fundamental_score,
    compute_technical_score,
    detect_regime,
)


def _make_stock_data(**kwargs) -> StockData:
    defaults = {
        "symbol": "TEST",
        "current_price": 100.0,
        "open": 99.0,
        "high": 102.0,
        "low": 98.0,
        "volume": 1000000,
    }
    defaults.update(kwargs)
    return StockData(**defaults)


class TestTechnicalScore:
    def test_bullish_trend(self):
        """Price > SMA20 > SMA50 → strong bullish signal."""
        data = _make_stock_data(
            current_price=110.0, sma_20=105.0, sma_50=100.0,
            rsi_14=55.0, macd=0.5, macd_signal=0.3,
        )
        score = compute_technical_score("TEST", data)
        assert score.sma_trend == 1.0
        assert score.composite > 0

    def test_bearish_trend(self):
        """Price < SMA20 < SMA50 → strong bearish signal."""
        data = _make_stock_data(
            current_price=90.0, sma_20=95.0, sma_50=100.0,
            rsi_14=55.0, macd=-0.5, macd_signal=-0.3,
        )
        score = compute_technical_score("TEST", data)
        assert score.sma_trend == -1.0
        assert score.composite < 0

    def test_oversold_rsi(self):
        """RSI < 30 → bullish signal."""
        data = _make_stock_data(rsi_14=25.0)
        score = compute_technical_score("TEST", data)
        assert score.rsi_signal == 1.0

    def test_overbought_rsi(self):
        """RSI > 70 → bearish signal."""
        data = _make_stock_data(rsi_14=75.0)
        score = compute_technical_score("TEST", data)
        assert score.rsi_signal == -1.0

    def test_positive_momentum(self):
        """Price increased over period → positive momentum."""
        data = _make_stock_data(
            current_price=120.0,
            price_history=[
                {"close": 100.0, "date": "2024-01-01"},
                {"close": 120.0, "date": "2024-02-01"},
            ],
        )
        score = compute_technical_score("TEST", data)
        assert score.momentum_score > 0

    def test_composite_bounded(self):
        """Composite score is between -1 and 1."""
        data = _make_stock_data(
            sma_20=50.0, sma_50=60.0, rsi_14=80.0,
            macd=-2.0, macd_signal=0.0,
        )
        score = compute_technical_score("TEST", data)
        assert -1.0 <= score.composite <= 1.0


class TestFundamentalScore:
    def test_low_pe_bullish(self):
        """PE < 15 → value signal."""
        fund = StockFundamentals(symbol="TEST", pe_ratio=12.0)
        score = compute_fundamental_score("TEST", fund)
        assert score.pe_vs_sector > 0

    def test_high_pe_bearish(self):
        """PE > 35 → overvalued signal."""
        fund = StockFundamentals(symbol="TEST", pe_ratio=40.0)
        score = compute_fundamental_score("TEST", fund)
        assert score.pe_vs_sector < 0

    def test_growth_signal(self):
        """Forward PE < trailing PE → expected earnings growth."""
        fund = StockFundamentals(symbol="TEST", pe_ratio=25.0, forward_pe=18.0)
        score = compute_fundamental_score("TEST", fund)
        assert score.growth_score > 0

    def test_quality_low_beta(self):
        """Low beta → quality signal."""
        fund = StockFundamentals(symbol="TEST", beta=0.6)
        score = compute_fundamental_score("TEST", fund)
        assert score.quality_score > 0

    def test_composite_bounded(self):
        """Composite stays in [-1, 1]."""
        fund = StockFundamentals(symbol="TEST", pe_ratio=5.0, forward_pe=3.0, beta=0.5, dividend_yield=0.05)
        score = compute_fundamental_score("TEST", fund)
        assert -1.0 <= score.composite <= 1.0


class TestRegimeDetection:
    def test_trending_up(self):
        """Strong uptrend → TRENDING_UP."""
        prices = [{"close": 100 + i * 2} for i in range(20)]
        data = _make_stock_data(
            current_price=140.0, sma_20=125.0,
            price_history=prices,
        )
        regime = detect_regime(data)
        assert regime == MarketRegime.TRENDING_UP

    def test_trending_down(self):
        """Strong downtrend → TRENDING_DOWN."""
        prices = [{"close": 100 - i * 2} for i in range(20)]
        data = _make_stock_data(
            current_price=60.0, sma_20=75.0,
            price_history=prices,
        )
        regime = detect_regime(data)
        assert regime == MarketRegime.TRENDING_DOWN

    def test_insufficient_data(self):
        """< 10 data points → LOW_VOLATILITY default."""
        data = _make_stock_data(price_history=[{"close": 100}] * 5)
        regime = detect_regime(data)
        assert regime == MarketRegime.LOW_VOLATILITY

    def test_high_volatility(self):
        """Large swings → HIGH_VOLATILITY."""
        prices = [{"close": 100 + (10 if i % 2 == 0 else -10)} for i in range(20)]
        data = _make_stock_data(current_price=100.0, price_history=prices)
        regime = detect_regime(data)
        assert regime in (MarketRegime.HIGH_VOLATILITY, MarketRegime.MEAN_REVERTING)
