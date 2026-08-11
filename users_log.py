"""Журнал пользователей бота → bot_users.json.

Пишет chat_id, имя, username, первый и последний заход.
Список смотри: файл bot_users.json или команда /users (только админ).
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
USERS_FILE = ROOT / "bot_users.json"

_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _load() -> dict:
    if not USERS_FILE.is_file():
        return {"users": {}}
    try:
        data = json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"users": {}}
    if not isinstance(data, dict):
        return {"users": {}}
    users = data.get("users")
    if not isinstance(users, dict):
        data["users"] = {}
    return data


def _save(data: dict) -> None:
    USERS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


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


def touch_user(message, *, event: str = "message") -> bool:
    """
    Зафиксировать визит. True — новый пользователь (первый раз).
    """
    info = _user_from_message(message)
    chat_id = info.get("chat_id")
    if chat_id is None:
        return False
    key = str(chat_id)
    now = _now_iso()
    is_new = False
    with _lock:
        data = _load()
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


def users_count() -> int:
    with _lock:
        return len(_load().get("users") or {})


def list_users(*, limit: int = 50) -> list[dict]:
    with _lock:
        users = list((_load().get("users") or {}).values())
    users.sort(key=lambda u: u.get("last_seen") or "", reverse=True)
    return users[:limit]


def format_users_report(*, limit: int = 30) -> str:
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
        mention = f"@{uname}" if uname else "без @username"
        lines.append(
            f"{i}. <b>{u.get('full_name') or '—'}</b> ({mention})\n"
            f"   id <code>{u.get('chat_id')}</code> · "
            f"первый {u.get('first_seen', '—')} · "
            f"был {u.get('last_seen', '—')} · "
            f"/start×{u.get('starts', 0)}"
        )
    if total > limit:
        lines.append(f"\n<i>Показаны последние {limit} из {total}.</i>")
    return "\n".join(lines)


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
