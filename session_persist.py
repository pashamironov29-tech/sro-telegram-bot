"""Режимы, которые должны пережить перезапуск процесса.

Один файл на площадку: Telegram и MAX не делят id.
Память процесса — источник правды, пока процесс жив.
Файл читается при старте и пишется, когда снимок раздела изменился.
"""

from __future__ import annotations

import copy
import json
import os
import threading
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def platform() -> str:
    value = (os.getenv("BOT_PLATFORM") or "tg").strip().lower()
    return "max" if value == "max" else "tg"


STATE_FILE = ROOT / f"session_state_{platform()}.json"

_lock = threading.Lock()
_warned = False


def _log(text: str) -> None:
    """Без id, имён и содержимого файла: там могут быть ответы опроса."""
    print(text, flush=True)


def _log_once(text: str) -> None:
    global _warned
    if _warned:
        return
    _warned = True
    _log(text)


def _read() -> dict:
    path = STATE_FILE
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _log_once("session_persist: файл состояния не прочитался, держу пустой снимок")
        return {}
    if not isinstance(raw, dict):
        return {}
    return raw


def _write(data: dict) -> None:
    path = STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = path.with_name(
        f"{path.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp"
    )
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.is_file():
            try:
                tmp.unlink()
            except OSError:
                pass


def load_section(name: str):
    """Копия раздела или None, если его ещё нет."""
    with _lock:
        value = _read().get(name)
    if value is None:
        return None
    return copy.deepcopy(value)


def save_section(name: str, value) -> None:
    """Записать раздел. Одинаковый снимок на диск не гоняем.

    Ошибка диска наружу не летит: ответ пользователю важнее файла.
    """
    try:
        with _lock:
            data = _read()
            new_value = copy.deepcopy(value)
            if data.get(name) == new_value:
                return
            data[name] = new_value
            _write(data)
    except Exception:
        _log_once("session_persist: не записал состояние")
