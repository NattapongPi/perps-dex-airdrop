#!/bin/sh
# Dump container env vars so cron jobs can see them (cron runs in a clean shell).
printenv | grep -v "^_=" >> /etc/environment
# Start cron daemon in background, then run health server in foreground.
cron
exec python3 -m src.health_server
