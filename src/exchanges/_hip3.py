"""
HIP-3 DEX market discovery and OHLCV for Hyperliquid.

Queries the `perpDexs` endpoint to find all markets listed by a specific
HIP-3 DEX (identified by its deployer address), then ranks them by OI cap.

OHLCV uses the Hyperliquid `candleSnapshot` API directly (bypassing CCXT's
market validation, which rejects HIP-3 symbols not in the standard markets list).
"""

from __future__ import annotations

import time

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


def get_hip3_top_coins(deployer_address: str, perp_suffix: str, n: int) -> list[str]:
    """
    Return top N symbols for a HIP-3 DEX, ranked by open interest cap.

    Parameters
    ----------
    deployer_address : str
        The HIP-3 DEX deployer address (from perpDexs API).
    perp_suffix : str
        CCXT perp suffix for this exchange, e.g. ":USDC".
    n : int
        Maximum number of symbols to return.
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

    # Build CCXT symbol: "NVDA/USDC:USDC"
    return [f"{asset}/USDC{perp_suffix}" for asset in ranked[:n]]
