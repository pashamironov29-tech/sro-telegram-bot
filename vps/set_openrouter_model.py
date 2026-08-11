#!/usr/bin/env python3
"""Set OPENROUTER_MODEL on VPS without printing secrets."""
from pathlib import Path

MODEL = "openai/gpt-4.1"
p = Path("/opt/sro-bot/config_keys.py")
lines = p.read_text(encoding="utf-8").splitlines(True)
out = []
seen = False
for line in lines:
    if line.lstrip().startswith("OPENROUTER_MODEL"):
        if not seen:
            out.append(f'OPENROUTER_MODEL = "{MODEL}"\n')
            seen = True
        continue
    out.append(line)
if not seen:
    out.append(f'\nOPENROUTER_MODEL = "{MODEL}"\n')
src = "".join(out)
compile(src, str(p), "exec")
p.write_text(src, encoding="utf-8")
print("model_set", MODEL)
