#!/bin/bash
# Watchdog: Telegram API + sro-bot.service
# - бот не active → start
# - api.telegram.org снова доступен после сбоя / свежие ConnectTimeout → restart (с кулдауном)
# Не дёргает restart, пока Telegram мёртв (бесполезно).
# Уведомления в Telegram: по умолчанию только FAIL (успешные restart — в лог).
# NOTIFY_OK=1 — снова слать и «restart → active».
set -u

APP_DIR="/opt/sro-bot"
LOG_DIR="$APP_DIR/logs"
PYTHON="$APP_DIR/venv/bin/python"
STATE_DIR="/var/lib/sro-bot"
STATE_FILE="$STATE_DIR/telegram_watchdog.state"
COOLDOWN_SEC=900
NOTIFY_OK="${NOTIFY_OK:-0}"
LOG="$LOG_DIR/telegram_watchdog.log"

mkdir -p "$LOG_DIR" "$STATE_DIR"
exec >>"$LOG" 2>&1

ts() { date -u -Iseconds; }

# Ночной sync держит свой stub — не мешаем
if [ -f "$APP_DIR/maintenance_stub.pid" ]; then
  pid="$(cat "$APP_DIR/maintenance_stub.pid" 2>/dev/null || true)"
  if [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null; then
    echo "$(ts) skip: maintenance stub pid=$pid"
    exit 0
  fi
fi

notify() {
  local reason="$1"
  "$PYTHON" - <<'PY' "$reason" || true
import sys
import requests

reason = sys.argv[1]
try:
    from config_keys import BOT_TOKEN, BOT_ADMIN_IDS
except Exception as exc:
    print("notify skip:", exc)
    raise SystemExit(0)

ids = BOT_ADMIN_IDS
if ids is None:
    ids = []
elif isinstance(ids, (int, str)):
    ids = [int(ids)]
else:
    ids = [int(x) for x in ids]

text = (
    "🛠 <b>Watchdog sro-bot</b>\n"
    f"<code>{reason[:700]}</code>\n"
    "Лог: <code>/opt/sro-bot/logs/telegram_watchdog.log</code>"
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
        print("notify fail", admin_id, exc)
PY
}

load_state() {
  TG_WAS_DOWN=0
  LAST_RESTART=0
  if [ -f "$STATE_FILE" ]; then
    # shellcheck disable=SC1090
    . "$STATE_FILE" || true
  fi
}

save_state() {
  cat >"$STATE_FILE" <<EOF
TG_WAS_DOWN=$TG_WAS_DOWN
LAST_RESTART=$LAST_RESTART
EOF
}

in_cooldown() {
  local now
  now="$(date +%s)"
  if [ "${LAST_RESTART:-0}" -gt 0 ] && [ $((now - LAST_RESTART)) -lt "$COOLDOWN_SEC" ]; then
    return 0
  fi
  return 1
}

do_restart() {
  local why="$1"
  if in_cooldown; then
    echo "$(ts) cooldown skip restart: $why"
    return 0
  fi
  echo "$(ts) restart: $why"
  systemctl restart sro-bot
  sleep 2
  if systemctl is-active --quiet sro-bot; then
    LAST_RESTART="$(date +%s)"
    save_state
    echo "$(ts) restart ok: $why → active"
    if [ "$NOTIFY_OK" = "1" ]; then
      notify "restart: $why → active"
    fi
  else
    notify "restart FAIL: $why → $(systemctl is-active sro-bot)"
  fi
}

probe_telegram() {
  "$PYTHON" - <<'PY'
import requests
try:
    from config_keys import BOT_TOKEN
except Exception as exc:
    print("NO_TOKEN", exc)
    raise SystemExit(2)
try:
    r = requests.get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/getMe",
        timeout=15,
    )
    if r.status_code == 200 and (r.json() or {}).get("ok"):
        raise SystemExit(0)
    print("BAD", r.status_code, (r.text or "")[:120])
    raise SystemExit(1)
except SystemExit:
    raise
except Exception as exc:
    print("ERR", type(exc).__name__, exc)
    raise SystemExit(1)
PY
}

load_state

# 1) процесс / сервис
if ! systemctl is-active --quiet sro-bot; then
  echo "$(ts) sro-bot not active → start"
  systemctl start sro-bot || true
  sleep 2
  if systemctl is-active --quiet sro-bot; then
    LAST_RESTART="$(date +%s)"
    save_state
    echo "$(ts) start ok: sro-bot был не active → ok"
    if [ "$NOTIFY_OK" = "1" ]; then
      notify "sro-bot был не active → start → ok"
    fi
  else
    notify "sro-bot не active, start не помог: $(systemctl is-active sro-bot)"
  fi
  exit 0
fi

# 2) Telegram API
if probe_telegram; then
  TG_OK=1
else
  TG_OK=0
fi

if [ "$TG_OK" -eq 0 ]; then
  TG_WAS_DOWN=1
  save_state
  echo "$(ts) telegram DOWN (no restart while API dead)"
  exit 0
fi

# 3) API снова жив после дауна → перезапуск polling
if [ "${TG_WAS_DOWN:-0}" -eq 1 ]; then
  TG_WAS_DOWN=0
  save_state
  do_restart "Telegram API снова доступен (был даун)"
  exit 0
fi

# 4) свежие ConnectTimeout в журнале при живом API → зависший polling
if journalctl -u sro-bot --since "8 min ago" --no-pager 2>/dev/null | grep -q "ConnectTimeout"; then
  do_restart "в журнале ConnectTimeout за 8 мин, API сейчас OK"
  exit 0
fi

echo "$(ts) ok"
exit 0
