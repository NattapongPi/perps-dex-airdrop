# airdrop-bot

Perpetual futures trading bot targeting HIP-3 DEX airdrop farming on Hyperliquid.
Trades TradeXYZ, DreamCash, and Hibachi. Runs hourly via cron on ECS Fargate.

## Strategy

EMA trend filter (12/26 on 1h) → long only → ATR-based SL/TP (1:1 R:R).
Position size: `(balance × risk_pct%) / (entry × sl_pct)`. Independent of leverage.

## Exchanges

| Exchange | Markets | Notes |
|----------|---------|-------|
| TradeXYZ | `XYZ-*` HIP-3 perps (USDC) | Isolated, max 10x |
| DreamCash | `CASH-*` HIP-3 perps (USDT) | Isolated, max 10x, 0.045% builder fee for XP |
| Hibachi | Crypto perps (USDT) | Separate API keys. See caution below. |

All three can share one Hyperliquid wallet. Missing credentials = exchange skipped automatically.

> **⚠️ Hibachi — orphan orders:** Unlike Hyperliquid-based DEXes, Hibachi does not
> auto-cancel reduce-only orders when a position closes. The bot cleans up orphan
> TP/SL orders at the **start of the next scan** (~1h later). If price revisits the
> orphan TP level before cleanup, it will fill and open an unwanted new position.
> Monitor open orders manually after an SL hit.

## Setup

```bash
cp .env.example .env
# fill in your credentials
pip install -r requirements.txt
python -m src.main
```

**.env keys:**
```
HYPERLIQUID_WALLET_ADDRESS=0x...   # used by TradeXYZ + DreamCash
HYPERLIQUID_PRIVATE_KEY=0x...

HIBACHI_API_KEY=...
HIBACHI_ACCOUNT_ID=...
HIBACHI_PRIVATE_KEY=0x...

# Optional overrides
TRADEXYZ_BUILDER_CODE=0x...
DREAMCASH_BUILDER_CODE=0x...
DRY_RUN=true                       # log orders without placing them
```

Only set what you need — any exchange with missing credentials is silently skipped.

## Config

`config/config.yaml` controls everything. Per-exchange overrides are supported:

```yaml
exchanges:
  - tradexyz:
      position:
        max_concurrent: 10
      scan:
        top_n: 10
      risk:
        risk_pct: 0.1
  - hibachi         # uses global defaults

risk:
  risk_pct: 0.2
  atr_sl_multiplier: 1.0
  atr_tp_multiplier: 1.0
```

## Run

```bash
# local (dry run)
DRY_RUN=true python -m src.main

# docker
docker compose up

# tests
pytest tests/
```

## Deploy

Push to `main` → GitHub Actions → Docker build → ECR → ECS force-redeploy.

```bash
git push  # that's it
```

Runs on ECS Fargate (ap-southeast-1). Cron: `3 * * * *` inside container.
Logs: CloudWatch → `/ecs/airdrop-bot`.

## Project structure

```
src/
  exchanges/
    ccxt_base.py      # shared CCXT adapter (order placement, positions, balance)
    hyperliquid.py    # Hyperliquid native
    tradexyz.py       # HIP-3, XYZ-* markets
    dreamcash.py      # HIP-3, CASH-* markets
    hibachi.py        # Hibachi exchange
    _hip3.py          # HIP-3 market discovery via perpDexs API
  strategy/
    trend_filter.py   # EMA signal + ATR calculation
  risk/
    sizing.py         # position sizing, SL/TP price calculation
  config_loader.py    # loads config.yaml + .env, skips unconfigured exchanges
  main.py             # orchestrator — one scan loop per run
```

## Adding an exchange

1. Subclass `CcxtAdapter` (or `HyperliquidAdapter` for HL-based DEXes)
2. Set `CCXT_ID`, `QUOTE_CURRENCY`, `PERP_SUFFIX`
3. Register in `src/exchanges/__init__.py`
4. Add credentials to `.env` and the exchange to `config.yaml`
