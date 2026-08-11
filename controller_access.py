"""Доступ к упрощённому меню для контролёров СРО (без онбординга вступающих)."""

from __future__ import annotations

# Активный «кабинет контролёра» (после /controller).
# /start и смена организации выключают — тогда UX как у члена СРО (без Checko).
_controller_work_mode: set[int] = set()


def controller_chat_ids() -> list[int]:
    try:
        import config_keys

        raw = getattr(config_keys, "CONTROLLER_CHAT_IDS", None)
        if raw is None:
            raw = getattr(config_keys, "BOT_ADMIN_IDS", [])
    except Exception:
        raw = []
    out: list[int] = []
    for x in raw or []:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


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
