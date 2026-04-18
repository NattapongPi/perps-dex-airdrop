"""
Exponential Moving Average — pure function, no side effects.
"""

from __future__ import annotations

import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    """
    Compute EMA over a price series.

    Uses pandas ewm with adjust=False, which matches the standard EMA
    convention used by TradingView and most exchanges:
        EMA_t = price_t * k + EMA_(t-1) * (1 - k)
        where k = 2 / (period + 1)

    Parameters
    ----------
    series : pd.Series
        Price series (typically close prices). Must have at least `period` rows.
    period : int
        EMA lookback period (e.g. 12, 26).

    Returns
    -------
    pd.Series
        EMA values, same length and index as `series`.
        First rows will be approximate until the series warms up.
    """
    if period < 1:
        raise ValueError(f"EMA period must be >= 1, got {period}")
    return series.ewm(span=period, adjust=False).mean()
