# Strategy

`src/strategy/trend_filter.py` — EMA trend filter.

## TrendFilter

```python
filter = TrendFilter(ema_fast=12, ema_slow=26, atr_period=14)
signal, atr_value = filter.evaluate(ohlcv_df)
```

### Logic

1. Compute `EMA_fast` (12) and `EMA_slow` (26) on `close`
2. Compute `ATR` (14) on `[high, low, close]`
3. **Signal:**
   - `Signal.LONG` if `EMA_fast > EMA_slow` on latest candle
   - `Signal.NONE` otherwise

### Long Only

The bot only takes **long** positions. No short signals are generated.

### Validation

- Required columns: `open, high, low, close, volume`
- Minimum rows: `max(ema_slow, atr_period) * 2` (safety margin for warm-up)
- Raises `ValueError` if constraints not met

### Config

```yaml
strategy:
  ema_fast: 12
  ema_slow: 26
  atr_period: 14
```

Per-exchange override supported:
```yaml
exchanges:
  - dreamcash:
      strategy:
        ema_fast: 10
```
