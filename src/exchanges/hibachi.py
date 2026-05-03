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

        # Hibachi's create_order always returns {id, status:'pending'} with no
        # price. fetch_order populates price/filled once the order is FILLED.
        order_id = entry_order.get("id")
        entry_order = self._exchange.fetch_order(order_id, symbol)
        actual_entry = float(
            entry_order.get("average")
            or entry_order.get("price")
            or entry_order.get("info", {}).get("avgPx", 0)
        )
        if actual_entry:
            _logger.debug("Entry price resolved via fetch_order for %s: %s", symbol, actual_entry)

        # Fallback 1: fetch_my_trades matched by order_id.
        # CCXT normalises bidOrderId/askOrderId into the "order" field for both sides.
        if not actual_entry:
            _logger.warning(
                "Entry price not in fetch_order for %s, falling back to fetch_my_trades",
                symbol,
            )
            trades = self._exchange.fetch_my_trades(symbol, limit=5)
            matching = [t for t in trades if t.get("order") == order_id]
            if matching:
                actual_entry = float(matching[-1]["price"])
                _logger.warning("Entry price resolved via fetch_my_trades for %s: %s", symbol, actual_entry)

        # Fallback 2: most recent trade for this symbol — order was placed milliseconds ago.
        if not actual_entry:
            trades = self._exchange.fetch_my_trades(symbol, limit=1)
            if trades:
                actual_entry = float(trades[-1]["price"])
                _logger.warning("Entry price resolved via latest trade fallback for %s: %s", symbol, actual_entry)

        if not actual_entry:
            raise RuntimeError(
                f"Could not determine entry price for {symbol} after fill. "
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
        # triggerDirection is required by Hibachi whenever triggerPrice is set.
        # Long SL fires when price drops BELOW sl_price; short SL fires ABOVE.
        self._exchange.create_order(
            symbol=symbol,
            type="market",
            side=close_side,
            amount=filled_size,
            params={
                "reduceOnly": True,
                "triggerPrice": sl_price,
                "triggerDirection": "LOW" if is_buy else "HIGH",
            },
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

    def close_all_positions(self) -> int:
        """
        Close all open positions at market price.

        Places a reduce-only market order on the opposite side for each position.
        """
        positions = self.get_open_positions()
        closed = 0
        for pos in positions:
            close_side = "sell" if pos.side == "long" else "buy"
            try:
                self._exchange.create_order(
                    symbol=pos.symbol,
                    type="market",
                    side=close_side,
                    amount=pos.size,
                    params={"reduceOnly": True},
                )
                _logger.info(
                    "Closed position %s %s (size %s)",
                    pos.side, pos.symbol, pos.size,
                )
                closed += 1
            except Exception as exc:
                _logger.error(
                    "Failed to close position %s: %s",
                    pos.symbol, exc,
                )
        return closed

    def cancel_orphan_orders(self, open_positions) -> int:
        """
        Cancel open orders for symbols with no open position.

        Hibachi does not auto-cancel reduce-only orders when a position closes,
        so a TP limit order left after an SL hit can re-open an unwanted position.
        This runs at scan start to clean up any such orphans.
        """
        open_syms = {p.symbol for p in open_positions}
        open_orders = self._exchange.fetch_open_orders()
        cancelled = 0
        for order in open_orders:
            if order["symbol"] not in open_syms:
                try:
                    self._exchange.cancel_order(order["id"], order["symbol"])
                    _logger.info(
                        "Cancelled orphan order %s for %s (no open position)",
                        order["id"], order["symbol"],
                    )
                    cancelled += 1
                except Exception as exc:
                    _logger.warning("Failed to cancel orphan order %s: %s", order["id"], exc)
        return cancelled

    def ping(self) -> bool:
        """Lightweight connectivity check via public inventory endpoint."""
        try:
            self._fetch_inventory()
            return True
        except Exception:
            return False
