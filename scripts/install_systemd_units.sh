#!/bin/bash
# Ставит живые юниты из каталога исходников в /etc/systemd/system.
# sync_failure_alert.sh кладёт в /opt/sro-bot/vps/.
# Файл пишется только если содержимое или права отличаются (cmp).
# Синки и таймеры не перезапускаются. daemon-reload — только после записи.
# systemd-analyze verify обязан пройти, иначе прежние файлы возвращаются.
# config_keys и .env этот скрипт не читает и не копирует.
set -euo pipefail

UNIT_DIR="/etc/systemd/system"
HELPER_DIR="/opt/sro-bot/vps"
ANALYZE_BIN="systemd-analyze"
SYSTEMCTL_BIN="systemctl"
SOURCE=""
DO_LIST=0

# policy: always — поставить, даже если файла ещё нет (так у живых юнитов и sro-sync-alert@).
# policy: if-present — обновить только то, что уже лежит на сервере. Новый юнит не добавлять.
read -r -d '' MANIFEST <<'EOF' || true
unit always 644 sro-bot.service
unit always 644 sro-max-bot.service
unit always 644 sro-reestr-sync.service
unit always 644 sro-reestr-sync.timer
unit always 644 sro-specialist-sync.service
unit always 644 sro-specialist-sync.timer
unit always 644 sro-sync-alert@.service
unit if-present 644 sro-telegram-watchdog.service
unit if-present 644 sro-telegram-watchdog.timer
unit if-present 644 sro-site-health.service
unit if-present 644 sro-site-health.timer
helper always 755 sync_failure_alert.sh
EOF

usage() {
  echo "usage: install_systemd_units.sh --source DIR [--unit-dir DIR] [--helper-dir DIR] [--analyze BIN] [--systemctl BIN]" >&2
  echo "       install_systemd_units.sh --list" >&2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source)
      SOURCE=${2:-}
      shift 2
      ;;
    --unit-dir)
      UNIT_DIR=${2:-}
      shift 2
      ;;
    --helper-dir)
      HELPER_DIR=${2:-}
      shift 2
      ;;
    --analyze)
      ANALYZE_BIN=${2:-}
      shift 2
      ;;
    --systemctl)
      SYSTEMCTL_BIN=${2:-}
      shift 2
      ;;
    --list)
      DO_LIST=1
      shift
      ;;
    *)
      usage
      exit 1
      ;;
  esac
done

list_names() {
  local kind policy mode name
  while read -r kind policy mode name; do
    [[ -n "${name:-}" ]] || continue
    printf '%s\n' "$name"
  done <<<"$MANIFEST"
}

if [[ "$DO_LIST" -eq 1 ]]; then
  list_names
  exit 0
fi

if [[ -z "$SOURCE" ]]; then
  usage
  exit 1
fi

abs_dir() {
  local path=$1 label=$2
  case "$path" in
    /*) ;;
    *)
      echo "$label не абсолютный: $path" >&2
      exit 1
      ;;
  esac
  case "$path" in
    *..*)
      echo "$label содержит ..: $path" >&2
      exit 1
      ;;
  esac
}

abs_dir "$SOURCE" "source"
abs_dir "$UNIT_DIR" "unit-dir"
abs_dir "$HELPER_DIR" "helper-dir"

if [[ ! -d "$SOURCE" ]]; then
  echo "нет каталога исходников: $SOURCE" >&2
  exit 1
fi

# Секреты рядом с юнитами не копируем, даже если их положили в source.
reject_secret_name() {
  local name=$1
  case "$name" in
    config_keys.py|contacts_data.py|.env|.env.*|*.pem|*.key|*secret*|*token*)
      echo "отказ: секретный файл $name" >&2
      exit 1
      ;;
  esac
  case "$name" in
    */*|.*|*..*)
      echo "отказ: плохое имя $name" >&2
      exit 1
      ;;
  esac
}

while read -r kind policy mode name; do
  [[ -n "${name:-}" ]] || continue
  reject_secret_name "$name"
  case "$kind" in
    unit|helper) ;;
    *)
      echo "плохой тип в списке: $kind" >&2
      exit 1
      ;;
  esac
  case "$policy" in
    always|if-present) ;;
    *)
      echo "плохая политика: $policy" >&2
      exit 1
      ;;
  esac
  case "$mode" in
    644|755) ;;
    *)
      echo "плохие права: $mode" >&2
      exit 1
      ;;
  esac
done <<<"$MANIFEST"

mkdir -p -- "$HELPER_DIR"
if [[ ! -d "$UNIT_DIR" ]]; then
  echo "нет каталога юнитов: $UNIT_DIR" >&2
  exit 1
fi

WORK=$(mktemp -d)
CHANGED_DEST=()
CHANGED_BACKUP=()
CHANGED_WAS=()
RESTORED=0

restore_changed() {
  local i
  if [[ "$RESTORED" -eq 1 ]]; then
    return 0
  fi
  RESTORED=1
  if [[ "${#CHANGED_DEST[@]}" -eq 0 ]]; then
    return 0
  fi
  for i in "${!CHANGED_DEST[@]}"; do
    if [[ "${CHANGED_WAS[$i]}" -eq 1 ]]; then
      cp -a -- "${CHANGED_BACKUP[$i]}" "${CHANGED_DEST[$i]}"
    else
      rm -f -- "${CHANGED_DEST[$i]}"
    fi
  done
  RESTORED=1
}

on_err() {
  echo "сбой установки юнитов, возвращаю прежние файлы" >&2
  restore_changed || true
}

trap on_err ERR
trap 'rm -rf -- "$WORK"' EXIT

remember() {
  local dest=$1 base
  base=$(basename -- "$dest")
  if [[ -f "$dest" ]]; then
    cp -a -- "$dest" "$WORK/$base"
    CHANGED_WAS+=(1)
    CHANGED_BACKUP+=("$WORK/$base")
  else
    CHANGED_WAS+=(0)
    CHANGED_BACKUP+=("")
  fi
  CHANGED_DEST+=("$dest")
}

write_file() {
  local src=$1 dest=$2 mode=$3
  local same=0 cur=""
  if [[ -L "$dest" ]]; then
    echo "ссылку не затираю: $dest" >&2
    restore_changed
    exit 1
  fi
  if [[ -e "$dest" && ! -f "$dest" ]]; then
    echo "это не файл: $dest" >&2
    restore_changed
    exit 1
  fi
  if [[ -f "$dest" ]] && cmp -s -- "$src" "$dest"; then
    same=1
  fi
  if [[ -f "$dest" ]]; then
    cur=$(stat -c %a -- "$dest")
    cur=${cur#0}
  fi
  if [[ "$same" -eq 1 && "$cur" == "$mode" ]]; then
    echo "без изменений: $(basename -- "$dest")"
    return 0
  fi
  remember "$dest"
  if [[ "$same" -eq 1 ]]; then
    chmod "$mode" -- "$dest"
  else
    install -m "$mode" -- "$src" "$dest"
  fi
  echo "обновлён: $(basename -- "$dest")"
  return 0
}

changed=0
verify_files=()

while read -r kind policy mode name; do
  [[ -n "${name:-}" ]] || continue
  src="$SOURCE/$name"
  if [[ ! -f "$src" ]]; then
    echo "нет исходника: $name" >&2
    restore_changed
    exit 1
  fi
  if [[ "$kind" == "helper" ]]; then
    dest="$HELPER_DIR/$name"
  else
    dest="$UNIT_DIR/$name"
  fi
  if [[ "$policy" == "if-present" && ! -f "$dest" ]]; then
    echo "на сервере нет, не добавляю: $name"
    continue
  fi
  before=${#CHANGED_DEST[@]}
  write_file "$src" "$dest" "$mode"
  if [[ "${#CHANGED_DEST[@]}" -gt "$before" ]]; then
    changed=1
  fi
  if [[ "$kind" == "unit" && -f "$dest" ]]; then
    verify_files+=("$dest")
  fi
done <<<"$MANIFEST"

if [[ "${#verify_files[@]}" -eq 0 ]]; then
  echo "нечего проверять systemd-analyze" >&2
  restore_changed
  exit 1
fi

if ! "$ANALYZE_BIN" verify "${verify_files[@]}"; then
  echo "systemd-analyze verify не прошёл, возвращаю прежние файлы" >&2
  restore_changed
  exit 1
fi

if [[ "$changed" -eq 1 ]]; then
  if ! "$SYSTEMCTL_BIN" daemon-reload; then
    echo "daemon-reload не прошёл, возвращаю прежние файлы" >&2
    restore_changed
    "$SYSTEMCTL_BIN" daemon-reload || true
    exit 1
  fi
fi

echo "юниты systemd готовы"
