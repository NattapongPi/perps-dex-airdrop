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

    def test_uses_markprice_when_entryprice_missing(self, adapter, caplog):
        import logging
        adp, _, mock_ex = adapter
        mock_ex.fetch_positions.return_value = [
            {"symbol": "BTC/USDT:USDT", "contracts": 1.0, "side": "long", "markPrice": 70000},
        ]
        with caplog.at_level(logging.ERROR):
            positions = adp.get_open_positions()
        assert len(positions) == 1
        assert positions[0].entry_price == 70000.0
        assert "missing entryPrice" in caplog.text

    def test_skips_when_entryprice_and_markprice_missing(self, adapter, caplog):
        import logging
        adp, _, mock_ex = adapter
        mock_ex.fetch_positions.return_value = [
            {"symbol": "BTC/USDT:USDT", "contracts": 1.0, "side": "long"},
        ]
        with caplog.at_level(logging.ERROR):
            positions = adp.get_open_positions()
        assert len(positions) == 0
        assert "no valid entry price" in caplog.text

    def test_falls_back_to_raw_info_fields(self, adapter):
        adp, _, mock_ex = adapter
        mock_ex.fetch_positions.return_value = [
            {
                "symbol": "ETH/USDT:USDT",
                "contracts": 2.0,
                "side": "short",
                "info": {"avgEntryPrice": "2100.5"},
            },
        ]
        positions = adp.get_open_positions()
        assert len(positions) == 1
        assert positions[0].entry_price == 2100.5


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


class TestHibachiPriceToTick:
    def test_rounds_to_tick_size(self, adapter):
        adp, _, mock_ex = adapter
        mock_ex.market.return_value = {"info": {"tickSize": "0.00001"}}
        assert adp._price_to_tick("XRP/USDT:USDT", 1.3958574) == "1.39586"

    def test_rounds_btc_to_ten_cents(self, adapter):
        adp, _, mock_ex = adapter
        mock_ex.market.return_value = {"info": {"tickSize": "0.1"}}
        assert adp._price_to_tick("BTC/USDT:USDT", 78546.12345) == "78546.1"

    def test_fallback_when_no_tick_size(self, adapter):
        adp, _, mock_ex = adapter
        mock_ex.market.return_value = {"info": {}}
        assert adp._price_to_tick("BTC/USDT:USDT", 78546.12345) == "78546.12345"


class TestHibachiOpenPriceFallback:
    def test_uses_openPrice_when_unified_entryPrice_missing(self, adapter):
        adp, _, mock_ex = adapter
        mock_ex.fetch_positions.return_value = [
            {
                "symbol": "ETH/USDT:USDT",
                "contracts": 1.5,
                "side": "long",
                "entryPrice": None,
                "info": {"openPrice": "2354.479339"},
            },
        ]
        positions = adp.get_open_positions()
        assert len(positions) == 1
        assert positions[0].entry_price == 2354.479339

    def test_uses_info_markPrice_when_both_unified_fields_missing(self, adapter, caplog):
        import logging
        adp, _, mock_ex = adapter
        mock_ex.fetch_positions.return_value = [
            {
                "symbol": "ETH/USDT:USDT",
                "contracts": 1.5,
                "side": "long",
                "entryPrice": None,
                "markPrice": None,
                "info": {"markPrice": "2374.357506"},
            },
        ]
        with caplog.at_level(logging.ERROR):
            positions = adp.get_open_positions()
        assert len(positions) == 1
        assert positions[0].entry_price == 2374.357506
        assert "missing entryPrice" in caplog.text


class TestHibachiSideFallback:
    def test_uses_info_direction_when_side_missing(self, adapter):
        adp, _, mock_ex = adapter
        mock_ex.fetch_positions.return_value = [
            {
                "symbol": "BTC/USDT:USDT",
                "contracts": 1.0,
                "side": None,
                "entryPrice": 70000,
                "info": {"direction": "Long"},
            },
        ]
        positions = adp.get_open_positions()
        assert len(positions) == 1
        assert positions[0].side == "long"

    def test_short_from_info_direction(self, adapter):
        adp, _, mock_ex = adapter
        mock_ex.fetch_positions.return_value = [
            {
                "symbol": "BTC/USDT:USDT",
                "contracts": 1.0,
                "side": None,
                "entryPrice": 70000,
                "info": {"direction": "Short"},
            },
        ]
        positions = adp.get_open_positions()
        assert len(positions) == 1
        assert positions[0].side == "short"


class TestHibachiPriceToTickScientificNotation:
    def test_no_scientific_notation(self, adapter):
        adp, _, mock_ex = adapter
        mock_ex.market.return_value = {"info": {"tickSize": "0.00001"}}
        result = adp._price_to_tick("XRP/USDT:USDT", 0.00003)
        assert "E" not in result
        assert result == "0.00003"


class TestHibachiCancelOrphanOrders:
    def test_cancels_orphans_for_symbols_without_position(self, adapter):
        adp, _, mock_ex = adapter
        mock_ex.fetch_open_orders.return_value = [
            {"symbol": "BTC/USDT:USDT", "id": "order1", "type": "limit", "side": "sell"},
            {"symbol": "ETH/USDT:USDT", "id": "order2", "type": "limit", "side": "sell"},
        ]
        from src.exchanges.base import Position
        open_positions = [Position(symbol="ETH/USDT:USDT", side="long", size=1.0, entry_price=2000)]
        cancelled = adp.cancel_orphan_orders(open_positions)
        assert cancelled == 1
        mock_ex.cancel_order.assert_called_once_with("order1", "BTC/USDT:USDT")

    def test_keeps_orders_for_symbols_with_position(self, adapter):
        adp, _, mock_ex = adapter
        mock_ex.fetch_open_orders.return_value = [
            {"symbol": "BTC/USDT:USDT", "id": "order1", "type": "limit", "side": "sell"},
        ]
        from src.exchanges.base import Position
        open_positions = [Position(symbol="BTC/USDT:USDT", side="long", size=1.0, entry_price=70000)]
        cancelled = adp.cancel_orphan_orders(open_positions)
        assert cancelled == 0
        mock_ex.cancel_order.assert_not_called()

    def test_returns_zero_on_fetch_open_orders_failure(self, adapter):
        adp, _, mock_ex = adapter
        mock_ex.fetch_open_orders.side_effect = Exception("network down")
        from src.exchanges.base import Position
        open_positions = [Position(symbol="BTC/USDT:USDT", side="long", size=1.0, entry_price=70000)]
        cancelled = adp.cancel_orphan_orders(open_positions)
        assert cancelled == 0

    def test_skips_malformed_orders(self, adapter):
        adp, _, mock_ex = adapter
        mock_ex.fetch_open_orders.return_value = [
            {"symbol": None, "id": "order1", "type": "limit", "side": "sell"},
            {"symbol": "BTC/USDT:USDT", "id": None, "type": "limit", "side": "sell"},
        ]
        from src.exchanges.base import Position
        open_positions = []
        cancelled = adp.cancel_orphan_orders(open_positions)
        assert cancelled == 0
        mock_ex.cancel_order.assert_not_called()


class TestHibachiPlaceOrder:
    def test_place_order_success(self, adapter):
        adp, _, mock_ex = adapter
        mock_ex.create_order.side_effect = [
            {"id": "entry123", "status": "pending"},
            {"id": "tp456"},
            {"id": "sl789"},
        ]
        mock_ex.fetch_order.return_value = {
            "id": "entry123",
            "average": 50000.0,
            "filled": 0.1,
            "status": "closed",
        }
        mock_ex.market.return_value = {"info": {"tickSize": "0.1"}}
        result = adp.place_order("BTC/USDT:USDT", "buy", 0.1, 0.04, 0.02)
        assert result.order_id == "entry123"
        assert result.entry_price == 50000.0
        assert result.size == 0.1
        assert result.status == "closed"
        assert mock_ex.create_order.call_count == 3

    def test_place_order_cancels_entry_when_price_resolution_fails(self, adapter):
        adp, _, mock_ex = adapter
        mock_ex.create_order.return_value = {"id": "entry123", "status": "pending"}
        mock_ex.fetch_order.side_effect = Exception("timeout")
        mock_ex.fetch_my_trades.side_effect = Exception("timeout")
        from src.exchanges.base import OrderResult
        with pytest.raises(RuntimeError, match="Could not determine entry price"):
            adp.place_order("BTC/USDT:USDT", "buy", 0.1, 0.04, 0.02)
        mock_ex.cancel_order.assert_called_once_with("entry123", "BTC/USDT:USDT")
