# Exchanges

All exchange integrations live in `src/exchanges/`.

## Architecture

```
ExchangeAdapter (ABC)          <- abstract contract
    ├── CcxtAdapter            <- CCXT-backed base (Hyperliquid family)
    │       ├── HyperliquidAdapter
    │       ├── TradeXYZAdapter
    │       └── DreamCashAdapter
    └── HibachiAdapter         <- standalone CCXT (different API)
```

## Base Contract (`base.py`)

Every adapter must implement:

| Method | Returns | Purpose |
|--------|---------|---------|
| `get_top_coins(n)` | `list[str]` | Top N symbols by OI/volume |
| `get_ohlcv(symbol, tf, limit)` | `pd.DataFrame` | OHLCV with columns `[open,high,low,close,volume]` |
| `get_open_positions()` | `list[Position]` | Open positions (non-zero size) |
| `get_balance()` | `float` | Free collateral in quote currency |
| `place_order(symbol, side, size, tp_pct, sl_pct)` | `OrderResult` | Market entry + TP limit + SL stop-market |
| `ping()` | `bool` | Connectivity check |

Dataclasses:
- `Position(symbol, side, size, entry_price)`
- `OrderResult(order_id, symbol, side, size, entry_price, tp_price, sl_price, status)`

## CCXT Base (`ccxt_base.py`)

Generic adapter for Hyperliquid-family exchanges. Subclasses set 3–4 class attributes:

| Attribute | Example | Purpose |
|-----------|---------|---------|
| `CCXT_ID` | `"hyperliquid"` | CCXT exchange identifier |
| `QUOTE_CURRENCY` | `"USDC"` / `"USDT"` | Collateral currency for balances |
| `PERP_SUFFIX` | `"USDC"` / `"USDT0"` | Filters perp markets |
| `POSITIONS_DEX` | `None` / `"xyz"` / `"cash"` | HIP-3 clearinghouse scope |

**Builder fee setup** (critical for XP farming):
```python
# feeInt = tenths of a basis point.  0.02% → 20
self._exchange.options["feeInt"] = int(builder_fee * 100_000)
# maxFeeRate must be >= actual fee rate
self._exchange.options["feeRate"] = f"{builder_fee * 100}%"
```

**Order flow:** `place_order` sends 3 orders sequentially:
1. **Market entry** (CCXT converts to IOC limit internally)
2. **TP** — reduce-only GTC limit on opposite side
3. **SL** — reduce-only stop-market on opposite side

## HIP-3 Adapters (`tradexyz.py`, `dreamcash.py`)

HIP-3 DEXes run on Hyperliquid but use separate clearinghouses. They inherit `HyperliquidAdapter` and override:
- `get_top_coins()` → queries `perpDexs` API via `_hip3.py`
- `get_ohlcv()` → queries `candleSnapshot` API directly
- `_get_market_price()` → computes mid from L2 book
- `place_order()` → forces isolated margin (HIP-3 rejects cross)

### TradeXYZ
- Markets: `XYZ-*` perps (USDC)
- Builder: `0x88806a71D74ad0a510b350545C9aE490912F0888`
- `POSITIONS_DEX = "xyz"`

### DreamCash
- Markets: `CASH-*` perps (USDT)
- Builder: `0x4950994884602d1b6c6d96e4fe30f58205c39395`
- `POSITIONS_DEX = "cash"`
- `QUOTE_CURRENCY = "USDT"` (balance key)
- Builder fee: `0.0002` (0.02%) for 0.5 XP/$
- Leverage capped at 10x in `place_order()`

## Hibachi (`hibachi.py`)

Standalone adapter (does **not** inherit `CcxtAdapter`).
- Uses `ccxt.hibachi()` for private ops
- Public market data from Hibachi REST API (`data-api.hibachi.xyz`)
- **Critical difference:** Hibachi does **not** auto-cancel reduce-only orders when a position closes. `cancel_orphan_orders()` is overridden to clean up orphan TP/SL orders at the start of each scan.
- TP/SL are placed as **standalone independent orders** (no parent order support)

## Registry (`__init__.py`)

```python
REGISTRY = {
    "hyperliquid": HyperliquidAdapter,
    "tradexyz": TradeXYZAdapter,
    "dreamcash": DreamCashAdapter,
    "hibachi": HibachiAdapter,
}
```

Use `get_adapter(name, config)` to instantiate.

## Credentials

| Exchange | Env Vars | Notes |
|----------|----------|-------|
| Hyperliquid | `HYPERLIQUID_WALLET_ADDRESS`, `HYPERLIQUID_PRIVATE_KEY`, `HYPERLIQUID_BUILDER_CODE` | |
| TradeXYZ | `TRADEXYZ_WALLET_ADDRESS`, `TRADEXYZ_PRIVATE_KEY`, `TRADEXYZ_BUILDER_CODE` | Falls back to HL wallet if blank |
| DreamCash | `DREAMCASH_WALLET_ADDRESS`, `DREAMCASH_PRIVATE_KEY`, `DREAMCASH_BUILDER_CODE` | Reuses HL wallet by default |
| Hibachi | `HIBACHI_API_KEY`, `HIBACHI_ACCOUNT_ID`, `HIBACHI_PRIVATE_KEY` | Separate API entirely |

Missing credentials → exchange skipped with a warning (non-fatal).
