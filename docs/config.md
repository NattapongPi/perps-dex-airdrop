# Configuration

Single source of truth: `src/config_loader.py`.

## Loading Priority (later overrides earlier)

1. `config/config.yaml` — runtime parameters
2. `.env` file — secrets and env overrides
3. `.env.local` — local overrides (gitignored)
4. OS environment variables — highest priority (Lambda, Docker, etc.)

## Secrets

Supports two injection modes:

### Individual env vars
```bash
HYPERLIQUID_WALLET_ADDRESS=0x...
HYPERLIQUID_PRIVATE_KEY=0x...
DREAMCASH_BUILDER_CODE=0x...
```

### Bulk JSON (`SECRETS_JSON`)
For ECS/Lambda full-secret injection:
```bash
SECRETS_JSON='{"HYPERLIQUID_WALLET_ADDRESS":"0x...","HYPERLIQUID_PRIVATE_KEY":"0x..."}'
```

## Dataclasses

| Class | Fields |
|-------|--------|
| `ScanConfig` | `top_n, timeframe, ohlcv_limit` |
| `StrategyConfig` | `ema_fast, ema_slow, atr_period` |
| `RiskConfig` | `risk_pct, atr_sl_multiplier, atr_tp_multiplier` |
| `PositionConfig` | `max_concurrent` |
| `LoggingConfig` | `level` |
| `SecretsConfig` | All API keys, private keys, builder codes |
| `Config` | Container holding all above + `dry_run: bool` |

## Secret Sharing

| Exchange | Falls back to... |
|----------|-----------------|
| TradeXYZ | Hyperliquid wallet if `TRADEXYZ_*` blank |
| DreamCash | Hyperliquid wallet if `DREAMCASH_*` blank |
| Dango | Hyperliquid wallet if `DANGO_*` blank |

## Exchange Filtering

Exchanges with missing required secrets are **skipped with a warning** (non-fatal). No crash.

## Validation

- Unknown exchange names → `ValueError`
- `ema_fast >= ema_slow` → `ValueError`
- `risk_pct <= 0 or risk_pct > 100` → `ValueError`

## Example `config/config.yaml`

```yaml
exchanges:
  - dreamcash:
      position:
        max_concurrent: 5
      scan:
        top_n: 10
      risk:
        risk_pct: 0.1
  - hibachi

strategy:
  ema_fast: 12
  ema_slow: 26
  atr_period: 14

risk:
  risk_pct: 0.2
  atr_sl_multiplier: 1.0
  atr_tp_multiplier: 1.0

position:
  max_concurrent: 5

logging:
  level: INFO
```
