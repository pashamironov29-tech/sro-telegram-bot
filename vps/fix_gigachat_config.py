#!/usr/bin/env python3
# Fix broken GIGACHAT_* append in config_keys.py (no secrets printed).
from pathlib import Path

p = Path("/opt/sro-bot/config_keys.py")
text = p.read_text(encoding="utf-8")
out = []
for line in text.splitlines(True):
    s = line.lstrip()
    if s.startswith("GIGACHAT_") or "Запасной ИИ в РФ" in line:
        continue
    out.append(line)
body = "".join(out).rstrip() + "\n\n"
body += (
    "# Запасной ИИ в РФ (Сбер GigaChat)\n"
    'GIGACHAT_CREDENTIALS = ""\n'
    'GIGACHAT_SCOPE = "GIGACHAT_API_PERS"\n'
    'GIGACHAT_MODEL = "GigaChat"\n'
    "GIGACHAT_VERIFY_SSL = True\n"
)
compile(body, str(p), "exec")
p.write_text(body, encoding="utf-8")
print("fixed_ok")
