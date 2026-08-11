#!/usr/bin/env python3
import re
from pathlib import Path

import requests

p = Path(r"C:\Users\User\OneDrive\Рабочие\GOLD\config_keys.py")
text = p.read_text(encoding="utf-8")
m = re.search(r"OPENROUTER_API_KEY\s*=\s*['\"]([^'\"]+)['\"]", text)
if not m:
    print("NO_KEY_IN_FILE")
    raise SystemExit(1)
key = m.group(1).strip()
print("key_prefix", key[:12], "len", len(key))

headers = {
    "Authorization": f"Bearer {key}",
    "Content-Type": "application/json",
    "HTTP-Referer": "https://www.srogen.ru",
    "X-Title": "JanTest",
}

r = requests.get("https://openrouter.ai/api/v1/key", headers=headers, timeout=30)
print("key_status", r.status_code)
print("key_body", r.text[:500])

r3 = requests.post(
    "https://openrouter.ai/api/v1/chat/completions",
    headers=headers,
    json={
        "model": "deepseek/deepseek-chat",
        "messages": [{"role": "user", "content": "say hi in one word"}],
        "max_tokens": 20,
    },
    timeout=60,
)
print("chat_status", r3.status_code)
print("chat_body", r3.text[:700])
