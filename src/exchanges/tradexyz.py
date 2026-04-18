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

from src.exchanges.ccxt_base import CcxtAdapter
from src.exchanges.hyperliquid import HyperliquidAdapter

if TYPE_CHECKING:
    from src.config_loader import Config

_XYZ_BUILDER = "0x88806a71D74ad0a510b350545C9aE490912F0888"


class TradeXYZAdapter(HyperliquidAdapter):
    """
    TradeXYZ adapter — inherits all Hyperliquid logic.
    Calls CcxtAdapter.__init__ directly to supply TradeXYZ credentials
    instead of Hyperliquid credentials.
    Builder address is public and hardcoded; override via TRADEXYZ_BUILDER_CODE if needed.
    """

    def __init__(self, config: "Config") -> None:
        CcxtAdapter.__init__(
            self,
            api_key=config.secrets.tradexyz_api_key,
            api_secret=config.secrets.tradexyz_api_secret,
            builder_code=config.secrets.tradexyz_builder_code or _XYZ_BUILDER,
        )