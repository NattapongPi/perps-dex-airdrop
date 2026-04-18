"""Tests for TrendFilter strategy."""

import pandas as pd
import pytest

from src.strategy.trend_filter import Signal, TrendFilter


def _make_df(closes: list[float], move: float = 1.0) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame from a close price list."""
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + move for c in closes],
            "low": [c - move for c in closes],
            "close": closes,
            "volume": [1_000_000.0] * len(closes),
        }
    )


class TestTrendFilter:
    def setup_method(self):
        self.tf = TrendFilter(ema_fast=12, ema_slow=26, atr_period=14)

    def test_bullish_trend_returns_long(self):
        # Strictly increasing prices → EMA12 > EMA26
        closes = list(range(1, 101))
        df = _make_df(closes)
        signal, atr_val = self.tf.evaluate(df)
        assert signal == Signal.LONG
        assert atr_val > 0

    def test_bearish_trend_returns_none(self):
        # Strictly decreasing prices → EMA12 < EMA26
        closes = list(range(100, 0, -1))
        df = _make_df(closes)
        signal, atr_val = self.tf.evaluate(df)
        assert signal == Signal.NONE

    def test_flat_prices_returns_none(self):
        # Flat prices → EMA12 == EMA26 → not strictly greater → NONE
        closes = [100.0] * 100
        df = _make_df(closes)
        signal, _ = self.tf.evaluate(df)
        assert signal == Signal.NONE

    def test_atr_value_is_positive(self):
        closes = list(range(1, 101))
        df = _make_df(closes, move=2.0)
        _, atr_val = self.tf.evaluate(df)
        assert atr_val > 0

    def test_missing_column_raises(self):
        df = pd.DataFrame({"close": [1.0] * 50})
        with pytest.raises(ValueError, match="missing required columns"):
            self.tf.evaluate(df)

    def test_too_short_raises(self):
        closes = [100.0] * 10  # need at least 26
        df = _make_df(closes)
        with pytest.raises(ValueError, match="at least"):
            self.tf.evaluate(df)

    def test_invalid_periods_raise(self):
        with pytest.raises(ValueError):
            TrendFilter(ema_fast=26, ema_slow=12, atr_period=14)
