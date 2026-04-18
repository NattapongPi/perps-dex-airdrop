"""
Position sizing and TP/SL calculation — pure functions, no side effects.

Math summary (long positions):
  SL price = entry - (ATR * sl_multiplier)
  TP price = entry + (ATR * tp_multiplier)
  Risk amount = balance * (risk_pct / 100)
  Size = risk_amount / (entry - sl_price)
"""

from __future__ import annotations


def calculate_sl_tp_prices(
    entry_price: float,
    atr_value: float,
    sl_multiplier: float,
    tp_multiplier: float,
) -> tuple[float, float]:
    """
    Compute absolute SL and TP prices for a long position.

    Parameters
    ----------
    entry_price : float
        Expected fill price (typically last close).
    atr_value : float
        Current ATR value from the same candle.
    sl_multiplier : float
        ATR multiple for stop loss (e.g. 1.5 means SL is 1.5 × ATR below entry).
    tp_multiplier : float
        ATR multiple for take profit (e.g. 2.0 means TP is 2.0 × ATR above entry).

    Returns
    -------
    (sl_price, tp_price)
    """
    sl_price = entry_price - (atr_value * sl_multiplier)
    tp_price = entry_price + (atr_value * tp_multiplier)
    return sl_price, tp_price


def calculate_sl_tp_pct(
    entry_price: float,
    sl_price: float,
    tp_price: float,
) -> tuple[float, float]:
    """
    Convert absolute SL/TP prices to percentages (decimals) for exchange APIs.

    Parameters
    ----------
    entry_price : float
    sl_price : float
        Must be below entry_price for a long (otherwise sizing returns 0).
    tp_price : float
        Must be above entry_price for a long.

    Returns
    -------
    (sl_pct, tp_pct)
        Positive decimals, e.g. 0.02 = 2%.

    Raises
    ------
    ValueError
        If entry_price is zero.
    """
    if entry_price == 0:
        raise ValueError("entry_price cannot be zero")

    sl_pct = abs(entry_price - sl_price) / entry_price
    tp_pct = abs(tp_price - entry_price) / entry_price
    return sl_pct, tp_pct


def calculate_position_size(
    balance: float,
    risk_pct: float,
    entry_price: float,
    sl_price: float,
) -> float:
    """
    ATR-informed position sizing based on fixed fractional risk.

    Formula:
        risk_amount = balance * (risk_pct / 100)
        sl_distance = entry_price - sl_price      # price units per base unit
        size        = risk_amount / sl_distance   # base asset units

    Example:
        balance=10_000, risk_pct=1.0, entry=100, sl=98
        → risk_amount = 100
        → sl_distance = 2
        → size = 50 units

    Parameters
    ----------
    balance : float
        Available account balance in quote currency (USD).
    risk_pct : float
        Percent of balance to risk (e.g. 1.0 = 1%).
    entry_price : float
        Expected fill price.
    sl_price : float
        Stop-loss price. Must be below entry_price for a long.

    Returns
    -------
    float
        Position size in base asset units.
        Returns 0.0 if sl_price >= entry_price (invalid SL — avoids division error).
    """
    if sl_price >= entry_price:
        return 0.0

    risk_amount = balance * (risk_pct / 100.0)
    sl_distance = entry_price - sl_price
    return risk_amount / sl_distance
