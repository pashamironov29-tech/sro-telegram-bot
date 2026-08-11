#!/usr/bin/env python3
# Smoke: GigaChat from /opt/sro-bot — no secrets printed.
import os
import sys

os.chdir("/opt/sro-bot")
sys.path.insert(0, "/opt/sro-bot")

from gigachat_client import credentials_configured, chat_completion

print("configured", credentials_configured())
try:
    ans = chat_completion(
        [{"role": "user", "content": "Ответь одним словом: ок"}],
        max_tokens=16,
        temperature=0.0,
    )
    print("ok", bool(ans), "chars", len(ans or ""))
except Exception as e:
    print("fail", type(e).__name__, str(e)[:200])
