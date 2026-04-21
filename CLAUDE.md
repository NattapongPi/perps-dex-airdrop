# Airdrop Trading Bot — Claude Context

## What this is
Multi-exchange perpetual futures trading bot targeting HIP-3 DEX airdrop farming.
Trades on TradeXYZ (xyz-tagged markets), DreamCash (cash-tagged markets), and Hibachi.
Hyperliquid direct is intentionally excluded — only HIP-3 front-ends.

## Strategy
- **Signal**: EMA trend filter (EMA 12/26 on 1h OHLCV)
- **Sizing**: ATR-based — `size = (balance × risk_pct/100) / (ATR × sl_multiplier)`
- **Risk per trade**: 0.2% of balance
- **SL/TP**: 1.0 × ATR each (1:1 R:R)
- **Max concurrent positions**: 5 per exchange

## Exchange details

| Exchange | Markets | Deployer address |
|----------|---------|-----------------|
| TradeXYZ | xyz-tagged HIP-3 | `0x88806a71D74ad0a510b350545C9aE490912F0888` |
| DreamCash | cash-tagged HIP-3 | `0xffa8198c62adb1e811629bd54c9b646d726deef7` |
| Hibachi | Hibachi perps (normal scan) | n/a |

**Critical**: DreamCash deployer ≠ builder code. Builder = `0x4950994884602d1b6c6d96e4fe30f58205c39395`, Deployer = `0xffa8198c...`. Market discovery uses deployer; fee attribution uses builder.

HIP-3 market discovery uses `POST https://api.hyperliquid.xyz/info {"type":"perpDexs"}` — NOT `metaAndAssetCtxs`. Assets are prefixed (`xyz:NVDA`, `cash:AMZN`); prefix is stripped for CCXT symbol building.

## Security — NEVER leak secrets

### What counts as sensitive
- **Private keys** (any `0x...` key that signs transactions)
- **API keys** (Hibachi, etc.)
- **AWS credentials** (access keys, secret keys, session tokens)
- **Account IDs** and **resource ARNs** (can be used for reconnaissance)
- **Wallet addresses** tied to real funds
- `.env` file contents
- CloudTrail logs containing request parameters

### Rules
1. **Never commit secrets to git** — `.env`, `task-definition.json` with hardcoded values, etc.
2. **Never print secrets in logs or error messages** — if a script fails, scrub the output before showing it.
3. **Never paste secrets into chat/LLM conversations** — if you need to share an error, redact keys first.
4. **Use placeholders in documentation** — write `<PRIVATE_KEY>`, `<AWS_ACCOUNT_ID>`, not real values.
5. **Rotate immediately if leaked** — create new wallets/keys, move funds, revoke old credentials.

### Where secrets live
| Location | Purpose |
|----------|---------|
| `.env` (gitignored) | Local dev secrets |
| Lambda env vars | Production runtime secrets (encrypted at rest by AWS KMS) |
| GitHub Secrets | CI/CD AWS credentials only |

## AWS deployment
- **Lambda** — ap-southeast-1 (Singapore)
- **Runtime**: Python 3.12
- **Trigger**: EventBridge Scheduler (`rate(1 hour)`)
- **Memory**: 512 MB (can tune down to 256 MB)
- **Timeout**: 5 minutes
- **Logs**: CloudWatch → `/aws/lambda/airdrop-trading-bot`
- **CI/CD**: GitHub Actions → pytest → build zip → deploy Lambda + EventBridge schedule

## GitHub
`https://github.com/NattapongPi/perps-dex-airdrop` — push to `main` triggers auto-deploy.

## Key files
- `src/exchanges/_hip3.py` — HIP-3 market discovery via `perpDexs` API
- `src/exchanges/tradexyz.py` — TradeXYZ adapter (inherits HyperliquidAdapter)
- `src/exchanges/dreamcash.py` — DreamCash adapter (inherits HyperliquidAdapter)
- `src/exchanges/hibachi.py` — Hibachi adapter
- `src/exchanges/ccxt_base.py` — base CCXT adapter with order placement
- `src/config_loader.py` — loads config.yaml + validates secrets at startup
- `src/lambda_handler.py` — Lambda entry point
- `scripts/build_lambda.py` — builds deployment zip
- `scripts/deploy_lambda.py` — deploys Lambda + EventBridge via AWS CLI
- `.github/workflows/deploy.yml` — CI/CD pipeline

## Common tasks

**Deploy a change:**
```bash
git add <files>
git commit -m "description"
git push   # triggers GitHub Actions → auto-deploys to Lambda
```

**Check if bot is running:**
- CloudWatch Logs → log group `/aws/lambda/airdrop-trading-bot`
- Lambda Console → `airdrop-trading-bot` → Monitor → CloudWatch metrics

**Run tests locally:**
```bash
pytest tests/
```

**Deploy manually (local):**
```bash
python scripts/build_lambda.py
python scripts/deploy_lambda.py
```

**Check live HIP-3 markets manually:**
```python
import requests
r = requests.post("https://api.hyperliquid.xyz/info", json={"type": "perpDexs"})
for dex in r.json():
    print(dex.get("deployer"), list(dex.get("assetToStreamingOiCap", {}).keys())[:3])
```
