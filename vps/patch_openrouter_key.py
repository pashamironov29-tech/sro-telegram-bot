#!/usr/bin/env python3
"""One-shot: read /tmp/or_key_once.txt -> config_keys.OPENROUTER_API_KEY, then delete key file."""
from pathlib import Path
import re
import sys

KEY_FILE = Path("/tmp/or_key_once.txt")
CFG = Path("/opt/sro-bot/config_keys.py")

if not KEY_FILE.is_file():
    print("missing_key_file", file=sys.stderr)
    sys.exit(1)

key = KEY_FILE.read_text(encoding="utf-8").strip()
KEY_FILE.unlink(missing_ok=True)
if not key.startswith("sk-or-"):
    print("bad_key", file=sys.stderr)
    sys.exit(1)

t = CFG.read_text(encoding="utf-8")
lines = []
done = False
for line in t.splitlines(True):
    if (not done) and line.lstrip().startswith("OPENROUTER_API_KEY"):
        lines.append(f'OPENROUTER_API_KEY = "{key}"\n')
        done = True
    else:
        lines.append(line)
if not done:
    lines.append(f'\nOPENROUTER_API_KEY = "{key}"\n')
CFG.write_text("".join(lines), encoding="utf-8")
print("config_updated")
