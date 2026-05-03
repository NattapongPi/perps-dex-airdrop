"""
Exchange adapter contract.

Every exchange integration must subclass ExchangeAdapter and implement
all abstract methods. The orchestrator only talks to this interface —
it never imports a concrete adapter directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass(frozen=True)
class Position:
    """An open position on the exchange."""

    symbol: str
    side: str        # "long" | "short"
    size: float      # in base asset units
    entry_price: float


@dataclass(frozen=True)
class OrderResult:
    """Result of a place_order() call."""

    order_id: str
    symbol: str
    side: str        # "buy" | "sell"
    size: float
    entry_price: float
    tp_price: Optional[float]
    sl_price: Optional[float]
    status: str      # "open" | "filled" | "rejected"


class ExchangeAdapter(ABC):
    """
    Abstract base class for all exchange integrations.

    Subclasses receive the full Config object in __init__ so they can
    read any secrets or parameters they need without adding arguments.
    """

    @abstractmethod
    def get_top_coins(self, n: int) -> list[str]:
        """
        Return the top N symbols by 24h volume.

        Symbols are in the exchange's native format (e.g. "BTC", "ETH").
        The same format is used in all other methods.
        """

    @abstractmethod
    def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
    ) -> pd.DataFrame:
        """
        Return OHLCV candles as a DataFrame.

        Columns (lowercase): open, high, low, close, volume
        Index: pd.DatetimeIndex, UTC, ascending (oldest first).
        Returns at most `limit` rows; may return fewer if the exchange
        has less history for that symbol.
        """

    @abstractmethod
    def get_open_positions(self) -> list[Position]:
        """
        Return all currently open positions for this account.
        """

    @abstractmethod
    def get_balance(self) -> float:
        """
        Return available account balance in USD (or quote currency).
        """

    @abstractmethod
    def place_order(
        self,
        symbol: str,
        side: str,
        size: float,
        tp_pct: float,
        sl_pct: float,
    ) -> OrderResult:
        """
        Place a market order with attached TP and SL.

        Parameters
        ----------
        symbol : str
            Trading pair in the exchange's native format.
        side : str
            "buy" or "sell".
        size : float
            Position size in base asset units.
        tp_pct : float
            Take-profit distance as a decimal (e.g. 0.04 = 4% from entry).
        sl_pct : float
            Stop-loss distance as a decimal (e.g. 0.02 = 2% from entry).

        Returns
        -------
        OrderResult
        """

    @abstractmethod
    def ping(self) -> bool:
        """
        Return True if the exchange is reachable and credentials are valid.
        Used by the healthcheck endpoint.
        """

    def close_all_positions(self) -> int:
        """
        Close all open positions at market price.

        Called at startup when `clear_positions_on_startup` is enabled.
        Default is a no-op — override in adapters that support it.

        Returns the number of positions closed.
        """
        return 0

    def cancel_orphan_orders(self, open_positions: list[Position]) -> int:
        """
        Cancel open orders for symbols that have no open position.

        Called at the start of each scan to clean up TP/SL orders left behind
        after a position was closed (e.g. SL triggered but TP not auto-cancelled).

        Default is a no-op — override in exchanges that don't auto-cancel
        reduce-only orders when a position closes (e.g. Hibachi).

        Returns the number of orders cancelled.
        """
        return 0
