"""
Hyperliquid adapter tests — mocked CCXT, no live API calls.

The mock patches `src.exchanges.ccxt_base.ccxt` because CcxtAdapter.__init__
is where the exchange is instantiated (HyperliquidAdapter just calls super()).
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.exchanges.base import ExchangeAdapter, Position
from src.exchanges.hyperliquid import HyperliquidAdapter


class _FakeSecrets:
    hyperliquid_api_key = "0xWALLET"
    hyperliquid_api_secret = "0xPRIVATE"
    hyperliquid_builder_code = "0xBUILDER"


class _FakeConfig:
    secrets = _FakeSecrets()


@pytest.fixture()
def adapter():
    # Patch ccxt in the base module — that's where getattr(ccxt, CCXT_ID) is called
    with patch("src.exchanges.ccxt_base.ccxt") as mock_ccxt:
        mock_exchange = MagicMock()
        mock_exchange.options = {}  # real dict so builder_code gets stored
        mock_ccxt.hyperliquid.return_value = mock_exchange
        adp = HyperliquidAdapter(_FakeConfig())  # type: ignore[arg-type]
        yield adp, mock_exchange


class TestHyperliquidAdapterInterface:
    def test_is_exchange_adapter(self, adapter):
        adp, _ = adapter
        assert isinstance(adp, ExchangeAdapter)

    def test_stores_builder_code(self, adapter):
        adp, _ = adapter
        assert adp._exchange.options["broker"] == "0xBUILDER"

    def test_ccxt_id(self, adapter):
        adp, _ = adapter
        assert adp.CCXT_ID == "hyperliquid"

    def test_quote_currency(self, adapter):
        adp, _ = adapter
        assert adp.QUOTE_CURRENCY == "USDC"


class TestHyperliquidGetTopCoins:
    def test_returns_top_n_by_oi(self, adapter):
        adp, mock_ex = adapter
        mock_ex.fetch_tickers.return_value = {
            "BTC:USDC": {"openInterestValue": 1_000_000},
            "ETH:USDC": {"openInterestValue": 500_000},
            "SOL:USDC": {"openInterestValue": 200_000},
        }
        result = adp.get_top_coins(2)
        assert result == ["BTC:USDC", "ETH:USDC"]

    def test_falls_back_to_volume_when_no_oi(self, adapter):
        adp, mock_ex = adapter
        mock_ex.fetch_tickers.return_value = {
            "BTC:USDC": {"openInterestValue": None, "quoteVolume": 1_000_000},
            "ETH:USDC": {"openInterestValue": None, "quoteVolume": 500_000},
        }
        result = adp.get_top_coins(2)
        assert result == ["BTC:USDC", "ETH:USDC"]

    def test_filters_non_perp(self, adapter):
        adp, mock_ex = adapter
        mock_ex.fetch_tickers.return_value = {
            "BTC:USDC": {"openInterestValue": 1_000_000},
            "BTC/USDC": {"openInterestValue": 9_000_000},  # spot — should be excluded
        }
        result = adp.get_top_coins(5)
        assert "BTC/USDC" not in result
        assert "BTC:USDC" in result

    def test_returns_at_most_n(self, adapter):
        adp, mock_ex = adapter
        mock_ex.fetch_tickers.return_value = {
            f"COIN{i}:USDC": {"openInterestValue": i * 1000}
            for i in range(10)
        }
        result = adp.get_top_coins(3)
        assert len(result) == 3


class TestHyperliquidGetOhlcv:
    def test_returns_correct_dataframe(self, adapter):
        adp, mock_ex = adapter
        mock_ex.fetch_ohlcv.return_value = [
            [1_700_000_000_000, 100.0, 105.0, 98.0, 102.0, 500.0],
            [1_700_003_600_000, 102.0, 107.0, 101.0, 106.0, 600.0],
        ]
        df = adp.get_ohlcv("BTC:USDC", "1h", 2)
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert len(df) == 2
        assert df["close"].iloc[-1] == 106.0

    def test_index_is_datetime(self, adapter):
        adp, mock_ex = adapter
        mock_ex.fetch_ohlcv.return_value = [
            [1_700_000_000_000, 100.0, 105.0, 98.0, 102.0, 500.0],
        ]
        df = adp.get_ohlcv("BTC:USDC", "1h", 1)
        assert isinstance(df.index, pd.DatetimeIndex)


class TestHyperliquidGetPositions:
    def test_filters_zero_size(self, adapter):
        adp, mock_ex = adapter
        mock_ex.fetch_positions.return_value = [
            {"symbol": "BTC:USDC", "contracts": 0, "side": "long", "entryPrice": 30000},
            {"symbol": "ETH:USDC", "contracts": 1.5, "side": "long", "entryPrice": 2000},
        ]
        positions = adp.get_open_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "ETH:USDC"

    def test_maps_to_position_dataclass(self, adapter):
        adp, mock_ex = adapter
        mock_ex.fetch_positions.return_value = [
            {"symbol": "BTC:USDC", "contracts": 0.5, "side": "long", "entryPrice": 30000},
        ]
        positions = adp.get_open_positions()
        p = positions[0]
        assert isinstance(p, Position)
        assert p.side == "long"
        assert p.size == 0.5
        assert p.entry_price == 30000


class TestHyperliquidGetBalance:
    def test_returns_usdc_free(self, adapter):
        adp, mock_ex = adapter
        mock_ex.fetch_balance.return_value = {
            "USDC": {"free": 5000.0, "used": 100.0, "total": 5100.0}
        }
        assert adp.get_balance() == 5000.0

    def test_returns_zero_if_no_usdc(self, adapter):
        adp, mock_ex = adapter
        mock_ex.fetch_balance.return_value = {}
        assert adp.get_balance() == 0.0


class TestHyperliquidPlaceOrder:
    def test_returns_order_result(self, adapter):
        adp, mock_ex = adapter
        mock_ex.create_order.return_value = {
            "id": "12345",
            "average": 30000.0,
            "status": "closed",
        }
        result = adp.place_order("BTC:USDC", "buy", 0.01, 0.04, 0.02)
        assert result.order_id == "12345"
        assert result.entry_price == 30000.0
        assert result.tp_price == pytest.approx(30000.0 * 1.04)
        assert result.sl_price == pytest.approx(30000.0 * 0.98)

    def test_places_three_orders(self, adapter):
        adp, mock_ex = adapter
        mock_ex.create_order.return_value = {
            "id": "1", "average": 30000.0, "status": "closed"
        }
        adp.place_order("BTC:USDC", "buy", 0.01, 0.04, 0.02)
        # entry + TP + SL = 3 calls
        assert mock_ex.create_order.call_count == 3


class TestHyperliquidPing:
    def test_ping_returns_true_on_success(self, adapter):
        adp, mock_ex = adapter
        mock_ex.fetch_tickers.return_value = {}
        assert adp.ping() is True

    def test_ping_returns_false_on_failure(self, adapter):
        adp, mock_ex = adapter
        mock_ex.fetch_tickers.side_effect = RuntimeError("network error")
        assert adp.ping() is False
