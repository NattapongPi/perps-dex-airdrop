"""
TradeXYZ adapter tests — mocked CCXT, no live API calls.

The mock patches `src.exchanges.ccxt_base.ccxt` because CcxtAdapter.__init__
is where the exchange is instantiated (TradeXYZAdapter just calls super()).
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.exchanges.base import ExchangeAdapter, Position
from src.exchanges.tradexyz import TradeXYZAdapter


class _FakeSecrets:
    tradexyz_api_key = "0xWALLET"
    tradexyz_api_secret = "0xPRIVATE"
    tradexyz_builder_code = "0xBUILDER"


class _FakeConfig:
    secrets = _FakeSecrets()


@pytest.fixture()
def adapter():
    with patch("src.exchanges.ccxt_base.ccxt") as mock_ccxt:
        mock_exchange = MagicMock()
        mock_exchange.options = {}  # real dict so builder_code gets stored
        mock_ccxt.hyperliquid.return_value = mock_exchange
        adp = TradeXYZAdapter(_FakeConfig())  # type: ignore[arg-type]
        yield adp, mock_exchange


class TestTradeXYZAdapterInterface:
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


class TestTradeXYZGetTopCoins:
    def test_returns_hip3_coins(self, adapter):
        adp, _ = adapter
        hip3_symbols = ["NVDA/USDC:USDC", "TSLA/USDC:USDC", "GOLD/USDC:USDC"]
        with patch("src.exchanges.tradexyz.get_hip3_top_coins", return_value=hip3_symbols) as mock_hip3:
            result = adp.get_top_coins(3)
        assert result == hip3_symbols
        mock_hip3.assert_called_once_with(
            "0x88806a71D74ad0a510b350545C9aE490912F0888", ":USDC", 3, quote="USDC"
        )

    def test_returns_at_most_n(self, adapter):
        adp, _ = adapter
        all_symbols = [f"ASSET{i}/USDC:USDC" for i in range(10)]
        with patch("src.exchanges.tradexyz.get_hip3_top_coins", return_value=all_symbols[:3]):
            result = adp.get_top_coins(3)
        assert len(result) == 3


class TestTradeXYZGetOhlcv:
    def _fake_df(self, rows):
        import pandas as pd
        data = [{"t": r[0], "o": r[1], "h": r[2], "l": r[3], "c": r[4], "v": r[5]} for r in rows]
        df = pd.DataFrame(data)
        df.index = pd.to_datetime(df["t"], unit="ms", utc=True)
        df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
        return df[["open", "high", "low", "close", "volume"]].astype(float).sort_index()

    def test_returns_correct_dataframe(self, adapter):
        adp, _ = adapter
        fake = self._fake_df([
            [1_700_000_000_000, 100.0, 105.0, 98.0, 102.0, 500.0],
            [1_700_003_600_000, 102.0, 107.0, 101.0, 106.0, 600.0],
        ])
        with patch("src.exchanges.tradexyz.get_hip3_ohlcv", return_value=fake) as mock_ohlcv:
            df = adp.get_ohlcv("CL/USDC:USDC", "1h", 2)
        mock_ohlcv.assert_called_once_with("xyz:CL", "1h", 2)
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert len(df) == 2
        assert df["close"].iloc[-1] == 106.0

    def test_index_is_datetime(self, adapter):
        adp, _ = adapter
        fake = self._fake_df([[1_700_000_000_000, 100.0, 105.0, 98.0, 102.0, 500.0]])
        with patch("src.exchanges.tradexyz.get_hip3_ohlcv", return_value=fake):
            df = adp.get_ohlcv("CL/USDC:USDC", "1h", 1)
        assert isinstance(df.index, pd.DatetimeIndex)


class TestTradeXYZGetPositions:
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


class TestTradeXYZGetBalance:
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


class TestTradeXYZPlaceOrder:
    def test_returns_order_result(self, adapter):
        adp, mock_ex = adapter
        mock_ex.create_order.return_value = {
            "id": "12345",
            "average": 30000.0,
            "status": "closed",
        }
        with patch("src.exchanges.tradexyz.get_hip3_mid_price", return_value=30000.0):
            result = adp.place_order("CL/USDC:USDC", "buy", 0.01, 0.04, 0.02)
        assert result.order_id == "12345"
        assert result.entry_price == 30000.0
        assert result.tp_price == pytest.approx(30000.0 * 1.04)
        assert result.sl_price == pytest.approx(30000.0 * 0.98)

    def test_places_three_orders(self, adapter):
        adp, mock_ex = adapter
        mock_ex.create_order.return_value = {
            "id": "1", "average": 30000.0, "status": "closed"
        }
        with patch("src.exchanges.tradexyz.get_hip3_mid_price", return_value=30000.0):
            adp.place_order("CL/USDC:USDC", "buy", 0.01, 0.04, 0.02)
        assert mock_ex.create_order.call_count == 3


class TestTradeXYZPing:
    def test_ping_returns_true_on_success(self, adapter):
        adp, mock_ex = adapter
        mock_ex.fetch_tickers.return_value = {}
        assert adp.ping() is True

    def test_ping_returns_false_on_failure(self, adapter):
        adp, mock_ex = adapter
        mock_ex.fetch_tickers.side_effect = RuntimeError("network error")
        assert adp.ping() is False