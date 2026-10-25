"""Лог «ответ не помог» → feedback_questions.jsonl."""

from __future__ import annotations

import json
import time
from pathlib import Path

import session_persist

ROOT = Path(__file__).resolve().parent
FEEDBACK_FILE = ROOT / "feedback_questions.jsonl"

# chat_id -> последний ответ (для кнопки / фразы)
_last_ai: dict[int, dict] = {}
# chat_id -> момент, когда спросили «какой ответ ждали»
_await_expected: dict[int, float] = {}
AWAIT_TTL_SEC = 10 * 60
# Кнопка «ответ не помог» на старом сообщении. Дольше, чем ожидание фразы.
LAST_AI_TTL_SEC = 24 * 60 * 60

FB_CALLBACK = "fb:bad"
FB_PHRASES = (
    "ответ не помог",
    "не помог",
    "не то",
    "не тот ответ",
    "ответ не тот",
)


def _save_persisted() -> None:
    session_persist.save_section(
        "feedback",
        {
            "await": {str(cid): ts for cid, ts in _await_expected.items()},
            "last": {str(cid): row for cid, row in _last_ai.items()},
        },
    )


def _load_persisted() -> None:
    raw = session_persist.load_section("feedback") or {}
    _await_expected.clear()
    _last_ai.clear()
    if not isinstance(raw, dict):
        return
    await_raw = raw.get("await")
    if isinstance(await_raw, dict):
        for key, value in await_raw.items():
            try:
                _await_expected[int(key)] = float(value)
            except (TypeError, ValueError):
                continue
    last_raw = raw.get("last")
    if isinstance(last_raw, dict):
        for key, value in last_raw.items():
            if not isinstance(value, dict):
                continue
            try:
                _last_ai[int(key)] = value
            except (TypeError, ValueError):
                continue


def remember_ai_reply(
    chat_id: int,
    *,
    question: str,
    answer_text: str,
    route: str | None,
    sro_id: str | None,
) -> None:
    preview = (answer_text or "").replace("\n", " ").strip()
    if len(preview) > 300:
        preview = preview[:297] + "..."
    _last_ai[chat_id] = {
        "question": (question or "").strip(),
        "answer_preview": preview,
        "route": route or "unknown",
        "sro_id": sro_id,
        "ts": time.time(),
    }
    _save_persisted()


def _fresh_last_ai(chat_id: int) -> dict | None:
    last = _last_ai.get(chat_id)
    if not last:
        return None
    try:
        age = time.time() - float(last.get("ts") or 0)
    except (TypeError, ValueError):
        age = LAST_AI_TTL_SEC + 1
    if age > LAST_AI_TTL_SEC:
        _last_ai.pop(chat_id, None)
        _await_expected.pop(chat_id, None)
        _save_persisted()
        return None
    return last


def has_last_ai(chat_id: int) -> bool:
    return _fresh_last_ai(chat_id) is not None


def is_awaiting_expected(chat_id: int) -> bool:
    started = _await_expected.get(chat_id)
    if started is None:
        return False
    if time.time() - started > AWAIT_TTL_SEC:
        _await_expected.pop(chat_id, None)
        _save_persisted()
        return False
    return True


def begin_await_expected(chat_id: int) -> bool:
    """True, если есть что логировать (был ответ)."""
    if _fresh_last_ai(chat_id) is None:
        return False
    _await_expected[chat_id] = time.time()
    _save_persisted()
    return True


def cancel_await_expected(chat_id: int) -> None:
    _await_expected.pop(chat_id, None)
    _save_persisted()


def is_feedback_phrase(text: str) -> bool:
    t = (text or "").strip().lower().replace("ё", "е")
    return t in FB_PHRASES


def append_feedback(chat_id: int, expected: str | None) -> bool:
    """Пишет строку в jsonl. False, если нечего писать."""
    last = _fresh_last_ai(chat_id)
    if not last:
        _await_expected.pop(chat_id, None)
        _save_persisted()
        return False
    row = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "chat_id": chat_id,
        "question": last.get("question"),
        "answer_preview": last.get("answer_preview"),
        "route": last.get("route"),
        "sro_id": last.get("sro_id"),
        "expected": (expected.strip() if expected and expected.strip() else None),
    }
    with FEEDBACK_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    _await_expected.pop(chat_id, None)
    _save_persisted()
    return True


_load_persisted()
