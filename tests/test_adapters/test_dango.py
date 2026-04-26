"""
Dango adapter tests — mocked GraphQL, no live API calls.
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.exchanges.base import ExchangeAdapter, Position
from src.exchanges.dango import DangoAdapter


class _FakeSecrets:
    dango_wallet_address = "0xAbCdEf1234567890"
    dango_private_key = "0x" + "11" * 32


class _FakeConfig:
    secrets = _FakeSecrets()


def _make_user_info():
    """Return a standard user info dict matching the account factory response."""
    return {
        "index": 7,
        "name": "test_user",
        "accounts": {"0": "0xaaaa1111bbbb2222cccc3333dddd4444eeee5555"},
        "keys": {"AABBCCDD": {"ethereum": "0xabcdef1234567890"}},
    }


def _default_side_effect(gql: str, variables: dict | None = None):
    if "users(publicKeyHash" in gql:
        return {"users": {"nodes": [{"userIndex": 7}]}}
    if "user:" in gql and "index:" in gql:
        return {"queryApp": {"wasm_smart": _make_user_info()}}
    if "seen_nonces" in gql:
        return {"queryApp": [10, 11, 12]}
    if "simulate" in gql:
        return {"simulate": {"gas_used": 100000, "gas_limit": None}}
    if "broadcastTxSync" in gql:
        return {"broadcastTxSync": {"txHash": "abc123"}}
    if "perpsPairStats" in gql and "pairId" in str(variables or {}):
        return {"perpsPairStats": {"currentPrice": "30000"}}
    if "user_state" in gql:
        return {"queryApp": None}
    if "allPerpsPairStats" in gql:
        return {
            "allPerpsPairStats": [
                {"pairId": "perp/btcusd", "volume24H": "1000000"},
                {"pairId": "perp/ethusd", "volume24H": "500000"},
            ]
        }
    if "perpsCandles" in gql:
        return {
            "perpsCandles": {
                "nodes": [
                    {
                        "open": "100.0",
                        "high": "105.0",
                        "low": "98.0",
                        "close": "102.0",
                        "volume": "500.0",
                        "timeStartUnix": "1700000000000",
                    },
                ]
            }
        }
    return {}


@pytest.fixture()
def adapter():
    with patch("src.exchanges.dango._GQL") as mock_gql_cls:
        mock_gql = MagicMock()
        mock_gql_cls.return_value = mock_gql
        mock_gql.query.side_effect = _default_side_effect
        mock_gql.mutate.side_effect = _default_side_effect
        adp = DangoAdapter(_FakeConfig())  # type: ignore[arg-type]
        yield adp, mock_gql


class TestDangoAdapterInterface:
    def test_is_exchange_adapter(self, adapter):
        adp, _ = adapter
        assert isinstance(adp, ExchangeAdapter)

    def test_stores_wallet_address(self, adapter):
        adp, _ = adapter
        assert adp._address == "0xAbCdEf1234567890"

    def test_key_hash_is_uppercase_hex(self, adapter):
        adp, _ = adapter
        assert adp._key_hash.isupper()
        assert all(c in "0123456789ABCDEF" for c in adp._key_hash)

    def test_resolves_account_address(self, adapter):
        adp, _ = adapter
        addr = adp._resolve_account_address()
        assert addr == "0xaaaa1111bbbb2222cccc3333dddd4444eeee5555"

    def test_resolves_user_index(self, adapter):
        adp, _ = adapter
        idx = adp._resolve_user_index()
        assert idx == 7


class TestDangoPing:
    def test_ping_returns_true_on_success(self, adapter):
        adp, _ = adapter
        assert adp.ping() is True

    def test_ping_returns_false_when_not_registered(self, adapter):
        adp, mock_gql = adapter

        def _fail(gql, variables=None):
            if "users(publicKeyHash" in gql:
                return {"users": {"nodes": []}}
            return {}

        mock_gql.query.side_effect = _fail
        assert adp.ping() is False

    def test_ping_returns_false_on_network_error(self, adapter):
        adp, mock_gql = adapter
        mock_gql.query.side_effect = RuntimeError("network error")
        assert adp.ping() is False


class TestDangoGetTopCoins:
    def test_returns_top_n_by_volume(self, adapter):
        adp, _ = adapter
        result = adp.get_top_coins(2)
        assert result == ["perp/btcusd", "perp/ethusd"]

    def test_filters_non_perp(self, adapter):
        adp, mock_gql = adapter
        mock_gql.query.return_value = {
            "allPerpsPairStats": [
                {"pairId": "perp/btcusd", "volume24H": "1000000"},
                {"pairId": "spot/ethusd", "volume24H": "9000000"},
            ]
        }
        result = adp.get_top_coins(5)
        assert "spot/ethusd" not in result
        assert "perp/btcusd" in result

    def test_returns_at_most_n(self, adapter):
        adp, mock_gql = adapter

        def _side_effect(gql, variables=None):
            if "allPerpsPairStats" in gql:
                return {
                    "allPerpsPairStats": [
                        {"pairId": f"perp/coin{i}", "volume24H": str(i * 1000)}
                        for i in range(10)
                    ]
                }
            return _default_side_effect(gql, variables)

        mock_gql.query.side_effect = _side_effect
        result = adp.get_top_coins(3)
        assert len(result) == 3


class TestDangoGetOhlcv:
    def test_returns_correct_dataframe(self, adapter):
        adp, _ = adapter
        df = adp.get_ohlcv("perp/btcusd", "1h", 1)
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert len(df) == 1
        assert df["close"].iloc[-1] == 102.0

    def test_index_is_datetime(self, adapter):
        adp, _ = adapter
        df = adp.get_ohlcv("perp/btcusd", "1h", 1)
        assert isinstance(df.index, pd.DatetimeIndex)

    def test_rejects_bad_timeframe(self, adapter):
        adp, _ = adapter
        with pytest.raises(ValueError, match="Unsupported timeframe"):
            adp.get_ohlcv("perp/btcusd", "bad", 10)


class TestDangoGetPositions:
    def test_returns_empty_when_not_registered(self, adapter):
        adp, mock_gql = adapter

        def _fail(gql, variables=None):
            if "users(publicKeyHash" in gql:
                return {"users": {"nodes": []}}
            return {}

        mock_gql.query.side_effect = _fail
        positions = adp.get_open_positions()
        assert positions == []

    def test_filters_zero_size(self, adapter):
        adp, mock_gql = adapter

        def _side_effect(gql, variables=None):
            if "user_state" in gql:
                return {
                    "queryApp": {"wasm_smart": '{"positions": {"perp/btcusd": {"size": "0", "entry_price": "30000"}, "perp/ethusd": {"size": "1.5", "entry_price": "2000"}}}'}
                }
            return _default_side_effect(gql, variables)

        mock_gql.query.side_effect = _side_effect
        positions = adp.get_open_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "perp/ethusd"

    def test_maps_to_position_dataclass(self, adapter):
        adp, mock_gql = adapter

        def _side_effect(gql, variables=None):
            if "user_state" in gql:
                return {
                    "queryApp": {"wasm_smart": '{"positions": {"perp/btcusd": {"size": "0.5", "entry_price": "30000"}}}'}
                }
            return _default_side_effect(gql, variables)

        mock_gql.query.side_effect = _side_effect
        positions = adp.get_open_positions()
        p = positions[0]
        assert isinstance(p, Position)
        assert p.side == "long"
        assert p.size == 0.5
        assert p.entry_price == 30000

    def test_negative_size_is_short(self, adapter):
        adp, mock_gql = adapter

        def _side_effect(gql, variables=None):
            if "user_state" in gql:
                return {
                    "queryApp": {"wasm_smart": '{"positions": {"perp/btcusd": {"size": "-0.3", "entry_price": "30000"}}}'}
                }
            return _default_side_effect(gql, variables)

        mock_gql.query.side_effect = _side_effect
        positions = adp.get_open_positions()
        assert positions[0].side == "short"
        assert positions[0].size == 0.3


class TestDangoGetBalance:
    def test_returns_zero_when_not_registered(self, adapter):
        adp, mock_gql = adapter

        def _fail(gql, variables=None):
            if "users(publicKeyHash" in gql:
                return {"users": {"nodes": []}}
            return {}

        mock_gql.query.side_effect = _fail
        assert adp.get_balance() == 0.0

    def test_returns_free_margin(self, adapter):
        adp, mock_gql = adapter

        def _side_effect(gql, variables=None):
            if "user_state" in gql:
                return {
                    "queryApp": {"wasm_smart": '{"margin": "5000", "reserved_margin": "100"}'}
                }
            return _default_side_effect(gql, variables)

        mock_gql.query.side_effect = _side_effect
        assert adp.get_balance() == 4900.0

    def test_returns_zero_if_no_data(self, adapter):
        adp, _ = adapter
        assert adp.get_balance() == 0.0


class TestDangoPlaceOrder:
    def test_returns_order_result(self, adapter):
        adp, _ = adapter

        with patch(
            "src.exchanges.dango._sign_eip712",
            return_value=("a" * 128, "b" * 128),
        ):
            result = adp.place_order("perp/btcusd", "buy", 0.01, 0.04, 0.02)

        assert result.order_id == "abc123"
        assert result.symbol == "perp/btcusd"
        assert result.side == "buy"
        assert result.status == "open"

    def test_sell_side_negative_size(self, adapter):
        adp, _ = adapter

        with patch(
            "src.exchanges.dango._sign_eip712",
            return_value=("a" * 128, "b" * 128),
        ):
            result = adp.place_order("perp/btcusd", "sell", 0.01, 0.04, 0.02)

        assert result.side == "sell"

    def test_uses_account_address_as_sender(self, adapter):
        adp, mock_gql = adapter

        with patch(
            "src.exchanges.dango._sign_eip712",
            return_value=("a" * 128, "b" * 128),
        ):
            adp.place_order("perp/btcusd", "buy", 0.01, 0.04, 0.02)

        # Find the simulate call and check sender
        simulate_calls = [
            call for call in mock_gql.query.call_args_list
            if "simulate" in str(call)
        ]
        assert len(simulate_calls) == 1
        call = simulate_calls[0]
        variables = call.args[1] if len(call.args) > 1 else call.kwargs.get("variables", {})
        tx = variables["tx"]
        assert tx["sender"] == "0xaaaa1111bbbb2222cccc3333dddd4444eeee5555"


class TestDangoCancelOrphanOrders:
    def test_default_noop(self, adapter):
        adp, _ = adapter
        assert adp.cancel_orphan_orders([]) == 0
