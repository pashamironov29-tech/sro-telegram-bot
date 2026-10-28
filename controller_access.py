"""Список chat_id для рассылки /notify_update.

Раньше здесь же жил кабинет контролёра (/controller, доступ к Checko).
Он убран: все кнопки доступны всем. Остался только список получателей
админской рассылки (ключ CONTROLLER_CHAT_IDS в config_keys, как раньше).
"""

from __future__ import annotations

import os


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
    """Получатели рассылки текущей платформы (BOT_PLATFORM=tg|max).

    TG: CONTROLLER_CHAT_IDS, если ключа нет — BOT_ADMIN_IDS.
    MAX: только MAX_CONTROLLER_IDS. Пустой список [] админами не подменяется.
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
