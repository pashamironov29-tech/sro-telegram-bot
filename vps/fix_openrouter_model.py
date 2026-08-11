#!/usr/bin/env python3
"""Repair broken OPENROUTER_MODEL line in VPS config_keys.py (no secrets printed)."""
from pathlib import Path

p = Path("/opt/sro-bot/config_keys.py")
lines = p.read_text(encoding="utf-8").splitlines(True)
out = []
seen_model = False
for line in lines:
    if line.lstrip().startswith("OPENROUTER_MODEL"):
        if not seen_model:
            out.append('OPENROUTER_MODEL = "openai/gpt-4.1-mini"\n')
            seen_model = True
        continue
    out.append(line)
if not seen_model:
    out.append('\nOPENROUTER_MODEL = "openai/gpt-4.1-mini"\n')
src = "".join(out)
compile(src, str(p), "exec")
p.write_text(src, encoding="utf-8")
print("config_syntax_ok")
for name in ("OPENROUTER_API_KEY", "OPENROUTER_MODEL", "GROQ_API_KEY", "BOT_ADMIN_IDS"):
    present = any(l.lstrip().startswith(name + " ") or l.lstrip().startswith(name + "=") for l in out)
    print(name, "yes" if present else "no")
