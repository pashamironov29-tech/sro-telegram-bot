#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Patch GIGACHAT_CREDENTIALS on VPS from /root/gc_cred_once.txt then delete that file."""
from pathlib import Path

cred_path = Path("/root/gc_cred_once.txt")
cfg_path = Path("/opt/sro-bot/config_keys.py")
cred = cred_path.read_text(encoding="utf-8").strip()
cred_path.unlink(missing_ok=True)
if not cred:
    raise SystemExit("empty_cred")

lines = cfg_path.read_text(encoding="utf-8").splitlines(True)
out = []
done = False
for line in lines:
    if line.lstrip().startswith("GIGACHAT_CREDENTIALS"):
        out.append(f'GIGACHAT_CREDENTIALS = "{cred}"\n')
        done = True
    else:
        out.append(line)
if not done:
    out.append(f'\nGIGACHAT_CREDENTIALS = "{cred}"\n')
body = "".join(out)
compile(body, str(cfg_path), "exec")
cfg_path.write_text(body, encoding="utf-8")
print("patched_ok", "len", len(cred))
