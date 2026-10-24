"""Журнал пользователей бота → bot_users.sqlite.

Одна строка на пару (площадка, chat_id): Telegram и MAX больше не
смешиваются в одном ключе. Запись — один UPSERT, файл целиком не
переписывается. WAL и synchronous=FULL: сбой питания не оставляет
пустую базу.

Старый bot_users.json один раз переносится в базу и остаётся на диске
как копия. Бот его не удаляет и дальше не переписывает.
Битый JSON уходит в bot_users.json.bad-* и не затирается пустым журналом.
Ошибка чтения (нет прав, диск) файл не перекладывает.
Сбой журнала не обрывает ответ пользователю.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from html import escape as html_escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent
USERS_FILE = ROOT / "bot_users.json"

_state_lock = threading.RLock()
_ready_path: str | None = None
_corrupt_warned = False
# Постоянная ошибка чтения не должна печататься на каждое сообщение.
READ_ERROR_LOG_INTERVAL_SEC = 10 * 60
_read_error_logged_at: float | None = None

try:
    from time import monotonic as _monotonic
except ImportError:  # pragma: no cover
    import time

    _monotonic = time.monotonic

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    platform TEXT NOT NULL,
    chat_id INTEGER NOT NULL,
    username TEXT NOT NULL DEFAULT '',
    full_name TEXT NOT NULL DEFAULT '—',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    starts INTEGER NOT NULL DEFAULT 0,
    messages INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (platform, chat_id)
);
CREATE INDEX IF NOT EXISTS users_last_seen ON users (last_seen);
"""

_PLATFORM_LABEL = {
    "tg": "Telegram",
    "max": "MAX",
    "legacy": "прежний файл",
}


def db_path() -> Path:
    """Живой журнал рядом с путём старого JSON (тесты подменяют USERS_FILE)."""
    return USERS_FILE.with_name("bot_users.sqlite")


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


def _platform() -> str:
    value = (os.getenv("BOT_PLATFORM") or "tg").strip().lower()
    return "max" if value == "max" else "tg"


def _platform_label(value: str | None) -> str:
    return _PLATFORM_LABEL.get(str(value or ""), str(value or "—"))


def _connect() -> sqlite3.Connection:
    """WAL и synchronous=FULL. Смену journal_mode SQLite не ждёт по busy_timeout."""
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 8
    while True:
        conn = sqlite3.connect(str(path), timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout=8000")
            row = conn.execute("PRAGMA journal_mode=WAL").fetchone()
            if not row or str(row[0]).lower() != "wal":
                raise sqlite3.OperationalError("journal_mode")
            conn.execute("PRAGMA synchronous=FULL")
            conn.executescript(_SCHEMA)
            return conn
        except sqlite3.OperationalError:
            conn.close()
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.02)


def _meta(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT value FROM meta WHERE key='json_imported'"
    ).fetchone()
    if row is None:
        return None
    return str(row["value"])


def _mark_imported(conn: sqlite3.Connection, value: str) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        if _meta(conn):
            conn.execute("COMMIT")
            return
        conn.execute(
            "INSERT INTO meta(key, value) VALUES ('json_imported', ?)",
            (value,),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _quarantine_corrupt() -> bool:
    """Один раз переложить битый журнал в bot_users.json.bad-YYYYmmdd-HHMMSS.

    False — файл на месте, новый журнал поверх него писать нельзя.
    Содержимое не удаляется: это копия битого файла.
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


def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _rows_from_json(data: dict) -> list[tuple]:
    users = data.get("users")
    if not isinstance(users, dict):
        return []
    now = _now_iso()
    rows: list[tuple] = []
    for key, row in users.items():
        if not isinstance(row, dict):
            continue
        raw_id = row.get("chat_id", key)
        try:
            chat_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        platform = str(row.get("platform") or "legacy").strip().lower()
        if platform not in ("tg", "max", "legacy"):
            platform = "legacy"
        username = str(row.get("username") or "")
        full_name = str(row.get("full_name") or "—") or "—"
        first_seen = str(row.get("first_seen") or now)
        last_seen = str(row.get("last_seen") or first_seen)
        rows.append(
            (
                platform,
                chat_id,
                username,
                full_name,
                first_seen,
                last_seen,
                _as_int(row.get("starts")),
                _as_int(row.get("messages")),
            )
        )
    return rows


def _migrate(conn: sqlite3.Connection) -> bool:
    """True — в sqlite можно писать. False — JSON не прочитался, запись пропускаем.

    Успешный перенос не трогает bot_users.json: файл остаётся копией.
    """
    if _meta(conn):
        _note_read_ok()
        return True
    if not USERS_FILE.is_file():
        _mark_imported(conn, "absent")
        _note_read_ok()
        return True
    try:
        raw = USERS_FILE.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        if not _quarantine_corrupt():
            return False
        _mark_imported(conn, "corrupt")
        _note_read_ok()
        return True
    except OSError:
        _log_read_error()
        return False
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        if not _quarantine_corrupt():
            return False
        _mark_imported(conn, "corrupt")
        _note_read_ok()
        return True
    if not isinstance(data, dict):
        if not _quarantine_corrupt():
            return False
        _mark_imported(conn, "corrupt")
        _note_read_ok()
        return True
    rows = _rows_from_json(data)
    conn.execute("BEGIN IMMEDIATE")
    try:
        if _meta(conn):
            conn.execute("COMMIT")
            _note_read_ok()
            return True
        conn.executemany(
            """
            INSERT OR IGNORE INTO users (
                platform, chat_id, username, full_name,
                first_seen, last_seen, starts, messages
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.execute(
            "INSERT INTO meta(key, value) VALUES ('json_imported', 'ok')"
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    _note_read_ok()
    _log("users_log: журнал перенесён в sqlite, bot_users.json оставлен как копия")
    return True


def _prepare() -> bool:
    global _ready_path
    current = str(db_path())
    if _ready_path == current:
        return True
    conn = _connect()
    try:
        ok = _migrate(conn)
    finally:
        conn.close()
    if ok:
        _ready_path = current
    return ok


def _load() -> dict | None:
    """Все строки или None, если журнал сейчас нельзя читать.

    None — битый JSON не удалось убрать или чтение сорвалось.
    Пустым словарём это не подменяем, пока перенос не завершён:
    иначе визит записался бы мимо старой истории.
    """
    if not _prepare():
        return None
    conn = _connect()
    try:
        fetched = conn.execute(
            """
            SELECT platform, chat_id, username, full_name,
                   first_seen, last_seen, starts, messages
            FROM users
            """
        ).fetchall()
    finally:
        conn.close()
    users: dict[str, dict] = {}
    for row in fetched:
        item = {
            "platform": row["platform"],
            "chat_id": row["chat_id"],
            "username": row["username"] or "",
            "full_name": row["full_name"] or "—",
            "first_seen": row["first_seen"],
            "last_seen": row["last_seen"],
            "starts": int(row["starts"] or 0),
            "messages": int(row["messages"] or 0),
        }
        users[f"{item['platform']}:{item['chat_id']}"] = item
    return {"users": users}


def _save(info: dict, event: str = "message") -> bool:
    """Один UPSERT. True — этой пары (площадка, id) ещё не было."""
    platform = _platform()
    chat_id = int(info["chat_id"])
    now = _now_iso()
    starts = 1 if event == "start" else 0
    messages = 0 if event == "start" else 1
    username = info.get("username") or ""
    full_name = info.get("full_name") or "—"
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT username, full_name FROM users
            WHERE platform=? AND chat_id=?
            """,
            (platform, chat_id),
        ).fetchone()
        if row is None:
            conn.execute(
                """
                INSERT INTO users (
                    platform, chat_id, username, full_name,
                    first_seen, last_seen, starts, messages
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (platform, chat_id, username, full_name, now, now, starts, messages),
            )
            conn.execute("COMMIT")
            return True
        new_username = username or row["username"] or ""
        new_name = full_name or row["full_name"] or "—"
        conn.execute(
            """
            UPDATE users
            SET username=?, full_name=?, last_seen=?,
                starts=starts+?, messages=messages+?
            WHERE platform=? AND chat_id=?
            """,
            (new_username, new_name, now, starts, messages, platform, chat_id),
        )
        conn.execute("COMMIT")
        return False
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()


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
    try:
        info["chat_id"] = int(chat_id)
    except (TypeError, ValueError):
        return False
    with _state_lock:
        if not _prepare():
            return False
        return _save(info, event)


def touch_user(message, *, event: str = "message") -> bool:
    """
    Зафиксировать визит. True — новый пользователь на этой площадке.

    Ошибка диска или журнала наружу не летит: ответ бота важнее записи.
    """
    try:
        return _touch_user(message, event=event)
    except Exception:
        _log("users_log: визит не записан")
        return False


def users_count() -> int:
    try:
        with _state_lock:
            data = _load()
            if not data:
                return 0
            return len(data.get("users") or {})
    except Exception:
        _log("users_log: не удалось посчитать пользователей")
        return 0


def list_users(*, limit: int = 50) -> list[dict]:
    try:
        with _state_lock:
            data = _load()
            users = list((data.get("users") or {}).values()) if data else []
    except Exception:
        _log("users_log: не удалось прочитать журнал")
        return []
    users.sort(key=lambda u: u.get("last_seen") or "", reverse=True)
    return users[:limit]


def _platform_counts() -> dict[str, int]:
    try:
        with _state_lock:
            data = _load()
    except Exception:
        return {}
    counts: dict[str, int] = {}
    for row in ((data or {}).get("users") or {}).values():
        key = str(row.get("platform") or "legacy")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _format_users_report(*, limit: int) -> str:
    total = users_count()
    rows = list_users(limit=limit)
    lines = [
        f"👥 <b>Пользователи бота:</b> {total}",
        f"<i>Файл: <code>{db_path().name}</code></i>",
    ]
    bits = []
    counts = _platform_counts()
    for key, label in (("tg", "Telegram"), ("max", "MAX"), ("legacy", "прежний файл")):
        amount = counts.get(key) or 0
        if amount:
            bits.append(f"{label}: {amount}")
    if bits:
        lines.append(" · ".join(bits))
    lines.append("")
    if not rows:
        lines.append("Пока никто не заходил.")
        return "\n".join(lines)
    for i, u in enumerate(rows, 1):
        uname = u.get("username") or ""
        mention = f"@{_html(uname)}" if uname else "без @username"
        lines.append(
            f"{i}. <b>{_html(u.get('full_name') or '—')}</b> ({mention})\n"
            f"   id <code>{u.get('chat_id')}</code> · "
            f"{_html(_platform_label(u.get('platform')))} · "
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
