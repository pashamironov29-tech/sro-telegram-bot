"""Журнал пользователей бота → bot_users.json.

Пишет chat_id, имя, username, первый и последний заход.
Список смотри: файл bot_users.json или команда /users (только админ).

Telegram и MAX — два процесса в одном каталоге. threading.Lock их не
разводит, поэтому запись идёт через свой tmp и lock-файл. На Windows
fcntl нет: два бота сразу делят журнал без межпроцессной блокировки.
Сбой журнала не должен обрывать ответ пользователю.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from html import escape as html_escape
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows: межпроцессного flock нет
    fcntl = None

ROOT = Path(__file__).resolve().parent
USERS_FILE = ROOT / "bot_users.json"

_thread_lock = threading.Lock()
_corrupt_warned = False
# Постоянная ошибка чтения не должна печататься на каждое сообщение.
READ_ERROR_LOG_INTERVAL_SEC = 10 * 60
_read_error_logged_at: float | None = None
_monotonic = time.monotonic


def _html(text: str) -> str:
    return html_escape(str(text or ""), quote=False)


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _log(text: str) -> None:
    """Короткая строка в лог процесса. Без имён, id и кусков журнала."""
    print(text, flush=True)


def _log_read_error() -> None:
    """Одна строка на окно. После успешного чтения окно сбрасывается."""
    global _read_error_logged_at
    now = _monotonic()
    last = _read_error_logged_at
    if last is not None and now - last < READ_ERROR_LOG_INTERVAL_SEC:
        return
    _read_error_logged_at = now
    _log("users_log: журнал не прочитался, запись пропускаю")


def _note_read_ok() -> None:
    global _read_error_logged_at
    _read_error_logged_at = None


@contextmanager
def _journal_lock():
    """Чтение-изменение-запись целиком.

    На Linux flock на bot_users.json.lock держит и второй процесс.
    На Windows fcntl нет — остаётся блокировка потока, tmp всё равно уникальный.
    """
    _thread_lock.acquire()
    handle = None
    try:
        if fcntl is not None:
            lock_path = USERS_FILE.with_name(USERS_FILE.name + ".lock")
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            handle = open(lock_path, "a+b")
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if handle is not None:
            try:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            handle.close()
        _thread_lock.release()


def _quarantine_corrupt() -> bool:
    """Один раз переложить битый журнал в bot_users.json.bad-YYYYmmdd-HHMMSS.

    False — файл на месте, новый журнал поверх него писать нельзя.
    """
    global _corrupt_warned
    if not USERS_FILE.is_file():
        return True
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    dest = USERS_FILE.with_name(f"{USERS_FILE.name}.bad-{stamp}")
    extra = 0
    while dest.exists():
        extra += 1
        dest = USERS_FILE.with_name(f"{USERS_FILE.name}.bad-{stamp}-{extra}")
    try:
        os.replace(USERS_FILE, dest)
    except FileNotFoundError:
        return True
    except OSError:
        if not _corrupt_warned:
            _log("bot_users.json повреждён, переложить не удалось, журнал не затираю")
            _corrupt_warned = True
        return False
    _log(f"bot_users.json повреждён, переложен в {dest.name}, начинаю новый журнал")
    return True


def _load() -> dict | None:
    """Журнал или None, если писать поверх файла нельзя.

    None — битый файл не удалось убрать или чтение сорвалось (нет прав, диск).
    Пустым словарём это не подменяем: следующая запись стёрла бы историю.
    """
    if not USERS_FILE.is_file():
        _note_read_ok()
        return {"users": {}}
    try:
        raw = USERS_FILE.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        if not _quarantine_corrupt():
            return None
        _note_read_ok()
        return {"users": {}}
    except OSError:
        # Нет прав или диск: файл не битый, в .bad не уносим и поверх не пишем.
        _log_read_error()
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        if not _quarantine_corrupt():
            return None
        _note_read_ok()
        return {"users": {}}
    if not isinstance(data, dict):
        if not _quarantine_corrupt():
            return None
        _note_read_ok()
        return {"users": {}}
    users = data.get("users")
    if not isinstance(users, dict):
        data["users"] = {}
    _note_read_ok()
    return data


def _save(data: dict) -> None:
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = USERS_FILE.with_name(
        f"{USERS_FILE.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp"
    )
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, USERS_FILE)
    finally:
        if tmp.is_file():
            try:
                tmp.unlink()
            except OSError:
                pass


def _user_from_message(message) -> dict:
    user = getattr(message, "from_user", None)
    chat = getattr(message, "chat", None)
    chat_id = getattr(chat, "id", None) or getattr(user, "id", None)
    first = (getattr(user, "first_name", None) or "").strip()
    last = (getattr(user, "last_name", None) or "").strip()
    username = (getattr(user, "username", None) or "").strip()
    full_name = " ".join(p for p in (first, last) if p).strip() or "—"
    return {
        "chat_id": chat_id,
        "username": username,
        "full_name": full_name,
        "first_name": first,
        "last_name": last,
    }


def _touch_user(message, *, event: str) -> bool:
    info = _user_from_message(message)
    chat_id = info.get("chat_id")
    if chat_id is None:
        return False
    key = str(chat_id)
    now = _now_iso()
    is_new = False
    with _journal_lock():
        data = _load()
        if data is None:
            return False
        users = data.setdefault("users", {})
        row = users.get(key)
        if not row:
            is_new = True
            users[key] = {
                "chat_id": chat_id,
                "username": info["username"],
                "full_name": info["full_name"],
                "first_seen": now,
                "last_seen": now,
                "starts": 1 if event == "start" else 0,
                "messages": 0 if event == "start" else 1,
            }
        else:
            row["username"] = info["username"] or row.get("username") or ""
            row["full_name"] = info["full_name"] or row.get("full_name") or "—"
            row["last_seen"] = now
            if event == "start":
                row["starts"] = int(row.get("starts") or 0) + 1
            else:
                row["messages"] = int(row.get("messages") or 0) + 1
        data["updated_at"] = now
        data["total_users"] = len(users)
        _save(data)
    return is_new


def touch_user(message, *, event: str = "message") -> bool:
    """
    Зафиксировать визит. True — новый пользователь (первый раз).

    Ошибка диска или журнала наружу не летит: ответ бота важнее записи.
    """
    try:
        return _touch_user(message, event=event)
    except Exception:
        _log("users_log: визит не записан")
        return False


def users_count() -> int:
    try:
        with _journal_lock():
            data = _load()
            if not data:
                return 0
            return len(data.get("users") or {})
    except Exception:
        _log("users_log: не удалось посчитать пользователей")
        return 0


def list_users(*, limit: int = 50) -> list[dict]:
    try:
        with _journal_lock():
            data = _load()
            users = list((data.get("users") or {}).values()) if data else []
    except Exception:
        _log("users_log: не удалось прочитать журнал")
        return []
    users.sort(key=lambda u: u.get("last_seen") or "", reverse=True)
    return users[:limit]


def _format_users_report(*, limit: int) -> str:
    total = users_count()
    rows = list_users(limit=limit)
    lines = [
        f"👥 <b>Пользователи бота:</b> {total}",
        f"<i>Файл: <code>{USERS_FILE.name}</code></i>",
        "",
    ]
    if not rows:
        lines.append("Пока никто не заходил.")
        return "\n".join(lines)
    for i, u in enumerate(rows, 1):
        uname = u.get("username") or ""
        mention = f"@{_html(uname)}" if uname else "без @username"
        lines.append(
            f"{i}. <b>{_html(u.get('full_name') or '—')}</b> ({mention})\n"
            f"   id <code>{u.get('chat_id')}</code> · "
            f"первый {u.get('first_seen', '—')} · "
            f"был {u.get('last_seen', '—')} · "
            f"/start×{u.get('starts', 0)}"
        )
    if total > limit:
        lines.append(f"\n<i>Показаны последние {limit} из {total}.</i>")
    return "\n".join(lines)


def format_users_report(*, limit: int = 30) -> str:
    try:
        return _format_users_report(limit=limit)
    except Exception:
        _log("users_log: не удалось собрать отчёт")
        return "👥 <b>Пользователи бота:</b> отчёт сейчас недоступен"


def is_bot_admin(chat_id: int) -> bool:
    """Админы из config_keys.BOT_ADMIN_IDS (list/tuple/int)."""
    try:
        from config_keys import BOT_ADMIN_IDS
    except Exception:
        return False
    if BOT_ADMIN_IDS is None:
        return False
    if isinstance(BOT_ADMIN_IDS, (int, str)):
        return str(chat_id) == str(BOT_ADMIN_IDS)
    try:
        return int(chat_id) in {int(x) for x in BOT_ADMIN_IDS}
    except Exception:
        return str(chat_id) in {str(x) for x in BOT_ADMIN_IDS}
