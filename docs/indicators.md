# Indicators

Pure functions in `src/indicators/`. No side effects, no state.

## EMA (`ema.py`)

```python
def ema(series: pd.Series, period: int) -> pd.Series
```

Standard Exponential Moving Average via `pandas.Series.ewm(span=period, adjust=False)`.

## ATR (`atr.py`)

```python
def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series
```

Average True Range (Wilder's smoothing).

1. **True Range** per candle:
   ```
   TR = max(high - low, |high - prev_close|, |low - prev_close|)
   ```
2. **Smooth** with EWM: `span=period, adjust=False`

Returns a `pd.Series` aligned to the input index.
