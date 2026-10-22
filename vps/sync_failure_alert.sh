#!/bin/bash
# Telegram, когда sro-specialist-sync или sro-reestr-sync упал или упёрся в TimeoutStartSec.
# Токен читает specialist_sync.notify_admins из config_keys.py и в вывод не пишет.
# Аргумент — имя юнита без .service (systemd подставляет %i).

set -u

APP_DIR="/opt/sro-bot"
PYTHON="${APP_DIR}/venv/bin/python"
UNIT="${1:-sync}"

case "$UNIT" in
  *[!A-Za-z0-9_.-]*)
    echo "sync alert: странное имя юнита, не шлю"
    exit 0
    ;;
esac

if [ ! -x "$PYTHON" ]; then
  PYTHON="$(command -v python3 || true)"
fi
if [ -z "${PYTHON}" ]; then
  echo "sync alert: нет python"
  exit 0
fi

RESULT="$(systemctl show -p Result --value "${UNIT}.service" 2>/dev/null || true)"
CODE="$(systemctl show -p ExecMainStatus --value "${UNIT}.service" 2>/dev/null || true)"

cd "$APP_DIR"
"$PYTHON" -c '
import sys
from specialist_sync import send_unit_failure_alert
send_unit_failure_alert(sys.argv[1], sys.argv[2], sys.argv[3])
' "$UNIT" "${RESULT:-unknown}" "${CODE:-?}" || echo "sync alert: отправка не удалась"
exit 0
