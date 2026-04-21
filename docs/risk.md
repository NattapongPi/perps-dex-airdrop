# Risk

Pure functions in `src/risk/sizing.py`. No side effects.

## Position Sizing

```python
def calculate_position_size(
    balance: float,
    risk_pct: float,
    entry: float,
    sl: float,
) -> float
```

Fixed fractional risk sizing:
```
size = (balance * risk_pct / 100) / (entry - sl)
```

Returns `0.0` if `sl >= entry` (invalid long setup).

## SL/TP Prices

```python
def calculate_sl_tp_prices(
    entry: float,
    atr: float,
    sl_mult: float,
    tp_mult: float,
) -> tuple[float, float]
```

For **long only**:
- `sl = entry - (atr * sl_mult)`
- `tp = entry + (atr * tp_mult)`

## SL/TP Percentages

```python
def calculate_sl_tp_pct(
    entry: float,
    sl: float,
    tp: float,
) -> tuple[float, float]
```

Converts absolute prices to decimal percentages for exchange APIs:
- `sl_pct = (entry - sl) / entry`
- `tp_pct = (tp - entry) / entry`

## Config Defaults

From `config/config.yaml`:
- `risk.risk_pct: 0.2` — risk 0.2% of balance per trade
- `risk.atr_sl_multiplier: 1.0`
- `risk.atr_tp_multiplier: 1.0`
- Result: 1:1 risk/reward (SL = TP = 1× ATR)
