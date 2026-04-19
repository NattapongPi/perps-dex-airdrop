"""
HIP-3 DEX market discovery and OHLCV for Hyperliquid.

Queries the `perpDexs` endpoint to find all markets listed by a specific
HIP-3 DEX (identified by its deployer address), then ranks them by OI cap.

OHLCV uses the Hyperliquid `candleSnapshot` API directly (bypassing CCXT's
market validation, which rejects HIP-3 symbols not in the standard markets list).
"""

from __future__ import annotations

import time
from typing import Any

import pandas as pd
import requests

_HL_INFO_URL = "https://api.hyperliquid.xyz/info"

_INTERVAL_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


def _fetch_l2book(coin: str) -> dict:
    resp = requests.post(_HL_INFO_URL, json={"type": "l2Book", "coin": coin}, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _infer_tick(values: list[str]) -> float:
    """Infer minimum tick size from a sample of decimal strings (e.g. order book prices)."""
    max_dp = 0
    for v in values:
        if "." in v:
            dp = len(v.split(".")[1].rstrip("0") or "0")
            max_dp = max(max_dp, dp)
    return 10.0 ** (-max_dp) if max_dp > 0 else 1.0


def get_hip3_mid_price(coin: str) -> float:
    """Return the current mid price for a HIP-3 coin (e.g. 'xyz:CL') via l2Book."""
    data = _fetch_l2book(coin)
    levels = data.get("levels", [])
    if len(levels) < 2 or not levels[0] or not levels[1]:
        raise ValueError(f"Empty order book for {coin!r}")
    best_bid = float(levels[0][0]["px"])
    best_ask = float(levels[1][0]["px"])
    return (best_bid + best_ask) / 2


def ensure_hip3_market(exchange: Any, symbol: str, dex_prefix: str, quote: str = "USDC") -> None:
    """
    Inject a synthetic market entry into a CCXT exchange's markets dict for a
    HIP-3 symbol that isn't in the standard Hyperliquid markets list.

    CCXT validates the symbol before placing orders, so we must register it.
    baseId is set to the prefixed coin name (e.g. 'xyz:CL') because that's what
    the Hyperliquid exchange API expects in the order payload.
    """
    if not exchange.markets:
        exchange.load_markets()
    if symbol in exchange.markets:
        return
    base = symbol.split("/")[0]
    prefixed = f"{dex_prefix}:{base}"

    # Dynamically infer tick sizes from the live order book.
    amount_tick = 0.01
    price_tick = 0.01
    try:
        data = _fetch_l2book(prefixed)
        levels = data.get("levels", [])
        entries = (levels[0] if levels else []) + (levels[1] if len(levels) > 1 else [])
        if entries:
            amount_tick = _infer_tick([e["sz"] for e in entries])
            price_tick = _infer_tick([e["px"] for e in entries])
    except Exception:
        pass  # fall back to defaults

    exchange.markets[symbol] = {
        "id": prefixed,
        "symbol": symbol,
        "base": base,
        "quote": quote,
        "settle": quote,
        "baseId": prefixed,
        "quoteId": quote,
        "settleId": quote,
        "type": "swap",
        "spot": False,
        "margin": False,
        "swap": True,
        "future": False,
        "option": False,
        "active": True,
        "contract": True,
        "linear": True,
        "inverse": False,
        "taker": 0.00035,
        "maker": 0.0001,
        "contractSize": 1,
        "expiry": None,
        "expiryDatetime": None,
        "strike": None,
        "optionType": None,
        "precision": {"amount": amount_tick, "price": price_tick, "cost": None, "base": None, "quote": None},
        "limits": {
            "leverage": {"min": 1, "max": 50},
            "amount": {"min": amount_tick, "max": None},
            "price": {"min": None, "max": None},
            "cost": {"min": None, "max": None},
        },
        "info": {"name": prefixed},
    }


def get_hip3_ohlcv(coin: str, timeframe: str, limit: int) -> pd.DataFrame:
    """
    Fetch OHLCV for a HIP-3 coin (e.g. 'xyz:CL', 'cash:AMZN') via the
    Hyperliquid candleSnapshot API.

    Returns a DataFrame with columns [open, high, low, close, volume] and
    a UTC DatetimeIndex, sorted oldest-first — same contract as CcxtAdapter.get_ohlcv.
    """
    interval_ms = _INTERVAL_MS.get(timeframe, 3_600_000)
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - limit * interval_ms

    resp = requests.post(
        _HL_INFO_URL,
        json={"type": "candleSnapshot", "req": {"coin": coin, "interval": timeframe, "startTime": start_ms, "endTime": end_ms}},
        timeout=10,
    )
    resp.raise_for_status()
    candles = resp.json()

    if not candles:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    df = pd.DataFrame(candles)
    df.index = pd.to_datetime(df["t"], unit="ms", utc=True)
    df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    return df[["open", "high", "low", "close", "volume"]].astype(float).sort_index()


def get_hip3_top_coins(deployer_address: str, perp_suffix: str, n: int, quote: str = "USDC", symbol_prefix: str = "") -> list[str]:
    """
    Return top N symbols for a HIP-3 DEX, ranked by open interest cap.

    Parameters
    ----------
    deployer_address : str
        The HIP-3 DEX deployer address (from perpDexs API).
    perp_suffix : str
        CCXT perp suffix for this exchange, e.g. ":USDC" or ":USDT0".
    n : int
        Maximum number of symbols to return.
    quote : str
        Quote/settle currency for the symbol, e.g. "USDC" or "USDT0".
    symbol_prefix : str
        CCXT symbol prefix for this DEX, e.g. "XYZ-" or "CASH-".
        CCXT uses prefixed names like "XYZ-CL/USDC:USDC" for HIP-3 markets.
    """
    resp = requests.post(_HL_INFO_URL, json={"type": "perpDexs"}, timeout=10)
    resp.raise_for_status()
    dexs = resp.json()

    dex = next(
        (d for d in dexs if d and d.get("deployer", "").lower() == deployer_address.lower()),
        None,
    )
    if not dex:
        return []

    # OI cap per asset (strip DEX prefix: "xyz:NVDA" → "NVDA")
    oi_caps: dict[str, float] = {
        k.split(":", 1)[1]: float(v)
        for k, v in dex.get("assetToStreamingOiCap", [])
    }

    # Funding multiplier list covers all listed assets (more complete than OI cap list)
    all_assets: set[str] = set(oi_caps)
    for k, _ in dex.get("assetToFundingMultiplier", []):
        all_assets.add(k.split(":", 1)[1])

    # Rank by OI cap descending; assets missing from cap list get 0
    ranked = sorted(all_assets, key=lambda a: oi_caps.get(a, 0.0), reverse=True)

    # Build CCXT-native symbol: "XYZ-NVDA/USDC:USDC" or "CASH-WTI/USDT0:USDT0"
    return [f"{symbol_prefix}{asset}/{quote}{perp_suffix}" for asset in ranked[:n]]
