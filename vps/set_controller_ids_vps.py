#!/usr/bin/env python3
"""Добавить/обновить CONTROLLER_CHAT_IDS на VPS. Запуск: python3 set_controller_ids_vps.py 796315762 ..."""
from __future__ import annotations

import re
import sys
from pathlib import Path

CONFIG = Path("/opt/sro-bot/config_keys.py")


def main() -> int:
    ids = [int(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else [796315762]
    text = CONFIG.read_text(encoding="utf-8")
    line = f"CONTROLLER_CHAT_IDS = {ids}"
    if "CONTROLLER_CHAT_IDS" in text:
        text = re.sub(r"CONTROLLER_CHAT_IDS\s*=.*", line, text)
    else:
        text = text.rstrip() + "\n" + line + "\n"
    CONFIG.write_text(text, encoding="utf-8")
    print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
