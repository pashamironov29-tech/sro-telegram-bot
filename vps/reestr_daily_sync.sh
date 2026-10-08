#!/bin/bash
# Nightly reestr sync on VPS: maintenance stub -> sync -> main bot.
# On failure -> Telegram to BOT_ADMIN_IDS.
set -euo pipefail

APP_DIR="/opt/sro-bot"
LOG_DIR="$APP_DIR/logs"
PYTHON="$APP_DIR/venv/bin/python"
STAMP="$(date -u +%Y-%m-%d_%H%M%S)"
LOG="$LOG_DIR/reestr_daily_${STAMP}.log"
STUB_PID_FILE="$APP_DIR/maintenance_stub.pid"
STUB_LOG="$LOG_DIR/maintenance_stub_${STAMP}.log"

mkdir -p "$LOG_DIR"
exec >>"$LOG" 2>&1

notify_fail() {
  local reason="$1"
  echo "FAIL: $reason"
  stop_maintenance_stub || true
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
    "🚨 <b>Ночной sync реестра упал</b>\n"
    f"<code>{reason[:500]}</code>\n\n"
    "Таймер жив; сломался скрипт.\n"
    "Лог: <code>/opt/sro-bot/logs/reestr_daily_*.log</code>\n"
    "Пробуем поднять бота: systemctl start sro-bot"
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
  systemctl start sro-bot || true
}

start_maintenance_stub() {
  echo "Starting maintenance stub..."
  # Free token: stop main bot first
  systemctl stop sro-bot || true
  sleep 2
  nohup "$PYTHON" -u "$APP_DIR/maintenance_stub.py" >>"$STUB_LOG" 2>&1 &
  echo $! >"$STUB_PID_FILE"
  sleep 2
  if ! kill -0 "$(cat "$STUB_PID_FILE")" 2>/dev/null; then
    echo "WARN: maintenance stub failed to start (see $STUB_LOG)"
    rm -f "$STUB_PID_FILE"
    return 1
  fi
  echo "Maintenance stub PID=$(cat "$STUB_PID_FILE")"
  return 0
}

stop_maintenance_stub() {
  if [ -f "$STUB_PID_FILE" ]; then
    local pid
    pid="$(cat "$STUB_PID_FILE")"
    echo "Stopping maintenance stub PID=$pid"
    kill "$pid" 2>/dev/null || true
    # wait up to ~15s
    for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
      if ! kill -0 "$pid" 2>/dev/null; then
        break
      fi
      sleep 1
    done
    kill -9 "$pid" 2>/dev/null || true
    rm -f "$STUB_PID_FILE"
  fi
  # leftover by name
  pkill -f "$APP_DIR/maintenance_stub.py" 2>/dev/null || true
  sleep 1
}

echo "=== $(date -u -Iseconds) UTC: start daily reestr sync ==="

cd "$APP_DIR"
export PYTHONUNBUFFERED=1
export PYTHONIOENCODING=utf-8

start_maintenance_stub || echo "WARN: continue sync without stub"

# Ненулевой код — массовый провал (см. daily_sync_failure_reason). Кэш при этом
# уже записан целиком или остался предыдущим: ботов всё равно поднимаем.
sync_rc=0
# $? внутри `if ! cmd` — это код уже инвертированного теста (0). Код cmd берём справа от ||,
# иначе set -e оборвёт скрипт, а notify_fail по провалу синка не увидит ошибку.
"$PYTHON" -u reestr_sync.py --daily || sync_rc=$?

echo "Stopping maintenance stub, starting sro-bot and sro-max-bot..."
stop_maintenance_stub

bot_rc=0
if ! systemctl start sro-bot; then
  bot_rc=1
else
  sleep 2
  if ! systemctl is-active --quiet sro-bot; then
    bot_rc=1
  fi
fi
systemctl is-active sro-bot || true

# MAX держит реестр в памяти с момента своего старта. Рестарт после целого
# файла надёжнее, чем перечитывать JSON на каждом сохранении (каждые 200 карточек).
max_rc=0
if ! systemctl restart sro-max-bot; then
  max_rc=1
else
  sleep 2
  if ! systemctl is-active --quiet sro-max-bot; then
    max_rc=1
  fi
fi
systemctl is-active sro-max-bot || true

if [ "$bot_rc" -ne 0 ]; then
  notify_fail "systemctl start sro-bot failed (sync rc=$sync_rc, log $LOG)"
  exit 1
fi
if [ "$max_rc" -ne 0 ]; then
  notify_fail "systemctl restart sro-max-bot failed (sync rc=$sync_rc, log $LOG)"
  exit 1
fi
if [ "$sync_rc" -ne 0 ]; then
  notify_fail "reestr_sync.py --daily exited with error (rc=$sync_rc, log $LOG)"
  exit 1
fi

echo "=== $(date -u -Iseconds) UTC: done ==="

find "$LOG_DIR" -name 'reestr_daily_*.log' -mtime +14 -delete 2>/dev/null || true
find "$LOG_DIR" -name 'maintenance_stub_*.log' -mtime +14 -delete 2>/dev/null || true
