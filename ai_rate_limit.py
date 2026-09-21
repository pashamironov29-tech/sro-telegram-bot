"""Лимит платных запросов ИИ (OpenRouter / GigaChat / Groq) на чат в час.

FAQ, поиск по ИНН и ответы из базы бота не считаются.
Админы (BOT_ADMIN_IDS) — без лимита.
"""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

_chat_id_var: ContextVar[int | None] = ContextVar("paid_ai_chat_id", default=None)
_lock = threading.Lock()
_hits: dict[int, deque[float]] = defaultdict(deque)
_loaded = False

_STATE_PATH = Path(__file__).resolve().parent / "ai_rate_limit_state.json"

_DEFAULT_USER = 20
_DEFAULT_CONTROLLER = 40
_DEFAULT_WINDOW = 3600


class PaidAiRateLimited(Exception):
    """Платный ИИ отклонили из‑за лимита чата."""

    def __init__(self, text: str):
        self.text = text
        super().__init__(text)


def bind_chat_id(chat_id) -> object:
    """Привязать chat_id к текущему потоку/задаче. Вернуть token для reset."""
    if chat_id is None:
        return _chat_id_var.set(None)
    try:
        return _chat_id_var.set(int(chat_id))
    except (TypeError, ValueError):
        return _chat_id_var.set(None)


def reset_chat_id(token) -> None:
    try:
        _chat_id_var.reset(token)
    except Exception:
        pass


@contextmanager
def ai_chat_scope(chat_id):
    token = bind_chat_id(chat_id)
    try:
        yield
    finally:
        reset_chat_id(token)


def current_chat_id(chat_id=None) -> int | None:
    if chat_id is not None:
        try:
            return int(chat_id)
        except (TypeError, ValueError):
            return None
    return _chat_id_var.get()


def _settings() -> tuple[bool, int, int, int]:
    enabled = True
    user_n = _DEFAULT_USER
    ctrl_n = _DEFAULT_CONTROLLER
    window = _DEFAULT_WINDOW
    try:
        import config_keys as ck

        enabled = bool(getattr(ck, "AI_RATE_LIMIT_ENABLED", True))
        user_n = int(getattr(ck, "AI_USER_LIMIT_PER_HOUR", _DEFAULT_USER) or _DEFAULT_USER)
        ctrl_n = int(
            getattr(ck, "AI_CONTROLLER_LIMIT_PER_HOUR", _DEFAULT_CONTROLLER)
            or _DEFAULT_CONTROLLER
        )
        window = int(getattr(ck, "AI_RATE_WINDOW_SEC", _DEFAULT_WINDOW) or _DEFAULT_WINDOW)
    except Exception:
        pass
    user_n = max(1, user_n)
    ctrl_n = max(1, ctrl_n)
    window = max(60, window)
    return enabled, user_n, ctrl_n, window


def _quota_for(chat_id: int) -> int | None:
    """None = без лимита (админ)."""
    try:
        from users_log import is_bot_admin

        if is_bot_admin(chat_id):
            return None
    except Exception:
        pass
    _enabled, user_n, ctrl_n, _window = _settings()
    try:
        from controller_access import is_controller

        if is_controller(chat_id):
            return ctrl_n
    except Exception:
        pass
    return user_n


def _load_state() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    if not _STATE_PATH.is_file():
        return
    try:
        raw = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return
    now = time.time()
    _, _, _, window = _settings()
    cutoff = now - window
    if not isinstance(raw, dict):
        return
    for key, stamps in raw.items():
        try:
            cid = int(key)
        except (TypeError, ValueError):
            continue
        if not isinstance(stamps, list):
            continue
        dq: deque[float] = deque()
        for ts in stamps:
            try:
                val = float(ts)
            except (TypeError, ValueError):
                continue
            if val >= cutoff:
                dq.append(val)
        if dq:
            _hits[cid] = dq


def _save_state() -> None:
    payload = {str(cid): list(stamps) for cid, stamps in _hits.items() if stamps}
    try:
        tmp = _STATE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(_STATE_PATH)
    except Exception:
        pass


def _prune(dq: deque[float], cutoff: float) -> None:
    while dq and dq[0] < cutoff:
        dq.popleft()


def _deny_text(limit: int, retry_in_sec: float) -> str:
    mins = max(1, int((retry_in_sec + 59) // 60))
    return (
        "⏳ Слишком много вопросов к ИИ за последний час.\n\n"
        f"Лимит: <b>{limit}</b> платных запросов в час на этот чат.\n"
        f"Следующий запрос можно через ~<b>{mins}</b> мин.\n\n"
        "Поиск по ИНН, меню и готовые ответы из базы — без ограничений."
    )


def consume_paid_ai(chat_id=None) -> str | None:
    """Списать 1 платный запрос. Вернуть текст отказа или None, если можно идти в API."""
    enabled, _user_n, _ctrl_n, window = _settings()
    if not enabled:
        return None
    cid = current_chat_id(chat_id)
    if cid is None:
        return None
    quota = _quota_for(cid)
    if quota is None:
        return None

    now = time.time()
    cutoff = now - window
    with _lock:
        _load_state()
        dq = _hits[cid]
        _prune(dq, cutoff)
        if len(dq) >= quota:
            retry = window - (now - dq[0]) if dq else window
            return _deny_text(quota, retry)
        dq.append(now)
        _save_state()
    return None


def raise_if_paid_ai_limited(chat_id=None) -> None:
    msg = consume_paid_ai(chat_id)
    if msg:
        raise PaidAiRateLimited(msg)
