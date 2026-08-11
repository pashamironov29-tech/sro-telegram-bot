"""Лог «ответ не помог» по ответам ИИ → feedback_questions.jsonl."""

from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FEEDBACK_FILE = ROOT / "feedback_questions.jsonl"

# chat_id -> последний ответ ИИ (для кнопки / фразы)
_last_ai: dict[int, dict] = {}
# chat_id -> ждём текст «что ожидали»
_await_expected: set[int] = set()

FB_CALLBACK = "fb:bad"
FB_PHRASES = (
    "ответ не помог",
    "не помог",
    "не то",
    "не тот ответ",
    "ответ не тот",
)


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


def has_last_ai(chat_id: int) -> bool:
    return chat_id in _last_ai


def is_awaiting_expected(chat_id: int) -> bool:
    return chat_id in _await_expected


def begin_await_expected(chat_id: int) -> bool:
    """True, если есть что логировать (был ответ ИИ)."""
    if chat_id not in _last_ai:
        return False
    _await_expected.add(chat_id)
    return True


def cancel_await_expected(chat_id: int) -> None:
    _await_expected.discard(chat_id)


def is_feedback_phrase(text: str) -> bool:
    t = (text or "").strip().lower().replace("ё", "е")
    return t in FB_PHRASES


def append_feedback(chat_id: int, expected: str | None) -> bool:
    """Пишет строку в jsonl. False, если нечего писать."""
    last = _last_ai.get(chat_id)
    if not last:
        _await_expected.discard(chat_id)
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
    _await_expected.discard(chat_id)
    return True
