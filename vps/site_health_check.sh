#!/bin/bash
# Daily NRS + SRO sites health check -> Telegram admins on failure.
set -euo pipefail

APP_DIR="/opt/sro-bot"
LOG_DIR="$APP_DIR/logs"
PYTHON="$APP_DIR/venv/bin/python"
STAMP="$(date -u +%Y-%m-%d_%H%M%S)"
LOG="$LOG_DIR/site_health_run_${STAMP}.log"

mkdir -p "$LOG_DIR"
exec >>"$LOG" 2>&1

echo "=== $(date -u -Iseconds) UTC: site health start ==="
cd "$APP_DIR"
export PYTHONUNBUFFERED=1
export PYTHONIOENCODING=utf-8

# Without --notify-ok: Telegram only if something failed
set +e
"$PYTHON" -u site_health_check.py
code=$?
set -e

echo "exit=$code"
echo "=== $(date -u -Iseconds) UTC: site health done ==="

find "$LOG_DIR" -name 'site_health_*.log' -mtime +30 -delete 2>/dev/null || true
exit "$code"
