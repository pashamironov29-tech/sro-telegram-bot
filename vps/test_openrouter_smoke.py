#!/usr/bin/env python3
"""Smoke-test OpenRouter from VPS (no secrets printed)."""
import re
import requests

from config_keys import OPENROUTER_API_KEY

try:
    from config_keys import OPENROUTER_MODEL
except ImportError:
    OPENROUTER_MODEL = "openai/gpt-4.1-mini"

print("key_set", bool((OPENROUTER_API_KEY or "").strip()))
model = (OPENROUTER_MODEL or "openai/gpt-4.1-mini").strip() or "openai/gpt-4.1-mini"
print("model", model)
r = requests.post(
    "https://openrouter.ai/api/v1/chat/completions",
    headers={
        "Authorization": "Bearer " + (OPENROUTER_API_KEY or "").strip(),
        "Content-Type": "application/json",
        "HTTP-Referer": "https://www.srogen.ru",
        "X-Title": "SRO GOLD DocQA",
    },
    json={
        "model": model,
        "messages": [{"role": "user", "content": "Reply with one word: ok"}],
        "max_tokens": 10,
    },
    timeout=45,
)
body = re.sub(r"sk-or-v1-[A-Za-z0-9]+", "[REDACTED]", (r.text or "")[:400])
print("status", r.status_code)
print(body)
