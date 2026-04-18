"""
Average True Range — pure function, no side effects.
"""

from __future__ import annotations

import pandas as pd


def atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int,
) -> pd.Series:
    """
    Compute ATR (Average True Range) over OHLC data.

    True Range for each bar:
        TR = max(
            high - low,
            abs(high - prev_close),
            abs(low  - prev_close)
        )

    ATR = EWM smoothing of TR with span=period (Wilder's method approximation).
    The first bar has no prev_close so its TR will be NaN; subsequent bars will
    converge as the EWM warms up.

    Parameters
    ----------
    high, low, close : pd.Series
        OHLC series with a shared index. All must be the same length.
    period : int
        ATR lookback period (commonly 14).

    Returns
    -------
    pd.Series
        ATR values, same length and index as inputs.
    """
    if period < 1:
        raise ValueError(f"ATR period must be >= 1, got {period}")

    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    return tr.ewm(span=period, adjust=False).mean()
