# -*- coding: utf-8 -*-
"""GigaChat API (Сбер) — запасной ИИ в РФ для СРО-бота.

Ключ: GIGACHAT_CREDENTIALS в config_keys.py (Authorization Key из
https://developers.sber.ru/ — Studio → проект → ключ авторизации).
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any

import requests

try:
    from config_keys import GIGACHAT_CREDENTIALS as _CRED
except ImportError:
    _CRED = ""

try:
    from config_keys import GIGACHAT_SCOPE as _SCOPE
except ImportError:
    _SCOPE = "GIGACHAT_API_PERS"

try:
    from config_keys import GIGACHAT_MODEL as _MODEL
except ImportError:
    _MODEL = "GigaChat"

try:
    from config_keys import GIGACHAT_VERIFY_SSL as _VERIFY
except ImportError:
    _VERIFY = True

# OAuth + chat (актуальные URL Сбера)
OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
CHAT_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"

_lock = threading.Lock()
_token: str = ""
_token_exp: float = 0.0


def credentials_configured() -> bool:
    return bool((_CRED or "").strip())


def _verify_ssl() -> bool:
    return bool(_VERIFY) if _VERIFY is not None else True


def _scope() -> str:
    return (_SCOPE or "GIGACHAT_API_PERS").strip() or "GIGACHAT_API_PERS"


def _model() -> str:
    return (_MODEL or "GigaChat").strip() or "GigaChat"


def _post(url: str, **kwargs: Any) -> requests.Response:
    """POST с запасным verify=False при SSL-ошибке (часто на VPS без цепочки Сбера)."""
    verify = _verify_ssl()
    try:
        return requests.post(url, verify=verify, **kwargs)
    except requests.exceptions.SSLError:
        if verify is False:
            raise
        return requests.post(url, verify=False, **kwargs)


def _fetch_token() -> str:
    cred = (_CRED or "").strip()
    if not cred:
        raise RuntimeError("gigachat_no_credentials")
    r = _post(
        OAUTH_URL,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "RqUID": str(uuid.uuid4()),
            "Authorization": f"Basic {cred}",
        },
        data={"scope": _scope()},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    token = (data.get("access_token") or "").strip()
    if not token:
        raise RuntimeError("gigachat_empty_token")
    # Обычно ~30 мин; берём с запасом
    expires = int(data.get("expires_at") or 0)
    with _lock:
        global _token, _token_exp
        _token = token
        if expires > 1_000_000_000_000:  # мс
            _token_exp = expires / 1000.0 - 60
        elif expires > 1_000_000_000:  # unix sec
            _token_exp = float(expires) - 60
        else:
            _token_exp = time.time() + 25 * 60
    return token


def get_access_token() -> str:
    with _lock:
        if _token and time.time() < _token_exp:
            return _token
    return _fetch_token()


def chat_completion(
    messages: list[dict],
    *,
    max_tokens: int = 64,
    temperature: float = 0.0,
) -> str:
    """OpenAI-совместимый chat/completions через GigaChat."""
    token = get_access_token()
    r = _post(
        CHAT_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json={
            "model": _model(),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=60,
    )
    if r.status_code == 401:
        # токен протух — один повтор
        with _lock:
            global _token_exp
            _token_exp = 0
        token = get_access_token()
        r = _post(
            CHAT_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={
                "model": _model(),
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=60,
        )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()
