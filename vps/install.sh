#!/bin/bash
# Установка СРО-бота на Ubuntu 22.04/24.04 (запускать на VPS от root)
set -euo pipefail

APP_DIR="/opt/sro-bot"
APP_USER="srobot"

echo "==> Обновление пакетов..."
apt-get update -qq
apt-get install -y python3 python3-venv python3-pip rsync

echo "==> Пользователь $APP_USER..."
if ! id "$APP_USER" &>/dev/null; then
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi

mkdir -p "$APP_DIR/sro_data/plany" "$APP_DIR/sro_data/blanki"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

if [ ! -d "$APP_DIR/venv" ]; then
  echo "==> Виртуальное окружение Python..."
  python3 -m venv "$APP_DIR/venv"
fi

if [ -f "$APP_DIR/requirements.txt" ]; then
  echo "==> Зависимости..."
  "$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
fi

if [ -f "$APP_DIR/config_keys.py" ]; then
  sed -i 's|SRO_FILES_DIR = .*|SRO_FILES_DIR = "/opt/sro-bot/sro_data"|' "$APP_DIR/config_keys.py" 2>/dev/null || true
else
  echo ""
  echo "!!! Создайте $APP_DIR/config_keys.py (скопируйте с ПК или из config_keys.vps.example.py)"
  echo ""
fi

echo "==> Systemd-сервис бота..."
cp "$APP_DIR/vps/sro-bot.service" /etc/systemd/system/sro-bot.service
chmod +x "$APP_DIR/vps/reestr_daily_sync.sh" 2>/dev/null || true
cp "$APP_DIR/vps/sro-reestr-sync.service" /etc/systemd/system/sro-reestr-sync.service
cp "$APP_DIR/vps/sro-reestr-sync.timer" /etc/systemd/system/sro-reestr-sync.timer
systemctl daemon-reload
systemctl enable sro-bot
systemctl enable sro-reestr-sync.timer
systemctl start sro-reestr-sync.timer || true

chown -R "$APP_USER:$APP_USER" "$APP_DIR"

echo ""
echo "Готово. Дальше:"
echo "  1) Залейте файлы бота в $APP_DIR (upload_to_vps.ps1 с Windows)"
echo "  2) Проверьте config_keys.py"
echo "  3) systemctl start sro-bot"
echo "  4) systemctl status sro-bot"
echo "  5) journalctl -u sro-bot -f"
echo "  6) Ночной sync: systemctl list-timers sro-reestr-sync.timer"
echo "     Логи: /opt/sro-bot/logs/reestr_daily_*.log"
