"""
Structured JSON logging — stdout only, cloud/Docker friendly.

Usage:
    from src.logging_config import get_logger
    logger = get_logger(__name__)
    logger.info("Order placed", extra={"symbol": "BTC", "size": 0.01})
"""

from __future__ import annotations

import logging
import sys

from pythonjsonlogger import jsonlogger


def setup_logging(level: str = "INFO") -> None:
    """
    Configure the root logger once at startup.
    All subsequent get_logger() calls inherit this config.
    """
    root = logging.getLogger()
    if root.handlers:
        # Already configured (e.g. called twice); update level only.
        root.setLevel(level)
        return

    handler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
        rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
    )
    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. Call setup_logging() once before using this."""
    return logging.getLogger(name)
