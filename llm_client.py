"""Клиент LLM: DeepSeek напрямую или прежний OpenRouter.

DeepSeek: base_url из DEEPSEEK_BASE_URL, без HTTP(S)_PROXY и без OPENROUTER_BASE.
OpenRouter: прежний адрес (OPENROUTER_BASE, если задан — прокси в Нидерландах).
"""

from __future__ import annotations

import os
from pathlib import Path

import requests

_DEFAULT_DEEPSEEK_BASE = "https://api.deepseek.com"
_DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
_DEFAULT_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
_DEFAULT_OPENROUTER_MODEL = "openai/gpt-4.1-mini"

# deepseek-chat и deepseek-reasoner сняты 24.07.2026 (официальный changelog).
# deepseek-chat был non-thinking режимом. Актуальная замена — deepseek-flash.
_RETIRED_DEEPSEEK_MODELS = {
    "deepseek-chat": "deepseek-flash",
    "deepseek-reasoner": "deepseek-flash",
}


def _load_dotenv() -> None:
    """Подхватить .env рядом с ботом. Уже заданные переменные окружения не трогаем."""
    path = Path(__file__).resolve().parent / ".env"
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        os.environ[key] = val


def _setting(name: str, default: str = "") -> str:
    """Сначала окружение / .env, затем config_keys.py (как раньше лежали ключи)."""
    env_val = os.environ.get(name)
    if env_val is not None and str(env_val).strip():
        return str(env_val).strip()
    try:
        import config_keys

        cfg = getattr(config_keys, name, "")
    except Exception:
        cfg = ""
    if isinstance(cfg, str) and cfg.strip():
        return cfg.strip()
    return default


def resolve_deepseek_model(name: str) -> str:
    """Имя модели, которое реально уходит в API."""
    model = (name or "").strip() or _DEFAULT_DEEPSEEK_MODEL
    return _RETIRED_DEEPSEEK_MODELS.get(model, model)


class LlmClient:
    """OpenAI-совместимый chat/completions. proxies=None — прокси не используется."""

    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        api_key: str,
        model: str,
        proxies: dict | None,
        trust_env: bool,
    ) -> None:
        self.provider = provider
        self.base_url = (base_url or "").strip().rstrip("/")
        self.api_key = (api_key or "").strip()
        self.model = (model or "").strip()
        self.proxies = proxies
        self.trust_env = trust_env

    @property
    def chat_url(self) -> str:
        return self.base_url + "/chat/completions"

    def session(self) -> requests.Session:
        sess = requests.Session()
        sess.trust_env = self.trust_env
        return sess

    def request_model(self, requested: str | None = None) -> str:
        if self.provider == "deepseek":
            return resolve_deepseek_model(self.model)
        picked = (requested or self.model or _DEFAULT_OPENROUTER_MODEL).strip()
        return picked or _DEFAULT_OPENROUTER_MODEL

    def complete(
        self,
        messages: list[dict],
        *,
        max_tokens: int,
        temperature: float,
        timeout: int,
        model: str | None = None,
        plugins: list | None = None,
        extra_headers: dict | None = None,
    ) -> str:
        payload: dict = {
            "model": self.request_model(model),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.provider == "deepseek":
            # Flash по умолчанию думает. С max_tokens=32 (роутер тем) ответ съедается,
            # а temperature игнорируется. deepseek-chat был без thinking.
            payload["thinking"] = {"type": "disabled"}
        else:
            if plugins:
                payload["plugins"] = plugins
            headers["HTTP-Referer"] = "https://www.srogen.ru"
            if extra_headers:
                headers.update(extra_headers)
        sess = self.session()
        post_kwargs: dict = {
            "headers": headers,
            "json": payload,
            "timeout": timeout,
        }
        if not self.trust_env:
            post_kwargs["proxies"] = {} if self.proxies is None else self.proxies
        response = sess.post(self.chat_url, **post_kwargs)
        response.raise_for_status()
        message = ((response.json().get("choices") or [{}])[0].get("message") or {})
        content = message.get("content")
        if content is None:
            raise RuntimeError("empty_llm_content")
        return str(content).strip()


def create_llm_client() -> LlmClient:
    """Собрать клиент по LLM_PROVIDER. По умолчанию deepseek, без прокси."""
    _load_dotenv()
    provider = (_setting("LLM_PROVIDER", "deepseek") or "deepseek").strip().lower()
    if provider != "openrouter":
        provider = "deepseek"
    if provider == "openrouter":
        base = (_setting("OPENROUTER_BASE", _DEFAULT_OPENROUTER_BASE) or _DEFAULT_OPENROUTER_BASE).strip().rstrip("/")
        model = (_setting("OPENROUTER_MODEL", _DEFAULT_OPENROUTER_MODEL) or _DEFAULT_OPENROUTER_MODEL).strip()
        return LlmClient(
            provider="openrouter",
            base_url=base or _DEFAULT_OPENROUTER_BASE,
            api_key=_setting("OPENROUTER_API_KEY"),
            model=model or _DEFAULT_OPENROUTER_MODEL,
            proxies=None,
            trust_env=True,
        )
    base = (_setting("DEEPSEEK_BASE_URL", _DEFAULT_DEEPSEEK_BASE) or _DEFAULT_DEEPSEEK_BASE).strip().rstrip("/")
    model = (_setting("DEEPSEEK_MODEL", _DEFAULT_DEEPSEEK_MODEL) or _DEFAULT_DEEPSEEK_MODEL).strip()
    return LlmClient(
        provider="deepseek",
        base_url=base or _DEFAULT_DEEPSEEK_BASE,
        api_key=_setting("DEEPSEEK_API_KEY"),
        model=model or _DEFAULT_DEEPSEEK_MODEL,
        proxies=None,
        trust_env=False,
    )


def missing_key_name() -> str:
    if create_llm_client().provider == "openrouter":
        return "OPENROUTER_API_KEY"
    return "DEEPSEEK_API_KEY"
