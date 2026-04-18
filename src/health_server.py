"""
Standalone persistent health server for ECS.

Runs continuously alongside cron so ECS health checks always get a response.
The trading loop (src/main.py) runs separately via cron every hour.
"""

from flask import Flask, jsonify

app = Flask(__name__)


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False, use_reloader=False)
