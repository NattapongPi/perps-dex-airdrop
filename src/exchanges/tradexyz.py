"""
TradeXYZ exchange adapter.

TradeXYZ is a HIP-3 DEX built on Hyperliquid — it uses the exact same
Hyperliquid API (same endpoints, same auth, same order format).
The only difference from HyperliquidAdapter is the builder code and credentials.

All trading logic is inherited from HyperliquidAdapter → CcxtAdapter.

XYZ Protocol metadata (from docs.trade.xyz):
  Deployer:       0x88806a71D74ad0a510b350545C9aE490912F0888
  Oracle Updater: 0x1234567890545d1Df9EE64B35Fdd16966e08aCEC

Auth fields in .env:
  TRADEXYZ_WALLET_ADDRESS — 0x... wallet address
  TRADEXYZ_PRIVATE_KEY    — 0x... private key for signing
  TRADEXYZ_BUILDER_CODE   — optional override (defaults to _XYZ_BUILDER below)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from src.exchanges._hip3 import ensure_hip3_market, get_hip3_mid_price, get_hip3_ohlcv, get_hip3_top_coins
from src.exchanges.ccxt_base import CcxtAdapter
from src.exchanges.hyperliquid import HyperliquidAdapter

if TYPE_CHECKING:
    from src.config_loader import Config

_XYZ_BUILDER = "0x88806a71D74ad0a510b350545C9aE490912F0888"
# Deployer == builder for TradeXYZ
_XYZ_DEPLOYER = _XYZ_BUILDER


class TradeXYZAdapter(HyperliquidAdapter):
    """
    TradeXYZ adapter — inherits all Hyperliquid logic.
    Overrides get_top_coins() to return only xyz-tagged HIP-3 markets.
    """

    def __init__(self, config: "Config") -> None:
        CcxtAdapter.__init__(
            self,
            api_key=config.secrets.tradexyz_api_key,
            api_secret=config.secrets.tradexyz_api_secret,
            builder_code=config.secrets.tradexyz_builder_code or _XYZ_BUILDER,
        )

    def get_top_coins(self, n: int) -> list[str]:
        return get_hip3_top_coins(_XYZ_DEPLOYER, self.PERP_SUFFIX, n, quote=self.QUOTE_CURRENCY)

    def get_ohlcv(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        base = symbol.split("/")[0]  # "CL" from "CL/USDC:USDC"
        return get_hip3_ohlcv(f"xyz:{base}", timeframe, limit)

    def _get_market_price(self, symbol: str) -> float:
        base = symbol.split("/")[0]
        return get_hip3_mid_price(f"xyz:{base}")

    def place_order(self, symbol: str, side: str, size: float, tp_pct: float, sl_pct: float):
        ensure_hip3_market(self._exchange, symbol, "xyz")
        return super().place_order(symbol, side, size, tp_pct, sl_pct)