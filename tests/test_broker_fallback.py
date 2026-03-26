"""Tests for broker initialization fallback logic.

Verifies that when polymarket.paper=false but credentials are missing,
both main.py and app.py fall back to PaperPolymarketBroker with a warning.
"""

from __future__ import annotations

import logging

import pytest

from trading_bot.brokers.paper_polymarket import PaperPolymarketBroker
from trading_bot.config import Config


class TestMainBuildPolymarketBroker:
    """Test _build_polymarket_broker in main.py."""

    def _build(self, config: Config):
        from trading_bot.main import _build_polymarket_broker
        return _build_polymarket_broker(config)

    def test_paper_mode_returns_paper_broker(self):
        config = Config()
        config.polymarket.paper = True
        config.polymarket.paper_balance = 5000.0
        broker = self._build(config)
        assert isinstance(broker, PaperPolymarketBroker)

    def test_live_mode_without_credentials_falls_back_to_paper(self, caplog):
        config = Config()
        config.polymarket.paper = False
        config.polymarket.private_key = ""
        config.polymarket.api_key = ""
        config.polymarket.api_secret = ""
        config.polymarket.api_passphrase = ""
        config.polymarket.paper_balance = 7500.0

        with caplog.at_level(logging.WARNING):
            broker = self._build(config)

        assert isinstance(broker, PaperPolymarketBroker)
        assert "falling back to paper mode" in caplog.text.lower()

    def test_live_mode_partial_credentials_falls_back_to_paper(self, caplog):
        """Even if some credentials are set, all four are required."""
        config = Config()
        config.polymarket.paper = False
        config.polymarket.private_key = "0xabc123"
        config.polymarket.api_key = "some-key"
        config.polymarket.api_secret = ""  # Missing
        config.polymarket.api_passphrase = ""  # Missing

        with caplog.at_level(logging.WARNING):
            broker = self._build(config)

        assert isinstance(broker, PaperPolymarketBroker)


class TestAppBuildBrokers:
    """Test _build_brokers in app.py."""

    def _build(self, config: Config) -> dict:
        from trading_bot.api.app import _build_brokers
        return _build_brokers(config)

    def test_paper_mode_returns_paper_broker(self):
        config = Config()
        config.polymarket.paper = True
        brokers = self._build(config)
        assert "polymarket" in brokers
        assert isinstance(brokers["polymarket"], PaperPolymarketBroker)

    def test_live_mode_without_credentials_falls_back_to_paper(self, caplog):
        config = Config()
        config.polymarket.paper = False
        config.polymarket.private_key = ""
        config.polymarket.api_key = ""

        with caplog.at_level(logging.WARNING):
            brokers = self._build(config)

        assert "polymarket" in brokers
        assert isinstance(brokers["polymarket"], PaperPolymarketBroker)
        assert "falling back to paper mode" in caplog.text.lower()

    def test_live_mode_without_credentials_always_provides_broker(self):
        """Ensure a Polymarket broker is always present, even without credentials."""
        config = Config()
        config.polymarket.paper = False
        config.polymarket.private_key = ""
        brokers = self._build(config)
        assert "polymarket" in brokers
