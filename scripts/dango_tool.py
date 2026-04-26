"""
Standalone Dango CLI tool.

Run individual Dango commands without starting the full bot loop.
Usage examples:

    python scripts/dango_tool.py ping
    python scripts/dango_tool.py top --n 10
    python scripts/dango_tool.py ohlcv --symbol perp/btcusd --timeframe 1h --limit 50
    python scripts/dango_tool.py positions
    python scripts/dango_tool.py balance
    python scripts/dango_tool.py order --symbol perp/btcusd --side buy --size 0.01 --tp 0.04 --sl 0.02
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config_loader import load_config
from src.exchanges.dango import DangoAdapter

logging.basicConfig(level=logging.INFO, format="%(message)s")
_logger = logging.getLogger("dango_tool")


def _get_adapter() -> DangoAdapter:
    """Load config and return a DangoAdapter instance."""
    config = load_config()
    return DangoAdapter(config)


def cmd_ping(args: argparse.Namespace) -> None:
    adp = _get_adapter()
    ok = adp.ping()
    print("pong" if ok else "failed")
    sys.exit(0 if ok else 1)


def cmd_top(args: argparse.Namespace) -> None:
    adp = _get_adapter()
    coins = adp.get_top_coins(args.n)
    for i, c in enumerate(coins, 1):
        print(f"{i:2d}. {c}")


def cmd_ohlcv(args: argparse.Namespace) -> None:
    adp = _get_adapter()
    df = adp.get_ohlcv(args.symbol, args.timeframe, args.limit)
    if df.empty:
        print("No data returned.")
        return
    print(df.to_string())


def cmd_positions(args: argparse.Namespace) -> None:
    adp = _get_adapter()
    positions = adp.get_open_positions()
    if not positions:
        print("No open positions.")
        return
    for p in positions:
        print(
            f"{p.symbol:20s}  {p.side:6s}  size={p.size:12.6f}  entry={p.entry_price:12.4f}"
        )


def cmd_balance(args: argparse.Namespace) -> None:
    adp = _get_adapter()
    bal = adp.get_balance()
    print(f"Free margin: {bal:.4f} USD")


def cmd_order(args: argparse.Namespace) -> None:
    adp = _get_adapter()
    result = adp.place_order(
        symbol=args.symbol,
        side=args.side,
        size=args.size,
        tp_pct=args.tp,
        sl_pct=args.sl,
    )
    print(json.dumps(result.__dict__, indent=2, default=str))


def cmd_close(args: argparse.Namespace) -> None:
    adp = _get_adapter()
    result = adp.close_position(
        symbol=args.symbol,
        size=args.size,
    )
    print(json.dumps(result.__dict__, indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dango exchange CLI — run commands without the full bot loop.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  %(prog)s ping
  %(prog)s top --n 10
  %(prog)s ohlcv --symbol perp/btcusd --timeframe 1h --limit 50
  %(prog)s positions
  %(prog)s balance
  %(prog)s order --symbol perp/btcusd --side buy --size 0.01 --tp 0.04 --sl 0.02
  %(prog)s close --symbol perp/btcusd --size 0.01
        """.strip(),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ping
    sub.add_parser("ping", help="Check Dango connectivity and credentials")

    # top
    p_top = sub.add_parser("top", help="List top N perp pairs by 24h volume")
    p_top.add_argument("--n", type=int, default=20, help="Number of pairs (default: 20)")

    # ohlcv
    p_ohlcv = sub.add_parser("ohlcv", help="Fetch OHLCV candles for a pair")
    p_ohlcv.add_argument("--symbol", required=True, help="Pair id, e.g. perp/btcusd")
    p_ohlcv.add_argument("--timeframe", default="1h", help="Candle interval (default: 1h)")
    p_ohlcv.add_argument("--limit", type=int, default=100, help="Number of candles (default: 100)")

    # positions
    sub.add_parser("positions", help="List open positions")

    # balance
    sub.add_parser("balance", help="Show free margin balance")

    # order
    p_order = sub.add_parser("order", help="Place a market order with TP/SL")
    p_order.add_argument("--symbol", required=True, help="Pair id, e.g. perp/btcusd")
    p_order.add_argument("--side", required=True, choices=["buy", "sell"], help="Order side")
    p_order.add_argument("--size", required=True, type=float, help="Position size in base units")
    p_order.add_argument("--tp", required=True, type=float, help="Take-profit pct (e.g. 0.04 = 4%%)")
    p_order.add_argument("--sl", required=True, type=float, help="Stop-loss pct (e.g. 0.02 = 2%%)")

    # close
    p_close = sub.add_parser("close", help="Close a position with a reduce-only market order")
    p_close.add_argument("--symbol", required=True, help="Pair id, e.g. perp/btcusd")
    p_close.add_argument("--size", required=True, type=float, help="Position size in base units to close")

    args = parser.parse_args()

    commands = {
        "ping": cmd_ping,
        "top": cmd_top,
        "ohlcv": cmd_ohlcv,
        "positions": cmd_positions,
        "balance": cmd_balance,
        "order": cmd_order,
        "close": cmd_close,
    }

    try:
        commands[args.command](args)
    except Exception as exc:
        _logger.error("Command failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
