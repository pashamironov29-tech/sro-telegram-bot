#!/usr/bin/env python3
"""Обновить CHECKO_API_KEY на VPS. Ключ НЕ хранить в этом файле.

  python3 set_checko_key_vps.py 'ВАШ_КЛЮЧ'
  # или: CHECKO_API_KEY=... python3 set_checko_key_vps.py
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

KEY = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("CHECKO_API_KEY", "")).strip()
if not KEY:
    print("Usage: set_checko_key_vps.py '<CHECKO_API_KEY>'", file=sys.stderr)
    sys.exit(1)

p = Path("/opt/sro-bot/config_keys.py")
t = p.read_text(encoding="utf-8")
line = f'CHECKO_API_KEY = "{KEY}"'
if "CHECKO_API_KEY" in t:
    t = re.sub(r"CHECKO_API_KEY\s*=.*", line, t)
else:
    t = t.rstrip() + "\n" + line + "\n"
p.write_text(t, encoding="utf-8")
print("CHECKO_API_KEY set")
