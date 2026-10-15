#!/bin/bash
# Nightly specialist sync: member cards of 15 partner SROs -> specialists.sqlite.
# Does not stop the bots. On failure -> Telegram to BOT_ADMIN_IDS.
set -euo pipefail

APP_DIR="/opt/sro-bot"
LOG_DIR="$APP_DIR/logs"
PYTHON="$APP_DIR/venv/bin/python"
STAMP="$(date -u +%Y-%m-%d_%H%M%S)"
LOG="$LOG_DIR/specialist_sync_${STAMP}.log"

mkdir -p "$LOG_DIR"
exec >>"$LOG" 2>&1

notify_fail() {
  local reason="$1"
  echo "FAIL: $reason"
  "$PYTHON" - <<'PY' "$reason" || true
import sys
import requests

reason = sys.argv[1]
try:
    from config_keys import BOT_TOKEN, BOT_ADMIN_IDS
except Exception as exc:
    print("notify skip: no config", exc)
    raise SystemExit(0)

ids = BOT_ADMIN_IDS
if ids is None:
    ids = []
elif isinstance(ids, (int, str)):
    ids = [int(ids)]
else:
    ids = [int(x) for x in ids]

text = (
    "🚨 <b>Синк специалистов упал</b>\n"
    f"<code>{reason[:500]}</code>\n\n"
    "Боты не останавливались.\n"
    "Лог: <code>/opt/sro-bot/logs/specialist_sync_*.log</code>"
)
api = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
for admin_id in ids:
    try:
        requests.post(
            api,
            json={"chat_id": admin_id, "text": text, "parse_mode": "HTML"},
            timeout=20,
        )
    except Exception as exc:
        print("telegram fail", admin_id, exc)
PY
}

echo "=== $(date -u -Iseconds) UTC: specialist sync start ==="
cd "$APP_DIR"
export PYTHONUNBUFFERED=1
export PYTHONIOENCODING=utf-8

sync_rc=0
"$PYTHON" -u specialist_sync.py || sync_rc=$?

if [ "$sync_rc" -ne 0 ]; then
  notify_fail "specialist_sync.py exited with error (rc=$sync_rc, log $LOG)"
  exit 1
fi

echo "=== $(date -u -Iseconds) UTC: done ==="
find "$LOG_DIR" -name 'specialist_sync_*.log' -mtime +14 -delete 2>/dev/null || true
