"""
Exchange plugin registry.

To add a new exchange:
  1. Create src/exchanges/myexchange.py implementing ExchangeAdapter
  2. Import it here and add an entry to REGISTRY
  3. Add credentials to .env
  4. Set EXCHANGE=myexchange in .env or config.yaml
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.exchanges.dreamcash import DreamCashAdapter
from src.exchanges.hibachi import HibachiAdapter
from src.exchanges.hyperliquid import HyperliquidAdapter
from src.exchanges.tradexyz import TradeXYZAdapter

if TYPE_CHECKING:
    from src.config_loader import Config
    from src.exchanges.base import ExchangeAdapter

REGISTRY: dict[str, type[ExchangeAdapter]] = {
    "hyperliquid": HyperliquidAdapter,
    "tradexyz": TradeXYZAdapter,
    "dreamcash": DreamCashAdapter,
    "hibachi": HibachiAdapter,
}


def get_adapter(exchange_name: str, config: "Config") -> "ExchangeAdapter":
    """
    Instantiate and return the adapter for the given exchange name.
    Raises ValueError for unknown exchanges.
    """
    cls = REGISTRY.get(exchange_name.lower())
    if cls is None:
        raise ValueError(
            f"Unknown exchange: '{exchange_name}'. "
            f"Available: {sorted(REGISTRY.keys())}"
        )
    return cls(config)
