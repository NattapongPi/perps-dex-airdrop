#!/bin/sh
# Start cron daemon in background, then run health server in foreground.
cron
exec python -m src.health_server
