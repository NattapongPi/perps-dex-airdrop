"""
HIP-3 DEX market discovery for Hyperliquid.

Queries the `perpDexs` endpoint to find all markets listed by a specific
HIP-3 DEX (identified by its deployer address), then ranks them by OI cap.
"""

from __future__ import annotations

import requests

_HL_INFO_URL = "https://api.hyperliquid.xyz/info"


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
