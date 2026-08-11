#!/usr/bin/env python3
"""Обновить CONTACTS_PASSWORD на VPS. Запуск: python3 set_contacts_password_vps.py 'новый_пароль'"""
from __future__ import annotations

import sys
from pathlib import Path

if len(sys.argv) != 2 or len(sys.argv[1]) < 12:
    print("Usage: python3 set_contacts_password_vps.py 'password_min_12_chars'")
    raise SystemExit(1)

new = sys.argv[1]
p = Path("/opt/sro-bot/config_keys.py")
text = p.read_text(encoding="utf-8")
lines = []
for line in text.splitlines():
    if line.strip().startswith("CONTACTS_PASSWORD"):
        lines.append(f'CONTACTS_PASSWORD = "{new}"')
    else:
        lines.append(line)
p.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("CONTACTS_PASSWORD updated on VPS")
