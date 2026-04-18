"""Tests for EMA and ATR indicator functions."""

import pandas as pd
import pytest

from src.indicators.atr import atr
from src.indicators.ema import ema


class TestEma:
    def test_returns_same_length(self):
        s = pd.Series(range(1, 51), dtype=float)
        result = ema(s, 12)
        assert len(result) == len(s)

    def test_trending_up_series(self):
        s = pd.Series(range(1, 51), dtype=float)
        result = ema(s, 12)
        # EMA of strictly increasing series should also be increasing
        assert result.iloc[-1] > result.iloc[0]

    def test_flat_series_equals_price(self):
        s = pd.Series([100.0] * 50)
        result = ema(s, 12)
        # EMA of a constant series must equal that constant
        assert abs(result.iloc[-1] - 100.0) < 1e-9

    def test_fast_above_slow_on_uptrend(self):
        prices = pd.Series(range(1, 101), dtype=float)
        fast = ema(prices, 12)
        slow = ema(prices, 26)
        assert fast.iloc[-1] > slow.iloc[-1]

    def test_invalid_period_raises(self):
        with pytest.raises(ValueError):
            ema(pd.Series([1.0, 2.0]), 0)


class TestAtr:
    def _make_ohlc(self, n: int = 50, price: float = 100.0, move: float = 2.0):
        """Create a simple synthetic OHLCV DataFrame."""
        import numpy as np

        closes = [price] * n
        highs = [c + move for c in closes]
        lows = [c - move for c in closes]
        return pd.DataFrame({"high": highs, "low": lows, "close": closes})

    def test_returns_same_length(self):
        df = self._make_ohlc()
        result = atr(df["high"], df["low"], df["close"], 14)
        assert len(result) == len(df)

    def test_constant_range_converges(self):
        df = self._make_ohlc(n=100, move=2.0)
        result = atr(df["high"], df["low"], df["close"], 14)
        # For a constant H-L range of 4, ATR should converge near 4
        assert abs(result.iloc[-1] - 4.0) < 0.5

    def test_zero_range_near_zero(self):
        df = self._make_ohlc(n=100, move=0.0)
        result = atr(df["high"], df["low"], df["close"], 14)
        assert result.iloc[-1] < 1e-9

    def test_invalid_period_raises(self):
        df = self._make_ohlc()
        with pytest.raises(ValueError):
            atr(df["high"], df["low"], df["close"], 0)
