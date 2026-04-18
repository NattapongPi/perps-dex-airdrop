"""
EMA trend filter strategy.

Signal logic:
  LONG — most recent candle has EMA_fast > EMA_slow (bullish trend)
  NONE — otherwise (flat or bearish, do not open)

Returns the current ATR value alongside the signal so the caller can
use it directly for SL/TP calculation without recomputing.
"""

from __future__ import annotations

from enum import Enum

import pandas as pd

from src.indicators.atr import atr
from src.indicators.ema import ema

REQUIRED_COLUMNS = {"open", "high", "low", "close", "volume"}


class Signal(Enum):
    LONG = "LONG"
    NONE = "NONE"


class TrendFilter:
    """
    EMA-based trend filter.

    Parameters
    ----------
    ema_fast : int
        Fast EMA period (e.g. 12).
    ema_slow : int
        Slow EMA period (e.g. 26). Must be > ema_fast.
    atr_period : int
        ATR period (e.g. 14).
    """

    def __init__(self, ema_fast: int, ema_slow: int, atr_period: int) -> None:
        if ema_fast >= ema_slow:
            raise ValueError(
                f"ema_fast ({ema_fast}) must be less than ema_slow ({ema_slow})"
            )
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.atr_period = atr_period

    def evaluate(self, df: pd.DataFrame) -> tuple[Signal, float]:
        """
        Evaluate the trend signal on a candle DataFrame.

        Parameters
        ----------
        df : pd.DataFrame
            Must have columns: open, high, low, close, volume.
            Rows must be sorted ascending (oldest first).
            Minimum length: max(ema_slow, atr_period) + a few warm-up bars.

        Returns
        -------
        (Signal, atr_value)
            Signal.LONG if the last bar has EMA_fast > EMA_slow, else Signal.NONE.
            atr_value is the ATR of the last bar (use for SL/TP sizing).

        Raises
        ------
        ValueError
            If the DataFrame is missing required columns or is too short.
        """
        missing = REQUIRED_COLUMNS - set(df.columns)
        if missing:
            raise ValueError(f"DataFrame missing required columns: {missing}")

        min_length = max(self.ema_slow, self.atr_period)
        if len(df) < min_length:
            raise ValueError(
                f"DataFrame has {len(df)} rows; need at least {min_length} "
                f"for EMA{self.ema_slow} / ATR{self.atr_period} to be meaningful."
            )

        ema_f = ema(df["close"], self.ema_fast)
        ema_s = ema(df["close"], self.ema_slow)
        current_atr = atr(df["high"], df["low"], df["close"], self.atr_period).iloc[-1]

        if ema_f.iloc[-1] > ema_s.iloc[-1]:
            return Signal.LONG, float(current_atr)

        return Signal.NONE, float(current_atr)
