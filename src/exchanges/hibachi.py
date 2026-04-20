"""
Hibachi exchange adapter.

Docs: https://api-doc.hibachi.xyz/

Hibachi uses a public API for market data (no auth needed) and CCXT for
private account operations (balance, positions, orders).

Public market data:
  GET https://data-api.hibachi.xyz/market/inventory
  GET https://data-api.hibachi.xyz/market/exchange-info

Auth fields required in .env:
  HIBACHI_API_KEY      — API key
  HIBACHI_ACCOUNT_ID   — numeric account ID
  HIBACHI_PRIVATE_KEY  — private key (0x... for ECDSA)

Supported markets: BTC, ETH, SOL, SUI, XRP, BNB, HYPE (all vs USDT).
Quote currency is USDT (not USDC).
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

_logger = logging.getLogger(__name__)

import ccxt
import pandas as pd
import requests

from src.exchanges.base import ExchangeAdapter, OrderResult, Position

if TYPE_CHECKING:
    from src.config_loader import Config


_HIBACHI_PUBLIC_API = "https://data-api.hibachi.xyz"


class HibachiAdapter(ExchangeAdapter):

    CCXT_ID = "hibachi"
    QUOTE_CURRENCY = "USDT"
    PERP_SUFFIX = ":USDT"

    def __init__(self, config: "Config") -> None:
        self._exchange = ccxt.hibachi({
            "apiKey": config.secrets.hibachi_api_key,
            "accountId": config.secrets.hibachi_account_id,
            "privateKey": config.secrets.hibachi_private_key,
        })

    # ------------------------------------------------------------------
    # Public API helpers
    # ------------------------------------------------------------------

    def _fetch_inventory(self) -> dict:
        """Fetch all market data from public inventory endpoint (no auth)."""
        resp = requests.get(
            f"{_HIBACHI_PUBLIC_API}/market/inventory",
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def _build_symbol(self, underlying: str, settlement: str) -> str:
        """Convert 'BTC' + 'USDT' → 'BTC/USDT:USDT'."""
        return f"{underlying}/{settlement}:{settlement}"

    # ------------------------------------------------------------------
    # ExchangeAdapter interface
    # ------------------------------------------------------------------

    def get_top_coins(self, n: int) -> list[str]:
        """
        Fetch all market volumes from public inventory endpoint,
        sort by 24h volume, return top N symbols in full CCXT format.

        Note: Hibachi has no bulk OI endpoint. Volume is used as a proxy.
        """
        data = self._fetch_inventory()
        markets = data.get("markets", [])

        ranked = []
        for m in markets:
            contract = m.get("contract", {})
            info = m.get("info", {})
            underlying = contract.get("underlyingSymbol", "")
            settlement = contract.get("settlementSymbol", "USDT")
            volume = float(info.get("volume24h") or 0)
            if underlying:
                ranked.append((underlying, settlement, volume))

        ranked.sort(key=lambda x: x[2], reverse=True)
        return [
            self._build_symbol(underlying, settlement)
            for underlying, settlement, _ in ranked[:n]
        ]

    def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV candles via CCXT unified fetch_ohlcv.
        Symbol must be full format: 'BTC/USDT:USDT'.

        Returns DataFrame with columns: open, high, low, close, volume
        Index: pd.DatetimeIndex UTC ascending.
        """
        raw = self._exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df.index = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        return df[["open", "high", "low", "close", "volume"]].sort_index()

    def get_open_positions(self) -> list[Position]:
        """
        Fetch open positions via CCXT fetch_positions.
        Only returns positions with non-zero size.
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
        Return free USDT balance.
        """
        balance = self._exchange.fetch_balance()
        return float(balance.get("USDT", {}).get("free", 0))

    def place_order(
        self,
        symbol: str,
        side: str,
        size: float,
        tp_pct: float,
        sl_pct: float,
    ) -> OrderResult:
        """
        Place a market entry, then attach TP and SL as standalone orders.

        CCXT's Hibachi driver does not support parentOrder or triggerDirection,
        so TP and SL are placed as independent orders after the entry fills.
        They will not auto-cancel if the entry is cancelled before filling.

        Order flow (long / buy example):
          1. Market BID entry  — fills at actual_entry
          2. Limit ASK TP      — price = actual_entry * (1 + tp_pct)
          3. Trigger ASK SL    — triggerPrice = actual_entry * (1 - sl_pct)
        """
        is_buy = side == "buy"
        close_side = "sell" if is_buy else "buy"

        # --- 1. Market entry ---
        entry_order = self._exchange.create_order(
            symbol=symbol,
            type="market",
            side=side,
            amount=size,
        )

        # Hibachi returns status='pending' immediately — poll until filled.
        order_id = entry_order.get("id")
        for attempt in range(5):
            actual_entry = float(
                entry_order.get("average")
                or entry_order.get("price")
                or entry_order.get("info", {}).get("avgPx", 0)
            )
            if actual_entry > 0:
                break
            time.sleep(1)
            entry_order = self._exchange.fetch_order(order_id, symbol)
        else:
            # Primary poll loop exhausted — try fallbacks before giving up.

            # Fallback 1: most recent trade for this order
            actual_entry = 0.0
            _logger.warning(
                "Entry price not in order response for %s, falling back to fetch_my_trades",
                symbol,
            )
            try:
                trades = self._exchange.fetch_my_trades(symbol, limit=5)
                for trade in reversed(trades):
                    if str(trade.get("order")) == str(order_id):
                        actual_entry = float(trade.get("price") or 0)
                        if actual_entry > 0:
                            break
            except Exception:
                pass

            # Fallback 2: entry price from the newly opened position
            if actual_entry <= 0:
                _logger.warning(
                    "fetch_my_trades did not yield entry price for %s, falling back to fetch_position",
                    symbol,
                )
                try:
                    position = self._exchange.fetch_position(symbol)
                    actual_entry = float(position.get("entryPrice") or 0)
                except Exception:
                    pass

            if actual_entry <= 0:
                raise RuntimeError(
                    f"Could not determine entry price for {symbol} after fill "
                    f"(tried order poll, fetch_my_trades, fetch_position). "
                    f"Raw order response: {entry_order}"
                )

        filled_size = float(entry_order.get("filled") or size)
        tp_price = actual_entry * (1 + tp_pct) if is_buy else actual_entry * (1 - tp_pct)
        sl_price = actual_entry * (1 - sl_pct) if is_buy else actual_entry * (1 + sl_pct)

        # --- 2. TP — standalone reduce-only limit order ---
        self._exchange.create_order(
            symbol=symbol,
            type="limit",
            side=close_side,
            amount=filled_size,
            price=tp_price,
            params={"reduceOnly": True},
        )

        # --- 3. SL — standalone reduce-only trigger market order ---
        self._exchange.create_order(
            symbol=symbol,
            type="market",
            side=close_side,
            amount=filled_size,
            params={"reduceOnly": True, "triggerPrice": sl_price},
        )

        return OrderResult(
            order_id=str(entry_order.get("id", "unknown")),
            symbol=symbol,
            side=side,
            size=filled_size,
            entry_price=actual_entry,
            tp_price=tp_price,
            sl_price=sl_price,
            status=entry_order.get("status", "open"),
        )

    def ping(self) -> bool:
        """Lightweight connectivity check via public inventory endpoint."""
        try:
            self._fetch_inventory()
            return True
        except Exception:
            return False
