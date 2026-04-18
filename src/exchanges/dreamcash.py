"""
DreamCash exchange adapter.

DreamCash is a trading interface built on Hyperliquid — it uses the same
Hyperliquid API directly (POST https://api.hyperliquid.xyz/exchange).
The only difference from HyperliquidAdapter is the builder code and credentials.

Builder address: 0x4950994884602d1b6c6d96e4fe30f58205c39395
Required builder fee: 0.02% or 0.045% (set DREAMCASH_BUILDER_FEE_BPS in .env).
Source: https://www.dreamcash.xyz/build

All trading logic is inherited from HyperliquidAdapter → CcxtAdapter.

Auth fields in .env:
  DREAMCASH_WALLET_ADDRESS — 0x... wallet address
  DREAMCASH_PRIVATE_KEY    — 0x... private key for signing
  DREAMCASH_BUILDER_CODE   — override if DreamCash changes their builder address
                             (default: 0x4950994884602d1b6c6d96e4fe30f58205c39395)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.exchanges._hip3 import get_hip3_top_coins
from src.exchanges.ccxt_base import CcxtAdapter
from src.exchanges.hyperliquid import HyperliquidAdapter

if TYPE_CHECKING:
    from src.config_loader import Config

# Builder code for fee attribution (goes into CCXT broker option)
_DREAMCASH_BUILDER = "0x4950994884602d1b6c6d96e4fe30f58205c39395"
# Deployer address for HIP-3 market discovery (from perpDexs API — differs from builder)
_DREAMCASH_DEPLOYER = "0xffa8198c62adb1e811629bd54c9b646d726deef7"


class DreamCashAdapter(HyperliquidAdapter):
    """
    DreamCash adapter — inherits all Hyperliquid logic.
    Overrides get_top_coins() to return only cash-tagged HIP-3 markets.
    """

    def __init__(self, config: "Config") -> None:
        CcxtAdapter.__init__(
            self,
            api_key=config.secrets.dreamcash_api_key,
            api_secret=config.secrets.dreamcash_api_secret,
            builder_code=config.secrets.dreamcash_builder_code or _DREAMCASH_BUILDER,
        )

    def get_top_coins(self, n: int) -> list[str]:
        return get_hip3_top_coins(_DREAMCASH_DEPLOYER, self.PERP_SUFFIX, n)
