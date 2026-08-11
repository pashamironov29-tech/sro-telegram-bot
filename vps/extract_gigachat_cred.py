#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract GIGACHAT_CREDENTIALS to temp file; never print the secret."""
from pathlib import Path
import re

root = Path(r"C:\Users\User\OneDrive\Рабочие\GOLD")
text = (root / "config_keys.py").read_text(encoding="utf-8")
m = re.search(r'GIGACHAT_CREDENTIALS\s*=\s*["\']([^"\']*)["\']', text)
cred = (m.group(1) if m else "").strip()
out = Path(r"C:\Users\User\AppData\Local\Temp\gc_cred_once.txt")
out.write_text(cred, encoding="utf-8")
print("local_set", bool(cred), "len", len(cred))
