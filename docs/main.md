# Main Orchestrator & Entry Points

## `src/main.py` — Trading Loop

Stateless scan loop designed to run once per hour.

### `run()`

1. Load config (`config_loader.Config`)
2. Build adapter dict for all active exchanges
3. For each exchange, call `_run_exchange(...)`
4. Log global summary

### `_run_exchange(adapter, config)`

1. Merge global config with per-exchange overrides
2. `ping()` exchange; skip if unreachable
3. Fetch:
   - `get_top_coins(n)` — scan candidates
   - `get_open_positions()` — existing positions
   - `get_balance()` — free collateral
4. If `clear_positions_on_startup` is enabled: close all positions at market, then cancel all remaining open orders, and re-fetch account state
5. Otherwise: `cancel_orphan_orders()` — clean up stale TP/SL (critical for Hibachi)
6. Iterate top coins:
   - Skip if max concurrent positions reached
   - Skip if already have a position in this symbol
   - Fetch OHLCV → `TrendFilter.evaluate()`
   - If `Signal.LONG`:
     - Compute SL/TP prices via `risk.sizing`
     - Compute position size via fixed fractional risk
     - If `dry_run`: log only
     - Else: `place_order(side="buy", size, tp_pct, sl_pct)`
6. Log per-exchange summary

### Dry Run

Set `DRY_RUN=true` in `.env` or config to log orders without placing them.

## `src/lambda_handler.py` — AWS Lambda

Entry point for EventBridge Scheduler (triggers hourly).

```python
def handler(event, context):
    # Logs runtime context to CloudWatch
    # Calls main.run()
    # Returns {statusCode: 200, body: "..."}
    # On exception: prints to stderr and re-raises (Lambda marks failed)
```

## Health Endpoints

### `src/health.py` — Full Health Server

Flask app on `0.0.0.0:8080`:
- `GET /health` — always `200 OK` (liveness)
- `GET /ready` — calls `ping()` on all exchanges; `503` if any fail (readiness)

### `src/health_server.py` — Minimal Health Server

Standalone Flask server with only `GET /health`. Used as ECS sidecar.

## `src/logging_config.py`

Structured JSON logging to stdout via `pythonjsonlogger`.
- `setup_logging(level)` — configure root logger once
- `get_logger(name)` — named loggers
