# Project Overview

Multi-exchange perpetual futures trading bot targeting HIP-3 DEX airdrop farming on Hyperliquid.

## Exchanges

| Exchange | Markets | Collateral | Builder Fee for XP |
|----------|---------|-----------|-------------------|
| TradeXYZ | `XYZ-*` HIP-3 perps | USDC | — |
| DreamCash | `CASH-*` HIP-3 perps | USDT | 0.02% (0.5 XP/$) or 0.045% (1 XP/$) |
| Hibachi | Crypto perps | USDT | — |

## Strategy

- **Signal:** EMA 12/26 trend filter on 1h
- **Direction:** Long only
- **Risk per trade:** 0.2% of balance
- **SL/TP:** 1.0× ATR each (1:1 R:R)
- **Max concurrent:** 5 per exchange

## Architecture

```
src/
├── exchanges/          # Exchange adapters
│   ├── base.py         # Abstract contract
│   ├── ccxt_base.py    # CCXT-backed base
│   ├── _hip3.py        # HIP-3 market discovery
│   ├── hyperliquid.py
│   ├── tradexyz.py
│   ├── dreamcash.py
│   └── hibachi.py
├── indicators/         # Pure technical indicator functions
│   ├── ema.py
│   └── atr.py
├── risk/               # Position sizing & SL/TP math
│   └── sizing.py
├── strategy/           # Signal generation
│   └── trend_filter.py
├── config_loader.py    # Config + secrets loading
├── main.py             # Orchestrator / trading loop
├── lambda_handler.py   # AWS Lambda entry point
├── health.py           # Full health server
├── health_server.py    # Minimal health server
└── logging_config.py   # JSON logging setup
```

## Run

```bash
# Local dry run
DRY_RUN=true python -m src.main

# Tests
pytest tests/

# Docker
docker compose up
```

## Deploy

### Lambda (default)
```bash
python scripts/build_lambda.py
python scripts/deploy_lambda.py
```

GitHub Actions auto-deploys on push to `main`.

### ECS (legacy)
See `docker-compose.yml` and `task-definition.json`.

## Key Files

| File | Purpose |
|------|---------|
| `config/config.yaml` | Runtime parameters |
| `.env` | Secrets (gitignored) |
| `LAMBDA_SETUP.md` | Beginner AWS setup guide |
| `CLAUDE.md` | Project context for AI agents |

## Docs Index

- [`exchanges.md`](exchanges.md) — Adapter architecture & credentials
- [`indicators.md`](indicators.md) — EMA & ATR
- [`risk.md`](risk.md) — Position sizing & SL/TP
- [`strategy.md`](strategy.md) — Trend filter signal
- [`config.md`](config.md) — Configuration loading
- [`main.md`](main.md) — Orchestrator & entry points
- [`DREAMCASH_BUILDER_FEE_FIX.md`](DREAMCASH_BUILDER_FEE_FIX.md) — Post-mortem for builder fee bug
