"""
Main orchestrator — the trading loop.

Designed to be triggered once per hour (by cron or APScheduler).
Each run is stateless: it reads live data, evaluates signals, and acts.

Run manually:
    python -m src.main

Run on a schedule inside the container:
    cron triggers: 3 * * * * cd /app && python -m src.main
"""

from __future__ import annotations

import sys
from dataclasses import asdict

from src.config_loader import load_config
from src.exchanges import get_adapter  # used in run() to build adapter dict
from src.logging_config import get_logger, setup_logging
from src.risk.sizing import (
    calculate_position_size,
    calculate_sl_tp_pct,
    calculate_sl_tp_prices,
)
from src.strategy.trend_filter import Signal, TrendFilter


def _merge_config(global_cfg: dict, override: dict) -> dict:
    """Merge global config dict with per-exchange overrides."""
    merged = dict(global_cfg)
    for key, val in override.items():
        if isinstance(val, dict) and key in merged and isinstance(merged[key], dict):
            merged[key] = {**merged[key], **val}
        else:
            merged[key] = val
    return merged


def _run_exchange(
    exchange_name: str,
    exchange,
    config,
    logger,
) -> int:
    """Scan and trade one exchange. Returns number of orders placed."""
    overrides = config.per_exchange.get(exchange_name, {})

    global_strategy = asdict(config.strategy)
    global_risk = asdict(config.risk)
    global_position = asdict(config.position)
    global_scan = asdict(config.scan)

    strategy_cfg = _merge_config(global_strategy, overrides.get("strategy", {}))
    risk_cfg = _merge_config(global_risk, overrides.get("risk", {}))
    position_cfg = _merge_config(global_position, overrides.get("position", {}))
    scan_cfg = _merge_config(global_scan, overrides.get("scan", {}))

    strategy = TrendFilter(
        ema_fast=strategy_cfg["ema_fast"],
        ema_slow=strategy_cfg["ema_slow"],
        atr_period=risk_cfg["atr_period"],
    )

    try:
        if not exchange.ping():
            logger.warning("Exchange unreachable, skipping", extra={"exchange": exchange_name})
            return 0
    except Exception as exc:
        logger.warning("Exchange ping failed", extra={"exchange": exchange_name, "error": str(exc)})
        return 0

    try:
        top_coins = exchange.get_top_coins(scan_cfg["top_n"])
        open_positions = exchange.get_open_positions()
        open_symbols = {p.symbol for p in open_positions}
        balance = exchange.get_balance()
    except Exception as exc:
        logger.error("Failed to fetch account state", extra={"exchange": exchange_name, "error": str(exc)})
        return 0

    logger.info(
        "Exchange state fetched",
        extra={
            "exchange": exchange_name,
            "balance_usd": round(balance, 2),
            "open_positions": len(open_positions),
            "coins_to_scan": len(top_coins),
        },
    )

    cancelled = exchange.cancel_orphan_orders(open_positions)
    if cancelled:
        logger.info("Cancelled orphan orders", extra={"exchange": exchange_name, "count": cancelled})

    orders_placed = 0
    max_concurrent = position_cfg["max_concurrent"]

    for symbol in top_coins:
        if len(open_symbols) >= max_concurrent:
            logger.info("Max concurrent positions reached, stopping scan", extra={"exchange": exchange_name})
            break

        if symbol in open_symbols:
            logger.info("Position exists, skipping", extra={"exchange": exchange_name, "symbol": symbol})
            continue

        try:
            df = exchange.get_ohlcv(symbol, scan_cfg["timeframe"], scan_cfg["ohlcv_limit"])
        except Exception as exc:
            logger.warning("Failed to fetch OHLCV, skipping", extra={"exchange": exchange_name, "symbol": symbol, "error": str(exc)})
            continue

        try:
            signal, atr_value = strategy.evaluate(df)
        except Exception as exc:
            logger.warning("Strategy evaluation failed, skipping", extra={"exchange": exchange_name, "symbol": symbol, "error": str(exc)})
            continue

        if signal != Signal.LONG:
            logger.info("No signal", extra={"exchange": exchange_name, "symbol": symbol, "signal": signal.value})
            continue

        entry_price = float(df["close"].iloc[-1])

        sl_price, tp_price = calculate_sl_tp_prices(
            entry_price=entry_price,
            atr_value=atr_value,
            sl_multiplier=risk_cfg["atr_sl_multiplier"],
            tp_multiplier=risk_cfg["atr_tp_multiplier"],
        )
        sl_pct, tp_pct = calculate_sl_tp_pct(entry_price, sl_price, tp_price)

        min_sl_pct = risk_cfg.get("min_sl_pct", 0.0)
        if sl_pct < min_sl_pct:
            logger.info(
                "SL too tight — skipping",
                extra={
                    "exchange": exchange_name,
                    "symbol": symbol,
                    "sl_pct": round(sl_pct * 100, 4),
                    "min_sl_pct": round(min_sl_pct * 100, 4),
                },
            )
            continue

        size = calculate_position_size(
            balance=balance,
            risk_pct=risk_cfg["risk_pct"],
            entry_price=entry_price,
            sl_price=sl_price,
        )

        if size <= 0:
            logger.warning(
                "Position size is zero or negative, skipping",
                extra={
                    "exchange": exchange_name,
                    "symbol": symbol,
                    "entry_price": entry_price,
                    "sl_price": sl_price,
                    "atr_value": atr_value,
                },
            )
            continue

        order_extra = {
            "exchange": exchange_name,
            "symbol": symbol,
            "size": round(size, 6),
            "entry_price": entry_price,
            "sl_price": round(sl_price, 6),
            "tp_price": round(tp_price, 6),
            "sl_pct": round(sl_pct * 100, 3),
            "tp_pct": round(tp_pct * 100, 3),
            "atr_value": round(atr_value, 6),
        }

        if config.dry_run:
            logger.info("DRY RUN — order skipped", extra=order_extra)
            orders_placed += 1
            open_symbols.add(symbol)
            continue

        try:
            result = exchange.place_order(
                symbol=symbol,
                side="buy",
                size=size,
                tp_pct=tp_pct,
                sl_pct=sl_pct,
            )
        except Exception as exc:
            logger.error(
                "Order placement failed",
                extra={"exchange": exchange_name, "symbol": symbol, "error": str(exc)},
                exc_info=True,
            )
            continue

        orders_placed += 1
        open_symbols.add(symbol)
        logger.info("Order placed", extra={**order_extra, "order_id": result.order_id, "status": result.status})

    logger.info("Exchange scan complete", extra={"exchange": exchange_name, "orders_placed": orders_placed})
    return orders_placed


def run() -> None:
    config = load_config()
    setup_logging(config.logging.level)
    logger = get_logger("orchestrator")

    logger.info(
        "Scan started",
        extra={
            "exchanges": config.exchanges,
            "top_n": config.scan.top_n,
            "timeframe": config.scan.timeframe,
            "ema_fast": config.strategy.ema_fast,
            "ema_slow": config.strategy.ema_slow,
            "risk_pct": config.risk.risk_pct,
            "atr_sl_mult": config.risk.atr_sl_multiplier,
            "atr_tp_mult": config.risk.atr_tp_multiplier,
        },
    )

    exchanges = {name: get_adapter(name, config) for name in config.exchanges}

    total_orders = 0
    for exchange_name, adapter in exchanges.items():
        total_orders += _run_exchange(exchange_name, adapter, config, logger)

    logger.info("Scan complete", extra={"total_orders": total_orders})


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        import logging
        logging.getLogger("orchestrator").critical(
            "Unhandled exception — bot crashed",
            extra={"error": str(exc)},
            exc_info=True,
        )
        sys.exit(1)
