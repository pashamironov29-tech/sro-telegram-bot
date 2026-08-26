# -*- coding: utf-8 -*-
"""Проверка: контролёрский ИИ (голос/доки) подключён к bot_FINAL_GOLD.py.

Запуск:
  py vps/check_controller_ai_wired.py
  py vps/check_controller_ai_wired.py path/to/bot_FINAL_GOLD.py

Код выхода 0 = ок, 1 = связка отвалилась (нельзя заливать на VPS).
"""
from __future__ import annotations
import os
from pathlib import Path as _Path
_orig_resolve = _Path.resolve

def _safe_resolve(self, strict=False):
    try:
        return _orig_resolve(self, strict=strict)
    except OSError:
        return _Path(os.path.abspath(str(self)))

_Path.resolve = _safe_resolve  # type: ignore[method-assign]


import sys
from pathlib import Path

REQUIRED_SNIPPETS = (
    "from controller_ai import",
    "CONTROLLER_AI_BUTTON",
    "def get_controller_ai_keyboard",
    "def open_controller_ai",
    "def handle_controller_ai_voice",
    "def handle_controller_ai_document",
    "def handle_controller_ai_photo",
    "def handle_voice",
    "def handle_document",
    "def handle_photo",
    "tg_download_file",
    'content_types=["voice"]',
    "KeyboardButton(CONTROLLER_AI_BUTTON)",
    "user_text == CONTROLLER_AI_BUTTON",
    "is_controller_ai_mode",
)


def check_bot_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    missing = [s for s in REQUIRED_SNIPPETS if s not in text]
    return missing


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parent.parent
    bot = Path(argv[1]) if len(argv) > 1 else root / "bot_FINAL_GOLD.py"
    if not bot.is_file():
        print(f"FAIL: нет файла {bot}", flush=True)
        return 1
    missing = check_bot_file(bot)
    if missing:
        print("FAIL: в bot_FINAL_GOLD.py отвалилась связка 🎙 ИИ-помощника контролёра.", flush=True)
        print("Нет фрагментов:", flush=True)
        for s in missing:
            print(f"  - {s}", flush=True)
        print(
            "Не заливай этот файл на VPS. Восстанови из bak / Mail GOLD / "
            "vps/restore_controller_ai_wiring.py",
            flush=True,
        )
        return 1
    print(f"OK: controller AI wired — {bot}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
