"""
Lightweight Flask server for Docker healthcheck.

GET /health  — liveness probe (always returns 200 OK)
GET /ready   — readiness probe (calls ping() on all exchanges)

Started as a daemon thread in src/main.py so the bot can still be triggered
by cron while the health endpoint stays alive.
"""

from __future__ import annotations

from flask import Flask, jsonify

app = Flask(__name__)

_exchanges: dict = {}


def start_health_server(exchanges: dict) -> None:
    """Store exchanges dict and run Flask on port 8080."""
    global _exchanges
    _exchanges = exchanges
    app.config["exchanges"] = exchanges
    app.run(host="0.0.0.0", port=8080, debug=False, use_reloader=False)


@app.get("/health")
def health():
    """Liveness probe — confirms the process is up."""
    return jsonify({"status": "ok"})


@app.get("/ready")
def ready():
    """Readiness probe — verifies all exchange connections."""
    exchanges = app.config.get("exchanges") or _exchanges
    if not exchanges:
        return jsonify({"status": "error", "detail": "no exchanges configured"}), 503

    statuses: dict = {}
    all_ok = True

    for name, ex in exchanges.items():
        try:
            ok = bool(ex.ping())
        except Exception:
            ok = False
        statuses[name] = ok
        if not ok:
            all_ok = False

    if all_ok:
        return jsonify({"status": "ready", "exchanges": statuses})
    return jsonify({"status": "error", "exchanges": statuses}), 503
