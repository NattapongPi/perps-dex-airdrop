"""
Single source of truth for all configuration.

Loading order (later overrides earlier):
  1. config/config.yaml   — runtime parameters
  2. .env file            — secrets and env overrides
  3. OS environment vars  — highest priority (e.g. set in Docker / cloud)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# Load .env first, then .env.local overrides (local file is gitignored)
load_dotenv(override=False)
load_dotenv(".env.local", override=True)

# Support injecting all secrets as a single JSON env var (ECS full-secret injection)
_SECRETS: dict = json.loads(os.environ.get("SECRETS_JSON", "{}"))

_DEBUG_KEYS = ["HIBACHI_API_KEY", "HYPERLIQUID_WALLET_ADDRESS", "SECRETS_JSON"]
print("ENV_DEBUG:", {k: ("PRESENT" if os.environ.get(k) else "ABSENT") for k in _DEBUG_KEYS})

def _secret(key: str) -> str:
    return _SECRETS.get(key) or os.environ.get(key, "")

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.yaml"


# ---------------------------------------------------------------------------
# Dataclasses mirroring config.yaml structure
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScanConfig:
    top_n: int
    timeframe: str
    ohlcv_limit: int


@dataclass(frozen=True)
class StrategyConfig:
    type: str
    ema_fast: int
    ema_slow: int


@dataclass(frozen=True)
class RiskConfig:
    risk_pct: float
    atr_period: int
    atr_sl_multiplier: float
    atr_tp_multiplier: float
    min_sl_pct: float = 0.0


@dataclass(frozen=True)
class PositionConfig:
    max_concurrent: int
    clear_positions_on_startup: bool = False


@dataclass(frozen=True)
class LoggingConfig:
    level: str


@dataclass(frozen=True)
class SecretsConfig:
    # Hyperliquid
    hyperliquid_api_key: str        # wallet address (kept as api_key for adapter compat)
    hyperliquid_api_secret: str     # private key (kept as api_secret for adapter compat)
    hyperliquid_builder_code: str
    # Hibachi
    hibachi_api_key: str
    hibachi_account_id: str
    hibachi_private_key: str
    # TradeXYZ (HIP-3 DEX on Hyperliquid — same API, different builder code)
    tradexyz_api_key: str        # wallet address
    tradexyz_api_secret: str     # private key
    tradexyz_builder_code: str   # TradeXYZ builder address
    # DreamCash (Hyperliquid-based — builder: 0x4950994884602d1b6c6d96e4fe30f58205c39395)
    dreamcash_api_key: str       # wallet address
    dreamcash_api_secret: str    # private key
    dreamcash_builder_code: str  # override if needed; adapter defaults to official address
    # Dango (custom L1, secp256k1 signing — shares same Hyperliquid wallet)
    dango_wallet_address: str    # 0x... Ethereum-style wallet address
    dango_private_key: str       # 0x... secp256k1 private key


@dataclass(frozen=True)
class Config:
    exchanges: list[str]
    per_exchange: dict[str, dict]
    scan: ScanConfig
    strategy: StrategyConfig
    risk: RiskConfig
    position: PositionConfig
    logging: LoggingConfig
    secrets: SecretsConfig
    dry_run: bool = False  # Set DRY_RUN=true in .env to log orders without placing them


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _get(d: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Nested dict accessor with a default fallback."""
    for key in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(key, default)  # type: ignore[assignment]
    return d


def load_config(config_path: Path = _CONFIG_PATH) -> Config:
    """
    Load and validate configuration. Raises ValueError on missing required
    secrets so the bot fails fast at startup rather than mid-run.
    """
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}\n"
            f"Copy config/config.yaml.example to config/config.yaml and fill it in."
        )

    with config_path.open() as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    exchanges_raw: list[Any] = raw.get("exchanges", [])
    if not exchanges_raw:
        raise ValueError("No exchanges configured. Set 'exchanges' in config.yaml.")

    parsed_exchanges: list[str] = []
    per_exchange: dict[str, dict] = {}

    for item in exchanges_raw:
        if isinstance(item, str):
            parsed_exchanges.append(item.lower())
        elif isinstance(item, dict):
            for name, overrides in item.items():
                parsed_exchanges.append(name.lower())
                per_exchange[name.lower()] = overrides or {}

    scan_raw = raw.get("scan", {})
    strategy_raw = raw.get("strategy", {})
    risk_raw = raw.get("risk", {})
    position_raw = raw.get("position", {})
    logging_raw = raw.get("logging", {})

    dry_run = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes") or bool(raw.get("dry_run", False))

    # Build secrets first so we can filter exchanges before constructing Config.
    secrets = SecretsConfig(
        hyperliquid_api_key=_secret("HYPERLIQUID_WALLET_ADDRESS"),
        hyperliquid_api_secret=_secret("HYPERLIQUID_PRIVATE_KEY"),
        hyperliquid_builder_code=_secret("HYPERLIQUID_BUILDER_CODE"),
        hibachi_api_key=_secret("HIBACHI_API_KEY"),
        hibachi_account_id=_secret("HIBACHI_ACCOUNT_ID"),
        hibachi_private_key=_secret("HIBACHI_PRIVATE_KEY"),
        tradexyz_api_key=_secret("HYPERLIQUID_WALLET_ADDRESS"),
        tradexyz_api_secret=_secret("HYPERLIQUID_PRIVATE_KEY"),
        tradexyz_builder_code=_secret("TRADEXYZ_BUILDER_CODE"),
        dreamcash_api_key=_secret("HYPERLIQUID_WALLET_ADDRESS"),
        dreamcash_api_secret=_secret("HYPERLIQUID_PRIVATE_KEY"),
        dreamcash_builder_code=_secret("DREAMCASH_BUILDER_CODE"),
        dango_wallet_address=_secret("DANGO_WALLET_ADDRESS") or _secret("HYPERLIQUID_WALLET_ADDRESS"),
        dango_private_key=_secret("DANGO_PRIVATE_KEY") or _secret("HYPERLIQUID_PRIVATE_KEY"),
    )

    # Skip any exchange whose required secrets are missing (warn, don't crash).
    active_exchanges: list[str] = []
    for name in parsed_exchanges:
        missing = [
            f for f in _REQUIRED_SECRETS.get(name, [])
            if not getattr(secrets, f, "")
        ]
        if missing:
            print(f"WARNING: Skipping exchange '{name}' — missing credentials: {missing}")
        else:
            active_exchanges.append(name)

    config = Config(
        exchanges=active_exchanges,
        per_exchange={k: v for k, v in per_exchange.items() if k in active_exchanges},
        dry_run=dry_run,
        scan=ScanConfig(
            top_n=int(scan_raw.get("top_n", 20)),
            timeframe=str(scan_raw.get("timeframe", "1h")),
            ohlcv_limit=int(scan_raw.get("ohlcv_limit", 100)),
        ),
        strategy=StrategyConfig(
            type=str(strategy_raw.get("type", "ema_trend_filter")),
            ema_fast=int(strategy_raw.get("ema_fast", 12)),
            ema_slow=int(strategy_raw.get("ema_slow", 26)),
        ),
        risk=RiskConfig(
            risk_pct=float(risk_raw.get("risk_pct", 1.0)),
            atr_period=int(risk_raw.get("atr_period", 14)),
            atr_sl_multiplier=float(risk_raw.get("atr_sl_multiplier", 1.5)),
            atr_tp_multiplier=float(risk_raw.get("atr_tp_multiplier", 2.0)),
            min_sl_pct=float(risk_raw.get("min_sl_pct", 0.0)),
        ),
        position=PositionConfig(
            max_concurrent=int(position_raw.get("max_concurrent", 10)),
            clear_positions_on_startup=bool(position_raw.get("clear_positions_on_startup", False)),
        ),
        logging=LoggingConfig(
            level=str(logging_raw.get("level", "INFO")).upper(),
        ),
        secrets=secrets,
    )

    _validate(config)
    return config


_REQUIRED_SECRETS: dict[str, list[str]] = {
    "hyperliquid": ["hyperliquid_api_key", "hyperliquid_api_secret"],
    "tradexyz":    ["tradexyz_api_key", "tradexyz_api_secret"],   # shares HL wallet
    "dreamcash":   ["dreamcash_api_key", "dreamcash_api_secret"], # shares HL wallet
    "hibachi":     ["hibachi_api_key", "hibachi_account_id", "hibachi_private_key"],
    "dango":       ["dango_wallet_address", "dango_private_key"],
}


def _validate(config: Config) -> None:
    """Fail fast on obvious misconfiguration."""
    from src.exchanges import REGISTRY  # avoid circular import at module level

    for name in config.exchanges:
        if name not in REGISTRY:
            raise ValueError(
                f"Unknown exchange '{name}'. "
                f"Available: {sorted(REGISTRY.keys())}"
            )

    if config.strategy.ema_fast >= config.strategy.ema_slow:
        raise ValueError(
            f"ema_fast ({config.strategy.ema_fast}) must be less than "
            f"ema_slow ({config.strategy.ema_slow})"
        )

    if config.risk.risk_pct <= 0 or config.risk.risk_pct > 100:
        raise ValueError(f"risk_pct must be between 0 and 100, got {config.risk.risk_pct}")
