"""Доступ к упрощённому меню для контролёров СРО (без онбординга вступающих)."""

from __future__ import annotations

import os

# Активный «кабинет контролёра» (после /controller).
# /start и смена организации выключают — тогда UX как у члена СРО (без Checko).
_controller_work_mode: set[int] = set()


def _bot_platform() -> str:
    p = (os.getenv("BOT_PLATFORM") or "tg").strip().lower()
    return "max" if p == "max" else "tg"


def _normalize_ids(v) -> list[int]:
    """Один int/str → один id; строку не раскладывать по символам."""
    if v is None:
        return []
    if isinstance(v, int):
        return [v]
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return []
        parts = [p.strip() for p in s.replace(";", ",").split(",") if p.strip()]
        v = parts if parts else [s]
    out: list[int] = []
    for x in v:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


def controller_chat_ids() -> list[int]:
    """Список контролёров текущей платформы (BOT_PLATFORM=tg|max).

    TG: CONTROLLER_CHAT_IDS, если ключа нет — BOT_ADMIN_IDS.
    MAX: только MAX_CONTROLLER_IDS (без слияния с TG и без фолбэка на админов).
    Пустой список [] не подменяет админами.
    """
    try:
        import config_keys as ck

        if _bot_platform() == "max":
            raw = getattr(ck, "MAX_CONTROLLER_IDS", None)
            if raw is None:
                return []
            return list(dict.fromkeys(_normalize_ids(raw)))

        if not hasattr(ck, "CONTROLLER_CHAT_IDS"):
            raw = getattr(ck, "BOT_ADMIN_IDS", [])
        else:
            raw = getattr(ck, "CONTROLLER_CHAT_IDS")
            if raw is None:
                raw = getattr(ck, "BOT_ADMIN_IDS", [])
    except Exception:
        raw = []
    return list(dict.fromkeys(_normalize_ids(raw)))


def is_controller(chat_id: int) -> bool:
    try:
        cid = int(chat_id)
    except (TypeError, ValueError):
        return False
    return cid in controller_chat_ids()


def enter_controller_work_mode(chat_id: int) -> None:
    try:
        _controller_work_mode.add(int(chat_id))
    except (TypeError, ValueError):
        pass


def exit_controller_work_mode(chat_id: int) -> None:
    try:
        _controller_work_mode.discard(int(chat_id))
    except (TypeError, ValueError):
        pass


def is_controller_work_mode(chat_id: int) -> bool:
    """True только если ID контролёра и открыт кабинет (/controller)."""
    try:
        cid = int(chat_id)
    except (TypeError, ValueError):
        return False
    return cid in controller_chat_ids() and cid in _controller_work_mode


def can_use_checko(chat_id: int) -> bool:
    """Checko и развилка «полная информация» — только в кабинете контролёра."""
    return is_controller_work_mode(chat_id)
