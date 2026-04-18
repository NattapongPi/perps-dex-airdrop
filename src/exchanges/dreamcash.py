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

from src.exchanges.ccxt_base import CcxtAdapter
from src.exchanges.hyperliquid import HyperliquidAdapter

if TYPE_CHECKING:
    from src.config_loader import Config

# DreamCash official builder address — earns XP rewards for developers
_DREAMCASH_BUILDER = "0x4950994884602d1b6c6d96e4fe30f58205c39395"


class DreamCashAdapter(HyperliquidAdapter):
    """
    DreamCash adapter — inherits all Hyperliquid logic.
    Calls CcxtAdapter.__init__ directly to supply DreamCash credentials.
    Builder code defaults to the official DreamCash address if not overridden.
    """

    def __init__(self, config: "Config") -> None:
        CcxtAdapter.__init__(
            self,
            api_key=config.secrets.dreamcash_api_key,
            api_secret=config.secrets.dreamcash_api_secret,
            builder_code=config.secrets.dreamcash_builder_code or _DREAMCASH_BUILDER,
        )
