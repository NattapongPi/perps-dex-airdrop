"""
Hyperliquid exchange adapter.

Thin subclass of CcxtAdapter — all trading logic lives in the base class.
Only declares the CCXT exchange ID, quote currency, and reads credentials.

Auth fields in .env:
  HYPERLIQUID_WALLET_ADDRESS  — 0x... wallet address
  HYPERLIQUID_PRIVATE_KEY     — 0x... private key for signing
  HYPERLIQUID_BUILDER_CODE    — 0x... builder address (fee-share program)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.exchanges.ccxt_base import CcxtAdapter

if TYPE_CHECKING:
    from src.config_loader import Config


class HyperliquidAdapter(CcxtAdapter):

    CCXT_ID = "hyperliquid"
    QUOTE_CURRENCY = "USDC"
    PERP_SUFFIX = ":USDC"

    def __init__(self, config: "Config") -> None:
        super().__init__(
            api_key=config.secrets.hyperliquid_api_key,
            api_secret=config.secrets.hyperliquid_api_secret,
            builder_code=config.secrets.hyperliquid_builder_code,
        )
