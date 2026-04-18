#!/bin/sh
# Start cron daemon in background, then run health server in foreground.
cron
exec python3 -m src.health_server
