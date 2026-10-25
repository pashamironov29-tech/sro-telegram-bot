#!/bin/bash
# Выкладка отслеживаемых файлов на VPS из GitHub Actions.
# На сервере git нет: git archive на runner, затем rsync в /opt/sro-bot.
# Боевой config_keys.py не читаем и не перезаписываем.
# Каталог vps/ целиком не затираем. Живые юниты ставит
# scripts/install_systemd_units.sh: в /etc/systemd/system и один
# sync_failure_alert.sh. Синки и таймеры не перезапускаются.
set -euo pipefail
set +x

APP_DIR="/opt/sro-bot"
MIN_FREE_KB=$((300 * 1024))
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

SSH_BASE=()
KEY_FILE=""
KNOWN_FILE=""
STAGE=""
ITEMIZE=""
PY_LIST=""
BACKUP=""
COPY_STARTED=0
FINISHED=0
IN_HANDLER=0

EXCLUDES=(
  'config_keys.py'
  'contacts_data.py'
  '.env*'
  '*.pem'
  '*.key'
  'vps/'
  '.github/'
  'tests/'
  'docs/'
  'venv/'
  'backups/'
  'sro_data/'
  'sro files/'
  'logs/'
  '*.log'
  'bot_users.json*'
  'session_state_*'
  'user_sro_context.json'
  'contacts_access.json'
  'reestr_cache.json*'
  '*_cache*.json'
  'specialist_mode*.json'
  'nrs_link_mode.json'
  'doc_checklists.json'
  'feedback_questions.jsonl'
  '*.sqlite*'
  '__pycache__/'
)

cleanup() {
  if [[ -n "${KEY_FILE}" ]]; then
    rm -f -- "$KEY_FILE"
  fi
  if [[ -n "${KNOWN_FILE}" ]]; then
    rm -f -- "$KNOWN_FILE"
  fi
  if [[ -n "${STAGE}" && -d "${STAGE}" ]]; then
    rm -rf -- "$STAGE"
  fi
  if [[ -n "${ITEMIZE}" ]]; then
    rm -f -- "$ITEMIZE"
  fi
  if [[ -n "${PY_LIST}" ]]; then
    rm -f -- "$PY_LIST"
  fi
}

die_before_copy() {
  echo "$1"
  echo "Файлы на сервере не менялись."
  exit 1
}

redact_stream() {
  sed -E \
    -e 's/[0-9]{6,}:[A-Za-z0-9_-]{30,}/***REDACTED***/g' \
    -e 's#/bot[0-9]+:[A-Za-z0-9_-]+#/bot***REDACTED***#g' \
    -e 's/\bbot[0-9]+:[A-Za-z0-9_-]{20,}/bot***REDACTED***/g' \
    -e 's/sk-[A-Za-z0-9_-]{10,}/***REDACTED***/g' \
    -e 's/sk_(live|test)_[A-Za-z0-9]+/***REDACTED***/g' \
    -e 's/\b(live|test)_[A-Za-z0-9]{8,}/***REDACTED***/g' \
    -e 's/[A-Za-z0-9._%+=-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/***REDACTED***/g' \
    -e 's/([?&]token=)[^&[:space:]]+/\1***REDACTED***/g' \
    -e 's/[Aa]uthorization[[:space:]]*[:=][[:space:]]*[^[:space:],;]+/Authorization ***REDACTED***/g'
}

parse_itemize_marks() {
  local line code path
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" ]] && continue
    code=${line%% *}
    path=${line#"$code"}
    path=${path#"${path%%[![:space:]]*}"}
    [[ ${#code} -eq 11 ]] || continue
    if [[ "$code" == ?f+++++++++ ]]; then
      printf 'F %s\n' "${path%/}"
    elif [[ "$code" == ?d+++++++++ ]]; then
      printf 'D %s\n' "${path%/}"
    fi
  done
}

self_check() {
  local sample out raw cleaned plain kept token_body bot_body
  sample=$(printf '%s\n' \
    '>f+++++++++ b.txt' \
    '>fc........ a.txt' \
    'cd+++++++++ sub/' \
    '>f+++++++++ sub/c.txt' \
    '.d..t...... sub')
  out=$(printf '%s\n' "$sample" | parse_itemize_marks)
  if ! printf '%s\n' "$out" | grep -qx 'F b.txt'; then
    echo "self-check: нет нового файла" >&2
    return 1
  fi
  if ! printf '%s\n' "$out" | grep -qx 'F sub/c.txt'; then
    echo "self-check: нет вложенного файла" >&2
    return 1
  fi
  if ! printf '%s\n' "$out" | grep -qx 'D sub'; then
    echo "self-check: нет нового каталога" >&2
    return 1
  fi
  if printf '%s\n' "$out" | grep -q 'a.txt'; then
    echo "self-check: изменённый файл попал в новые" >&2
    return 1
  fi
  token_body=$(printf 'A%.0s' {1..30})
  bot_body=$(printf 'B%.0s' {1..20})
  raw="token 123456:${token_body} sk-abcdefghijklmnopqrstuvwxyz live_abcdefgh user@example.com bot123456:${bot_body}"
  cleaned=$(printf '%s\n' "$raw" | redact_stream)
  if [[ "$cleaned" == *"${token_body}"* || "$cleaned" == *sk-abcdefghijklmnopqrstuvwxyz* ]]; then
    echo "self-check: токен остался" >&2
    return 1
  fi
  if [[ "$cleaned" == *live_abcdefgh* || "$cleaned" == *user@example.com* || "$cleaned" == *"${bot_body}"* ]]; then
    echo "self-check: секрет остался" >&2
    return 1
  fi
  if [[ "$cleaned" != *REDACTED* ]]; then
    echo "self-check: нет отметки REDACTED" >&2
    return 1
  fi
  plain='ИНН 7700000001 не найден'
  kept=$(printf '%s\n' "$plain" | redact_stream)
  if [[ "$kept" != "$plain" ]]; then
    echo "self-check: обычный текст изменился" >&2
    return 1
  fi
  echo "self-check ok"
}

remote() {
  "${SSH_BASE[@]}" "$VPS_USER@$VPS_HOST" "$@"
}

remote_script() {
  "${SSH_BASE[@]}" "$VPS_USER@$VPS_HOST" bash -s -- "$@"
}

dump_journal() {
  remote "journalctl -u sro-bot -n 20 --no-pager || true; echo '-----'; journalctl -u sro-max-bot -n 20 --no-pager || true" \
    | redact_stream || true
}

have_exclude() {
  local needle=$1
  local pat
  for pat in "${EXCLUDES[@]}"; do
    if [[ "$pat" == "$needle" ]]; then
      return 0
    fi
  done
  return 1
}

append_excludes() {
  local line
  while IFS= read -r line || [[ -n "$line" ]]; do
    line=${line#"${line%%[![:space:]]*}"}
    line=${line%"${line##*[![:space:]]}"}
    [[ -z "$line" || "$line" == \#* ]] && continue
    EXCLUDES+=("$line")
  done
}

path_excluded() {
  local rel=$1
  local base=${rel##*/}
  case "$rel" in
    vps/*|.github/*|tests/*|docs/*|venv/*|backups/*|sro_data/*|logs/*|"sro files"/*|__pycache__/*|*/__pycache__/*)
      return 0
      ;;
  esac
  case "$base" in
    config_keys.py|contacts_data.py|*.pem|*.key|*.log|*.sqlite*|bot_users.json*|reestr_cache.json*|specialist_mode*.json|*_cache*.json|.env|.env.*)
      return 0
      ;;
  esac
  return 1
}

rollback() {
  echo "Откат из ${BACKUP}."
  remote_script "$BACKUP" "$APP_DIR" <<'EOS'
set -euo pipefail
backup=$1
app=$2
safe_rel() {
  local rel=$1
  [[ -n "$rel" ]] || return 1
  [[ "$rel" != /* ]] || return 1
  [[ "$rel" != "." && "$rel" != ".." ]] || return 1
  [[ "$rel" != ../* && "$rel" != */.. && "$rel" != */../* ]] || return 1
  case "$rel" in
    backups|backups/*) return 1 ;;
  esac
  return 0
}
if [[ -d "$backup/files" ]]; then
  while IFS= read -r -d '' src; do
    rel=${src#"$backup/files"/}
    if ! safe_rel "$rel"; then
      echo "пропуск восстановления" >&2
      continue
    fi
    mkdir -p -- "$(dirname -- "$app/$rel")"
    cp -a -- "$src" "$app/$rel"
  done < <(find "$backup/files" -type f -print0)
fi
dirs=()
if [[ -f "$backup/changes.txt" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" ]] && continue
    code=${line%% *}
    path=${line#"$code"}
    path=${path#"${path%%[![:space:]]*}"}
    [[ ${#code} -eq 11 ]] || continue
    if [[ "$code" == ?f+++++++++ ]]; then
      path=${path%/}
      if safe_rel "$path" && [[ -f "$app/$path" ]]; then
        rm -f -- "$app/$path"
      fi
    elif [[ "$code" == ?d+++++++++ ]]; then
      path=${path%/}
      if safe_rel "$path"; then
        dirs+=("$path")
      fi
    fi
  done < "$backup/changes.txt"
fi
if ((${#dirs[@]})); then
  while IFS= read -r dir; do
    [[ -n "$dir" ]] || continue
    rmdir -- "$app/$dir" 2>/dev/null || true
  done < <(printf '%s\n' "${dirs[@]}" | LC_ALL=C sort -r)
fi
systemctl restart sro-bot sro-max-bot || true
echo "sro-bot: $(systemctl is-active sro-bot || true)"
echo "sro-max-bot: $(systemctl is-active sro-max-bot || true)"
EOS
}

on_error() {
  local line=$1
  if [[ "${IN_HANDLER}" -eq 1 ]]; then
    exit 1
  fi
  IN_HANDLER=1
  trap - ERR
  set +e
  echo "Сбой на строке ${line}."
  if [[ "${COPY_STARTED}" -eq 1 && "${FINISHED}" -eq 0 ]]; then
    echo "pip не откатывался."
    dump_journal || true
    rollback || echo "Откат не завершился."
    prune_backups 10 "$BACKUP" || echo "Старые бэкапы не почистились."
    dump_journal || true
  else
    echo "Файлы на сервере не менялись."
  fi
  exit 1
}

prepare_ssh() {
  if [[ -z "${VPS_HOST:-}" || -z "${VPS_USER:-}" || -z "${VPS_SSH_KEY:-}" ]]; then
    die_before_copy "Не заданы VPS_HOST, VPS_USER или VPS_SSH_KEY."
  fi
  if [[ -z "${VPS_PORT:-}" ]]; then
    VPS_PORT=22
  fi
  if [[ ! "$VPS_PORT" =~ ^[0-9]+$ ]] || (( VPS_PORT < 1 || VPS_PORT > 65535 )); then
    die_before_copy "VPS_PORT некорректен."
  fi
  if [[ ! "$VPS_HOST" =~ ^[A-Za-z0-9._-]+$ ]]; then
    die_before_copy "VPS_HOST некорректен."
  fi
  if [[ ! "$VPS_USER" =~ ^[A-Za-z0-9._-]+$ ]]; then
    die_before_copy "VPS_USER некорректен."
  fi
  command -v ssh >/dev/null || die_before_copy "На runner нет ssh."
  command -v ssh-keyscan >/dev/null || die_before_copy "На runner нет ssh-keyscan."
  command -v rsync >/dev/null || die_before_copy "На runner нет rsync."
  command -v git >/dev/null || die_before_copy "На runner нет git."

  KEY_FILE=$(mktemp)
  chmod 600 "$KEY_FILE"
  printf '%s\n' "$VPS_SSH_KEY" > "$KEY_FILE"
  chmod 600 "$KEY_FILE"
  unset VPS_SSH_KEY
  if [[ ! -s "$KEY_FILE" ]]; then
    die_before_copy "VPS_SSH_KEY пуст."
  fi

  KNOWN_FILE=$(mktemp)
  chmod 600 "$KNOWN_FILE"
  if [[ -n "${VPS_KNOWN_HOSTS:-}" ]]; then
    printf '%s\n' "$VPS_KNOWN_HOSTS" > "$KNOWN_FILE"
    unset VPS_KNOWN_HOSTS
  else
    ssh-keyscan -p "$VPS_PORT" -T 10 "$VPS_HOST" > "$KNOWN_FILE" || true
  fi
  if [[ ! -s "$KNOWN_FILE" ]]; then
    die_before_copy "Не удалось получить ключ хоста. Задайте VPS_KNOWN_HOSTS."
  fi

  SSH_BASE=(
    ssh
    -i "$KEY_FILE"
    -o "UserKnownHostsFile=${KNOWN_FILE}"
    -o StrictHostKeyChecking=yes
    -o IdentitiesOnly=yes
    -o BatchMode=yes
    -o ConnectTimeout=20
    -o ServerAliveInterval=15
    -o ServerAliveCountMax=4
    -p "$VPS_PORT"
  )
}

prune_backups() {
  local keep=$1
  local protect=${2:-}
  remote_script "$APP_DIR/backups" "$keep" "$protect" <<'EOS'
set -euo pipefail
dir=$1
keep=$2
protect=$3
mkdir -p -- "$dir"
items=()
while IFS= read -r item; do
  [[ -n "$item" ]] || continue
  case "$item" in
    "$dir"/auto-*) items+=("$item") ;;
    *) echo "неожиданный путь бэкапа" >&2; exit 1 ;;
  esac
done < <(find "$dir" -mindepth 1 -maxdepth 1 -type d -name 'auto-*' | LC_ALL=C sort)
count=${#items[@]}
if (( count <= keep )); then
  exit 0
fi
extra=$((count - keep))
removed=0
for item in "${items[@]}"; do
  if (( removed >= extra )); then
    break
  fi
  if [[ -n "$protect" && "$item" == "$protect" ]]; then
    continue
  fi
  rm -rf -- "$item"
  removed=$((removed + 1))
done
EOS
}

install_units() {
  local installer pack remote_tmp name rc
  installer="$ROOT/scripts/install_systemd_units.sh"
  pack=$(mktemp -d)
  remote_tmp=""
  rc=0
  finish_units() {
    local code=$1
    rm -rf -- "$pack"
    if [[ -n "$remote_tmp" ]]; then
      remote "rm -rf -- ${remote_tmp}" || true
    fi
    return "$code"
  }
  if [[ ! -f "$installer" ]]; then
    echo "нет scripts/install_systemd_units.sh"
    finish_units 1
    return
  fi
  cp -- "$installer" "$pack/install_systemd_units.sh"
  chmod 755 "$pack/install_systemd_units.sh"
  local names
  names=$(bash "$installer" --list)
  if [[ -z "$names" ]]; then
    echo "пустой список юнитов"
    finish_units 1
    return
  fi
  while IFS= read -r name || [[ -n "$name" ]]; do
    [[ -z "$name" ]] && continue
    case "$name" in
      config_keys.py|contacts_data.py|.env|.env.*|*.pem|*.key)
        echo "в списке юнитов секрет: $name" >&2
        finish_units 1
        return
        ;;
      */*|.*|*..*)
        echo "плохое имя юнита: $name" >&2
        finish_units 1
        return
        ;;
    esac
    if [[ ! -f "$STAGE/vps/$name" ]]; then
      echo "в архиве нет vps/$name" >&2
      finish_units 1
      return
    fi
    cp -- "$STAGE/vps/$name" "$pack/$name"
  done <<<"$names"
  remote_tmp=$(remote "mktemp -d /tmp/sro-units.XXXXXXXX") || rc=$?
  remote_tmp=${remote_tmp//[[:space:]]/}
  if [[ "$rc" -ne 0 || ! "$remote_tmp" =~ ^/tmp/sro-units\.[A-Za-z0-9]+$ ]]; then
    echo "плохой временный каталог юнитов"
    remote_tmp=""
    finish_units 1
    return
  fi
  if ! rsync -rlptz --checksum \
    -e "$RSYNC_RSH" \
    "${pack}/" \
    "${VPS_USER}@${VPS_HOST}:${remote_tmp}/"; then
    echo "не удалось передать юниты"
    finish_units 1
    return
  fi
  if ! remote "bash ${remote_tmp}/install_systemd_units.sh --source ${remote_tmp}"; then
    echo "Юниты systemd не встали."
    finish_units 1
    return
  fi
  finish_units 0
}

fingerprint() {
  local path=$1
  local out
  out=$(remote_script "$path" <<'EOS'
set -euo pipefail
path=$1
if [[ -f "$path" ]]; then
  stat -c '%s %Y' -- "$path"
else
  printf '%s\n' MISSING
fi
EOS
)
  printf '%s' "$out"
}

if [[ "${1:-}" == "--self-check" ]]; then
  self_check
  exit 0
fi

trap cleanup EXIT
trap 'on_error $LINENO' ERR

cd "$ROOT"

if [[ -n "${DEPLOY_RSYNC_EXCLUDES:-}" ]]; then
  append_excludes <<< "$DEPLOY_RSYNC_EXCLUDES"
fi
have_exclude 'config_keys.py' || die_before_copy "Нет исключения config_keys.py."
have_exclude 'vps/' || die_before_copy "Нет исключения vps/."

prepare_ssh

free_kb=$(remote_script "$APP_DIR" <<'EOS'
set -euo pipefail
app=$1
if [[ ! -d "$app" ]]; then
  echo "NO_DIR" >&2
  exit 1
fi
df -Pk -- "$app" | awk 'NR==2 {print $4}'
EOS
)
free_kb=${free_kb//[[:space:]]/}
if [[ ! "$free_kb" =~ ^[0-9]+$ ]]; then
  die_before_copy "Не удалось проверить свободное место."
fi
if (( free_kb <= MIN_FREE_KB )); then
  die_before_copy "Свободно ${free_kb} КБ, нужно больше 300 МБ."
fi

PY=$(remote_script <<'EOS'
set -euo pipefail
show=$(systemctl show -p ExecStart --value sro-bot 2>/dev/null || true)
py=""
if [[ "$show" =~ path=([^[:space:];]+) ]]; then
  py="${BASH_REMATCH[1]}"
fi
if [[ -z "$py" || ! -x "$py" ]]; then
  py="/opt/sro-bot/venv/bin/python"
fi
if [[ ! -x "$py" ]]; then
  echo "NO_PYTHON" >&2
  exit 1
fi
printf '%s\n' "$py"
EOS
)
PY=${PY//[[:space:]]/}
if [[ ! "$PY" =~ ^/[A-Za-z0-9._+/-]+$ || "$PY" != *python* ]]; then
  die_before_copy "Не удалось определить python."
fi

SHA=$(git rev-parse HEAD)
if [[ ! "$SHA" =~ ^[0-9a-f]{40}$ ]]; then
  die_before_copy "Некорректный SHA."
fi
if [[ -n "${GITHUB_SHA:-}" && "${GITHUB_SHA}" != "$SHA" ]]; then
  die_before_copy "HEAD не совпадает с GITHUB_SHA."
fi

old_raw=$(remote "cat $(printf '%q' "$APP_DIR/DEPLOYED_COMMIT") 2>/dev/null || true" || true)
old_raw=${old_raw//[[:space:]]/}
if [[ "$old_raw" =~ ^[0-9a-f]{7,40}$ ]]; then
  OLD_SHA=$old_raw
else
  OLD_SHA=none
fi

STAGE=$(mktemp -d)
git archive --format=tar HEAD | tar -x -C "$STAGE"
PY_LIST=$(mktemp)
while IFS= read -r rel; do
  [[ "$rel" == *.py ]] || continue
  if path_excluded "$rel"; then
    continue
  fi
  printf '%s\n' "$rel"
done < <(git ls-files '*.py') > "$PY_LIST"
if [[ ! -s "$PY_LIST" ]]; then
  die_before_copy "Список py-файлов пуст."
fi

stamp=$(remote "date +%Y%m%d-%H%M%S")
stamp=${stamp//[[:space:]]/}
if [[ ! "$stamp" =~ ^[0-9]{8}-[0-9]{6}$ ]]; then
  die_before_copy "Некорректная метка времени."
fi

BACKUP=$(remote_script "$APP_DIR" "$stamp" <<'EOS'
set -euo pipefail
app=$1
stamp=$2
base="$app/backups/auto-$stamp"
dest=$base
n=2
while [[ -e "$dest" ]]; do
  dest="${base}-$n"
  n=$((n + 1))
  if (( n > 20 )); then
    echo "TOO_MANY" >&2
    exit 1
  fi
done
mkdir -p -- "$dest/files"
chmod 700 "$dest"
printf '%s\n' "$dest"
EOS
)
BACKUP=${BACKUP//[[:space:]]/}
if [[ ! "$BACKUP" =~ ^/opt/sro-bot/backups/auto-[0-9]{8}-[0-9]{6}(-[0-9]+)?$ ]]; then
  die_before_copy "Некорректный каталог бэкапа."
fi
echo "Бэкап: ${BACKUP}"

remote_script "$BACKUP" "$OLD_SHA" "$SHA" <<'EOS'
set -euo pipefail
backup=$1
prev=$2
target=$3
umask 077
cat > "$backup/DEPLOYED_FROM" <<EOF
previous: ${prev}
target: ${target}
EOF
chmod 700 "$backup"
EOS

fp_config_before=$(fingerprint "$APP_DIR/config_keys.py")
fp_contacts_before=$(fingerprint "$APP_DIR/contacts_data.py")

exclude_args=()
for pat in "${EXCLUDES[@]}"; do
  exclude_args+=(--exclude "$pat")
done
RSYNC_RSH=$(printf 'ssh -i %q -o UserKnownHostsFile=%q -o StrictHostKeyChecking=yes -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=20 -p %q' \
  "$KEY_FILE" "$KNOWN_FILE" "$VPS_PORT")

ITEMIZE=$(mktemp)
COPY_STARTED=1
set +e
rsync -rlptz --checksum \
  --backup --backup-dir="${BACKUP}/files" \
  --itemize-changes \
  "${exclude_args[@]}" \
  -e "$RSYNC_RSH" \
  "${STAGE}/" \
  "${VPS_USER}@${VPS_HOST}:${APP_DIR}/" \
  > "$ITEMIZE"
rsync_rc=$?
set -e
changes_dest=$(printf '%q' "$BACKUP/changes.txt")
if ! remote "cat > ${changes_dest}" < "$ITEMIZE"; then
  echo "Не удалось записать changes.txt."
  false
fi
if [[ "$rsync_rc" -ne 0 ]]; then
  echo "Копирование не удалось, код ${rsync_rc}."
  false
fi

fp_config_after=$(fingerprint "$APP_DIR/config_keys.py")
fp_contacts_after=$(fingerprint "$APP_DIR/contacts_data.py")
if [[ "$fp_config_before" != "$fp_config_after" || "$fp_contacts_before" != "$fp_contacts_after" ]]; then
  echo "config_keys.py или contacts_data.py изменились. Откат."
  false
fi

py_dest=$(printf '%q' "$BACKUP/py_files.txt")
if ! remote "cat > ${py_dest}" < "$PY_LIST"; then
  echo "Не удалось передать список py."
  false
fi

remote_script "$PY" "$APP_DIR" <<'EOS'
set -euo pipefail
py=$1
app=$2
"$py" -m pip install -r "$app/requirements.txt"
EOS

remote_script "$PY" "$APP_DIR" "$BACKUP/py_files.txt" <<'EOS'
set -euo pipefail
py=$1
app=$2
list=$3
export PYTHONPYCACHEPREFIX="/tmp/sro-deploy-pyc"
rm -rf -- "$PYTHONPYCACHEPREFIX"
mkdir -p -- "$PYTHONPYCACHEPREFIX"
while IFS= read -r rel || [[ -n "$rel" ]]; do
  [[ -z "$rel" ]] && continue
  case "$rel" in
    *.py) ;;
    *) continue ;;
  esac
  case "$rel" in
    /*|*..*|../*|*/../*) echo "плохой путь" >&2; exit 1 ;;
  esac
  "$py" -m py_compile "$app/$rel"
done < "$list"
rm -rf -- "$PYTHONPYCACHEPREFIX"
EOS

install_units

restart_out=$(remote_script <<'EOS'
set -euo pipefail
systemctl restart sro-bot sro-max-bot
bot=$(systemctl show -p NRestarts --value sro-bot | tr -d '[:space:]')
max=$(systemctl show -p NRestarts --value sro-max-bot | tr -d '[:space:]')
printf 'NRESTART bot=%s\n' "$bot"
printf 'NRESTART max=%s\n' "$max"
EOS
)
n0_bot=$(printf '%s\n' "$restart_out" | sed -n 's/^NRESTART bot=//p' | tail -n 1)
n0_max=$(printf '%s\n' "$restart_out" | sed -n 's/^NRESTART max=//p' | tail -n 1)
if [[ ! "$n0_bot" =~ ^[0-9]+$ || ! "$n0_max" =~ ^[0-9]+$ ]]; then
  echo "Не прочитался NRestarts."
  false
fi

sleep 20

health_out=$(remote_script <<'EOS'
set -euo pipefail
bot_active=$(systemctl is-active sro-bot || true)
max_active=$(systemctl is-active sro-max-bot || true)
bot_restarts=$(systemctl show -p NRestarts --value sro-bot | tr -d '[:space:]')
max_restarts=$(systemctl show -p NRestarts --value sro-max-bot | tr -d '[:space:]')
printf 'ACTIVE bot=%s\n' "$bot_active"
printf 'ACTIVE max=%s\n' "$max_active"
printf 'NRESTART bot=%s\n' "$bot_restarts"
printf 'NRESTART max=%s\n' "$max_restarts"
EOS
)
active_bot=$(printf '%s\n' "$health_out" | sed -n 's/^ACTIVE bot=//p' | tail -n 1)
active_max=$(printf '%s\n' "$health_out" | sed -n 's/^ACTIVE max=//p' | tail -n 1)
n1_bot=$(printf '%s\n' "$health_out" | sed -n 's/^NRESTART bot=//p' | tail -n 1)
n1_max=$(printf '%s\n' "$health_out" | sed -n 's/^NRESTART max=//p' | tail -n 1)
dump_journal || true
if [[ "$active_bot" != "active" || "$active_max" != "active" ]]; then
  echo "Служба не active."
  false
fi
if [[ ! "$n1_bot" =~ ^[0-9]+$ || ! "$n1_max" =~ ^[0-9]+$ ]]; then
  echo "Не прочитался NRestarts после ожидания."
  false
fi
if (( n1_bot > n0_bot || n1_max > n0_max )); then
  echo "NRestarts вырос за 20 с."
  false
fi

remote_script "$APP_DIR" "$SHA" <<'EOS'
set -euo pipefail
app=$1
sha=$2
tmp="$app/DEPLOYED_COMMIT.tmp"
printf '%s\n' "$sha" > "$tmp"
mv -f -- "$tmp" "$app/DEPLOYED_COMMIT"
EOS

FINISHED=1
if ! prune_backups 10 "$BACKUP"; then
  echo "Старые бэкапы не почистились."
fi
echo "Выкладка завершена: ${SHA}"
