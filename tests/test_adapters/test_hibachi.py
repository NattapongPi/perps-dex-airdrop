"""
Hibachi adapter tests — mocked requests.get for public API + mocked ccxt for account methods.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.exchanges.base import ExchangeAdapter
from src.exchanges.hibachi import HibachiAdapter


INVENTORY_FIXTURE = {
    "markets": [
        {
            "contract": {"underlyingSymbol": "BTC", "settlementSymbol": "USDT"},
            "info": {"volume24h": "1000000.0", "priceLatest": "73000.0"},
        },
        {
            "contract": {"underlyingSymbol": "ETH", "settlementSymbol": "USDT"},
            "info": {"volume24h": "500000.0", "priceLatest": "2250.0"},
        },
        {
            "contract": {"underlyingSymbol": "SOL", "settlementSymbol": "USDT"},
            "info": {"volume24h": "200000.0", "priceLatest": "83.0"},
        },
    ]
}


class _FakeSecrets:
    hibachi_api_key = "0xWALLET"
    hibachi_account_id = "1"
    hibachi_private_key = "0xPRIVATE"


class _FakeConfig:
    secrets = _FakeSecrets()


@pytest.fixture()
def adapter():
    with patch("src.exchanges.hibachi.requests.get") as mock_get, \
         patch("src.exchanges.hibachi.ccxt") as mock_ccxt:
        mock_get.return_value.json.return_value = INVENTORY_FIXTURE
        mock_exchange = MagicMock()
        mock_ccxt.hibachi.return_value = mock_exchange
        adp = HibachiAdapter(_FakeConfig())  # type: ignore[arg-type]
        yield adp, mock_get, mock_exchange


class TestHibachiAdapterInterface:
    def test_is_exchange_adapter(self, adapter):
        adp, _, _ = adapter
        assert isinstance(adp, ExchangeAdapter)

    def test_ccxt_id(self, adapter):
        adp, _, _ = adapter
        assert adp.CCXT_ID == "hibachi"

    def test_quote_currency(self, adapter):
        adp, _, _ = adapter
        assert adp.QUOTE_CURRENCY == "USDT"

    def test_perp_suffix(self, adapter):
        adp, _, _ = adapter
        assert adp.PERP_SUFFIX == ":USDT"


class TestHibachiGetTopCoins:
    def test_returns_ranked_by_volume(self, adapter):
        adp, mock_get, _ = adapter
        result = adp.get_top_coins(3)
        assert result == ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]

    def test_respects_n_limit(self, adapter):
        adp, mock_get, _ = adapter
        result = adp.get_top_coins(1)
        assert result == ["BTC/USDT:USDT"]

    def test_skips_missing_underlying(self, adapter):
        adp, mock_get, _ = adapter
        mock_get.return_value.json.return_value = {
            "markets": [
                {"contract": {"underlyingSymbol": "", "settlementSymbol": "USDT"}, "info": {"volume24h": "999"}},
                {"contract": {"underlyingSymbol": "ETH", "settlementSymbol": "USDT"}, "info": {"volume24h": "500"}},
            ]
        }
        result = adp.get_top_coins(5)
        assert result == ["ETH/USDT:USDT"]


class TestHibachiPing:
    def test_ping_returns_true_on_success(self, adapter):
        adp, mock_get, _ = adapter
        assert adp.ping() is True

    def test_ping_returns_false_on_network_error(self, adapter):
        adp, mock_get, _ = adapter
        mock_get.side_effect = Exception("network error")
        assert adp.ping() is False

    def test_ping_returns_false_on_bad_status(self, adapter):
        adp, mock_get, _ = adapter
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("404")
        mock_get.return_value = mock_response
        assert adp.ping() is False


class TestHibachiGetBalance:
    def test_returns_usdt_free(self, adapter):
        adp, _, mock_ex = adapter
        mock_ex.fetch_balance.return_value = {
            "USDT": {"free": 5000.0, "used": 100.0, "total": 5100.0}
        }
        assert adp.get_balance() == 5000.0

    def test_returns_zero_if_no_usdt(self, adapter):
        adp, _, mock_ex = adapter
        mock_ex.fetch_balance.return_value = {}
        assert adp.get_balance() == 0.0


class TestHibachiGetOhlcv:
    def test_returns_dataframe(self, adapter):
        adp, _, mock_ex = adapter
        mock_ex.fetch_ohlcv.return_value = [
            [1_700_000_000_000, 100.0, 105.0, 98.0, 102.0, 500.0],
        ]
        import pandas as pd
        df = adp.get_ohlcv("BTC/USDT:USDT", "1h", 1)
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert len(df) == 1


class TestHibachiGetPositions:
    def test_filters_zero_size(self, adapter):
        adp, _, mock_ex = adapter
        mock_ex.fetch_positions.return_value = [
            {"symbol": "BTC/USDT:USDT", "contracts": 0, "side": "long", "entryPrice": 30000},
            {"symbol": "ETH/USDT:USDT", "contracts": 1.5, "side": "long", "entryPrice": 2000},
        ]
        positions = adp.get_open_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "ETH/USDT:USDT"


class TestHibachiCloseAllPositions:
    def test_closes_long_with_sell_reduce_only(self, adapter):
        adp, _, mock_ex = adapter
        mock_ex.fetch_positions.return_value = [
            {"symbol": "BTC/USDT:USDT", "contracts": 1.0, "side": "long", "entryPrice": 70000},
        ]
        closed = adp.close_all_positions()
        assert closed == 1
        mock_ex.create_order.assert_called_once_with(
            symbol="BTC/USDT:USDT",
            type="market",
            side="sell",
            amount=1.0,
            params={"reduceOnly": True},
        )

    def test_closes_short_with_buy_reduce_only(self, adapter):
        adp, _, mock_ex = adapter
        mock_ex.fetch_positions.return_value = [
            {"symbol": "ETH/USDT:USDT", "contracts": 2.0, "side": "short", "entryPrice": 2000},
        ]
        closed = adp.close_all_positions()
        assert closed == 1
        mock_ex.create_order.assert_called_once_with(
            symbol="ETH/USDT:USDT",
            type="market",
            side="buy",
            amount=2.0,
            params={"reduceOnly": True},
        )

    def test_returns_zero_when_no_positions(self, adapter):
        adp, _, mock_ex = adapter
        mock_ex.fetch_positions.return_value = []
        closed = adp.close_all_positions()
        assert closed == 0
        mock_ex.create_order.assert_not_called()

    def test_counts_multiple_positions(self, adapter):
        adp, _, mock_ex = adapter
        mock_ex.fetch_positions.return_value = [
            {"symbol": "BTC/USDT:USDT", "contracts": 1.0, "side": "long", "entryPrice": 70000},
            {"symbol": "ETH/USDT:USDT", "contracts": 2.0, "side": "short", "entryPrice": 2000},
        ]
        closed = adp.close_all_positions()
        assert closed == 2
        assert mock_ex.create_order.call_count == 2
