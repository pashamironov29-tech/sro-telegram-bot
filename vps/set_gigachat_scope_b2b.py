#!/usr/bin/env python3
from pathlib import Path

p = Path("/opt/sro-bot/config_keys.py")
t = p.read_text(encoding="utf-8")
for old, new in (
    ('GIGACHAT_SCOPE = "GIGACHAT_API_PERS"', 'GIGACHAT_SCOPE = "GIGACHAT_API_B2B"'),
    ("GIGACHAT_SCOPE = 'GIGACHAT_API_PERS'", "GIGACHAT_SCOPE = 'GIGACHAT_API_B2B'"),
):
    if old in t:
        t = t.replace(old, new)
        break
else:
    raise SystemExit("scope_line_not_found")
p.write_text(t, encoding="utf-8")
print("set_b2b_ok")
