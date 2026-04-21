"""
DreamCash adapter tests — mocked CCXT, no live API calls.
"""

from unittest.mock import MagicMock, patch
import pytest

from src.exchanges.base import ExchangeAdapter
from src.exchanges.dreamcash import DreamCashAdapter


class _FakeSecrets:
    dreamcash_api_key = "0xWALLET"
    dreamcash_api_secret = "0xPRIVATE"
    dreamcash_builder_code = "0xDREAMCASHBUILDER"


class _FakeConfig:
    secrets = _FakeSecrets()


@pytest.fixture()
def adapter():
    with patch("src.exchanges.ccxt_base.ccxt") as mock_ccxt:
        mock_exchange = MagicMock()
        mock_exchange.options = {}
        mock_ccxt.hyperliquid.return_value = mock_exchange
        adp = DreamCashAdapter(_FakeConfig())  # type: ignore[arg-type]
        yield adp, mock_exchange


class TestDreamCashAdapterInterface:
    def test_is_exchange_adapter(self, adapter):
        adp, _ = adapter
        assert isinstance(adp, ExchangeAdapter)

    def test_stores_builder_code(self, adapter):
        adp, _ = adapter
        assert adp._exchange.options["builder"] == "0xDREAMCASHBUILDER"

    def test_stores_fee_int(self, adapter):
        adp, _ = adapter
        assert adp._exchange.options["feeInt"] == 20

    def test_stores_fee_rate(self, adapter):
        adp, _ = adapter
        assert adp._exchange.options["feeRate"] == "0.02%"

    def test_ccxt_id(self, adapter):
        adp, _ = adapter
        assert adp.CCXT_ID == "hyperliquid"

    def test_quote_currency(self, adapter):
        adp, _ = adapter
        assert adp.QUOTE_CURRENCY == "USDT"


class TestDreamCashPlaceOrder:
    def test_calls_approval_once(self, adapter):
        adp, mock_ex = adapter
        mock_ex.create_order.return_value = {
            "id": "1",
            "average": 100.0,
            "status": "closed",
        }
        with patch("src.exchanges.dreamcash.get_hip3_mid_price", return_value=100.0):
            adp.place_order("CASH-WTI/USDT0:USDT0", "buy", 0.01, 0.04, 0.02)
        adp._exchange.handle_builder_fee_approval.assert_called_once()

    def test_skips_approval_on_second_order(self, adapter):
        adp, mock_ex = adapter
        mock_ex.create_order.return_value = {
            "id": "1",
            "average": 100.0,
            "status": "closed",
        }
        with patch("src.exchanges.dreamcash.get_hip3_mid_price", return_value=100.0):
            adp.place_order("CASH-WTI/USDT0:USDT0", "buy", 0.01, 0.04, 0.02)
            adp.place_order("CASH-WTI/USDT0:USDT0", "buy", 0.01, 0.04, 0.02)
        assert adp._exchange.handle_builder_fee_approval.call_count == 1
