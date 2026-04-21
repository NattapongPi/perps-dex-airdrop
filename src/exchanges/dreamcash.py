"""
DreamCash exchange adapter.

DreamCash is a trading interface built on Hyperliquid — it uses the same
Hyperliquid API directly (POST https://api.hyperliquid.xyz/exchange).
The only difference from HyperliquidAdapter is the builder code and credentials.

Builder address: 0x4950994884602d1b6c6d96e4fe30f58205c39395
Required builder fee: 0.02% or 0.045% (set DREAMCASH_BUILDER_FEE_BPS in .env).
Source: https://www.dreamcash.xyz/build

All trading logic is inherited from HyperliquidAdapter → CcxtAdapter.

CCXT symbol format: "CASH-WTI/USDT0:USDT0"  (CCXT knows CASH-* markets natively
                                               with correct integer baseId — no
                                               synthetic market injection needed)
API coin format:    "cash:WTI"               (used for OHLCV and price lookups)
Balance currency:   "USDT"                   (fetch_balance returns "USDT" key)

Auth fields in .env:
  DREAMCASH_WALLET_ADDRESS — 0x... wallet address
  DREAMCASH_PRIVATE_KEY    — 0x... private key for signing
  DREAMCASH_BUILDER_CODE   — override if DreamCash changes their builder address
                             (default: 0x4950994884602d1b6c6d96e4fe30f58205c39395)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from src.exchanges._hip3 import get_hip3_mid_price, get_hip3_ohlcv, get_hip3_top_coins
from src.exchanges.ccxt_base import CcxtAdapter
from src.exchanges.hyperliquid import HyperliquidAdapter

if TYPE_CHECKING:
    from src.config_loader import Config

# Builder code for fee attribution (goes into CCXT broker option)
_DREAMCASH_BUILDER = "0x4950994884602d1b6c6d96e4fe30f58205c39395"
# Deployer address for HIP-3 market discovery (from perpDexs API — differs from builder)
_DREAMCASH_DEPLOYER = "0xffa8198c62adb1e811629bd54c9b646d726deef7"

# CCXT-native symbol prefix and quote for CASH HIP-3 markets
# e.g. "CASH-WTI/USDT0:USDT0" — note USDT0 in symbol, USDT in balance
_CASH_SYMBOL_PREFIX = "CASH-"
_CASH_SYMBOL_QUOTE = "USDT0"
_CASH_PERP_SUFFIX = ":USDT0"


class DreamCashAdapter(HyperliquidAdapter):
    """
    DreamCash adapter — inherits all Hyperliquid logic.
    Overrides get_top_coins(), get_ohlcv(), and _get_market_price() for HIP-3.

    CCXT knows DreamCash markets natively as "CASH-WTI/USDT0:USDT0" with correct
    integer baseIds (e.g. 170012 for WTI), so no synthetic market injection is
    needed and place_order() is inherited unchanged from CcxtAdapter.

    Note: CCXT market symbols use "USDT0"; fetch_balance() returns "USDT".
    """

    # QUOTE_CURRENCY is used by get_balance() — balance is returned as "USDT"
    QUOTE_CURRENCY = "USDT"
    # PERP_SUFFIX is used only if the base get_top_coins() were called — we override it
    PERP_SUFFIX = _CASH_PERP_SUFFIX
    # Required so fetch_positions queries the CASH DEX clearinghouse, not standard HL
    POSITIONS_DEX = "cash"

    def __init__(self, config: "Config") -> None:
        CcxtAdapter.__init__(
            self,
            api_key=config.secrets.dreamcash_api_key,
            api_secret=config.secrets.dreamcash_api_secret,
            builder_code=config.secrets.dreamcash_builder_code or _DREAMCASH_BUILDER,
            builder_fee=0.00045,  # 0.045% — earns 1 XP per $ traded on DreamCash
        )

    def get_top_coins(self, n: int) -> list[str]:
        # Returns CCXT-native symbols, e.g. "CASH-WTI/USDT0:USDT0"
        return get_hip3_top_coins(
            _DREAMCASH_DEPLOYER, _CASH_PERP_SUFFIX, n, quote=_CASH_SYMBOL_QUOTE, symbol_prefix=_CASH_SYMBOL_PREFIX
        )

    def get_ohlcv(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        # "CASH-WTI/USDT0:USDT0" → strip DEX prefix → "WTI" → API coin "cash:WTI"
        base = symbol.split("/")[0].split("-", 1)[-1]
        return get_hip3_ohlcv(f"cash:{base}", timeframe, limit)

    def _get_market_price(self, symbol: str) -> float:
        base = symbol.split("/")[0].split("-", 1)[-1]
        return get_hip3_mid_price(f"cash:{base}")

    def place_order(self, symbol: str, side: str, size: float, tp_pct: float, sl_pct: float):
        # CASH HIP-3 assets only support isolated margin (cross is rejected by Hyperliquid).
        # Set isolated leverage capped at 10x before entry — ATR-based SL limits real risk.
        market = self._exchange.market(symbol)
        max_lev = int((market.get("limits") or {}).get("leverage", {}).get("max") or 1)
        leverage = min(max_lev, 10)
        self._exchange.set_leverage(leverage, symbol, params={"marginMode": "isolated"})
        return super().place_order(symbol, side, size, tp_pct, sl_pct)
