"""
Generic CCXT-based exchange adapter.

All Hyperliquid-compatible exchanges (Hyperliquid, TradeXYZ, DreamCash, etc.)
share the same API surface. Subclasses declare 3 class attributes and provide
credentials — everything else is inherited.

To add a new Hyperliquid-compatible exchange:
  1. Subclass CcxtAdapter (or HyperliquidAdapter for HL-native exchanges)
  2. Set CCXT_ID, QUOTE_CURRENCY, PERP_SUFFIX
  3. Call super().__init__(api_key, api_secret, builder_code) with your secrets
"""

from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Any

import ccxt
import pandas as pd

from src.exchanges.base import ExchangeAdapter, OrderResult, Position

if TYPE_CHECKING:
    pass


class CcxtAdapter(ExchangeAdapter, ABC):
    """
    Base class for CCXT-backed exchange adapters.

    Class attributes (must be set by each subclass):
      CCXT_ID        — CCXT exchange identifier, e.g. "hyperliquid"
      QUOTE_CURRENCY — collateral currency for balance lookup, e.g. "USDC"
      PERP_SUFFIX    — suffix used to identify perp markets, e.g. ":USDC"
    """

    CCXT_ID: str
    QUOTE_CURRENCY: str
    PERP_SUFFIX: str

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        builder_code: str,
    ) -> None:
        """
        Parameters
        ----------
        api_key : str
            Wallet address (used as account identifier).
        api_secret : str
            Private key for signing orders.
        builder_code : str
            Builder address for fee-share. Empty string = no builder.
        """
        exchange_cls = getattr(ccxt, self.CCXT_ID)
        self._exchange = exchange_cls({
            "walletAddress": api_key,
            "privateKey": api_secret,
        })

        # Allow market orders without an explicit price (CCXT Hyperliquid converts
        # them to IOC limit orders using last_price ± slippage%).
        self._exchange.options["defaultSlippage"] = 0.05

        # Set builder code once — CCXT attaches it to every order.
        # builderFee=False means we supply our own address rather than using
        # CCXT's default fee schedule.
        if builder_code:
            self._exchange.options["broker"] = builder_code
            self._exchange.options["builderFee"] = False

    def _get_market_price(self, symbol: str) -> float | None:
        """Return current mid price for market order slippage calculation.

        Override in subclasses whose markets aren't in the CCXT markets list
        (e.g. HIP-3 adapters), otherwise CCXT will fail trying to fetch the ticker.
        Returns None for standard exchanges where CCXT fetches the price itself.
        """
        return None

    # ------------------------------------------------------------------
    # ExchangeAdapter interface — full implementations
    # ------------------------------------------------------------------

    def get_top_coins(self, n: int) -> list[str]:
        """
        Fetch all perpetual tickers, sort by open interest (USD notional), return top N symbols.
        Filters to perp markets by PERP_SUFFIX (e.g. ":USDC").
        Falls back to quoteVolume if openInterestValue is unavailable (e.g. newly listed coins).
        """
        tickers = self._exchange.fetch_tickers()
        perp_tickers = [
            (symbol, t.get("openInterestValue") or t.get("quoteVolume") or 0)
            for symbol, t in tickers.items()
            if symbol.endswith(self.PERP_SUFFIX)
        ]
        perp_tickers.sort(key=lambda x: x[1], reverse=True)
        return [symbol for symbol, _ in perp_tickers[:n]]

    def get_ohlcv(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        """
        Fetch OHLCV candles via CCXT unified fetch_ohlcv.

        Returns
        -------
        pd.DataFrame
            Columns: open, high, low, close, volume
            Index: pd.DatetimeIndex UTC ascending (oldest first).
        """
        raw = self._exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df.index = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        return df[["open", "high", "low", "close", "volume"]].sort_index()

    def get_open_positions(self) -> list[Position]:
        """
        Fetch all open positions via CCXT fetch_positions.
        Filters out zero-size entries.
        """
        raw_positions = self._exchange.fetch_positions()
        positions = []
        for p in raw_positions:
            size = abs(float(p.get("contracts") or 0))
            if size == 0:
                continue
            side = "long" if p.get("side") == "long" else "short"
            positions.append(Position(
                symbol=p["symbol"],
                side=side,
                size=size,
                entry_price=float(p.get("entryPrice") or 0),
            ))
        return positions

    def get_balance(self) -> float:
        """
        Return free balance in QUOTE_CURRENCY (e.g. USDC).
        """
        balance = self._exchange.fetch_balance()
        return float(balance.get(self.QUOTE_CURRENCY, {}).get("free", 0))

    def place_order(
        self,
        symbol: str,
        side: str,
        size: float,
        tp_pct: float,
        sl_pct: float,
    ) -> OrderResult:
        """
        Place a market entry + reduce-only TP limit + reduce-only SL stop-market.

        1. Market entry (CCXT sends IOC internally for Hyperliquid-family)
        2. TP — reduce-only GTC limit on opposite side
        3. SL — reduce-only stop-market on opposite side
        """
        is_buy = side == "buy"
        close_side = "sell" if is_buy else "buy"

        # --- 1. Market entry ---
        # price_hint allows subclasses (e.g. HIP-3 adapters) to supply the current
        # mid price so CCXT can compute the IOC slippage price without fetching the
        # ticker (which fails for synthetic markets not in the standard markets list).
        price_hint = self._get_market_price(symbol)
        entry_order = self._exchange.create_order(
            symbol=symbol,
            type="market",
            side=side,
            amount=size,
            price=price_hint,
        )

        entry_price = float(
            entry_order.get("average")
            or entry_order.get("price")
            or entry_order.get("info", {}).get("avgPx", 0)
        )

        if entry_price <= 0:
            raise RuntimeError(
                f"Could not determine entry price for {symbol} after fill. "
                f"Raw order response: {entry_order}"
            )

        # --- 2. TP — reduce-only limit ---
        tp_price = entry_price * (1 + tp_pct) if is_buy else entry_price * (1 - tp_pct)
        self._exchange.create_order(
            symbol=symbol,
            type="limit",
            side=close_side,
            amount=size,
            price=tp_price,
            params={"reduceOnly": True},
        )

        # --- 3. SL — reduce-only stop-market ---
        sl_price = entry_price * (1 - sl_pct) if is_buy else entry_price * (1 + sl_pct)
        self._exchange.create_order(
            symbol=symbol,
            type="stop",
            side=close_side,
            amount=size,
            price=sl_price,
            params={
                "reduceOnly": True,
                "stopPrice": sl_price,
                "triggerType": "mark",
            },
        )

        return OrderResult(
            order_id=str(entry_order.get("id", "unknown")),
            symbol=symbol,
            side=side,
            size=size,
            entry_price=entry_price,
            tp_price=tp_price,
            sl_price=sl_price,
            status=entry_order.get("status", "open"),
        )

    def ping(self) -> bool:
        """Lightweight connectivity check via fetch_tickers."""
        try:
            self._exchange.fetch_tickers()
            return True
        except Exception:
            return False
