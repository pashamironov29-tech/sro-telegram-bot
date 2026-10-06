"""LLM_PROVIDER=deepseek: клиент на api.deepseek.com и без прокси."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import llm_client


class _Resp:
    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": "ok"}}]}


class _Session:
    def __init__(self):
        self.trust_env = True
        self.posts: list[tuple[str, dict]] = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return _Resp()


class DeepSeekClientTests(unittest.TestCase):
    def setUp(self):
        self._saved = {}
        for name in (
            "LLM_PROVIDER",
            "DEEPSEEK_API_KEY",
            "DEEPSEEK_BASE_URL",
            "DEEPSEEK_MODEL",
            "OPENROUTER_BASE",
            "OPENROUTER_API_KEY",
            "OPENROUTER_MODEL",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        ):
            self._saved[name] = os.environ.get(name)
            os.environ.pop(name, None)

    def tearDown(self):
        for name, val in self._saved.items():
            if val is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = val

    def test_deepseek_client_base_url_without_proxy(self):
        os.environ["LLM_PROVIDER"] = "deepseek"
        os.environ["DEEPSEEK_API_KEY"] = "sk-test"
        os.environ["DEEPSEEK_BASE_URL"] = "https://api.deepseek.com"
        os.environ["DEEPSEEK_MODEL"] = "deepseek-chat"
        os.environ["HTTPS_PROXY"] = "http://nl-proxy.example:8080"
        os.environ["HTTP_PROXY"] = "http://nl-proxy.example:8080"
        os.environ["OPENROUTER_BASE"] = "https://nl-proxy.example/openrouter/v1"

        client = llm_client.create_llm_client()

        self.assertEqual(client.provider, "deepseek")
        self.assertEqual(client.base_url, "https://api.deepseek.com")
        self.assertEqual(client.chat_url, "https://api.deepseek.com/chat/completions")
        self.assertIsNone(client.proxies)
        self.assertFalse(client.trust_env)
        self.assertNotIn("nl-proxy", client.base_url)
        self.assertNotIn("openrouter", client.base_url)
        self.assertEqual(client.model, "deepseek-chat")

        created: list[_Session] = []

        def _factory():
            sess = _Session()
            created.append(sess)
            return sess

        with patch.object(llm_client.requests, "Session", _factory):
            text = client.complete(
                [{"role": "user", "content": "ping"}],
                max_tokens=32,
                temperature=0,
                timeout=10,
                model="google/gemini-2.5-flash",
                plugins=[{"id": "file-parser"}],
                extra_headers={"X-Title": "should-not-leak"},
            )

        self.assertEqual(text, "ok")
        self.assertEqual(len(created), 1)
        self.assertFalse(created[0].trust_env)
        url, kwargs = created[0].posts[0]
        self.assertEqual(url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(kwargs.get("proxies"), {})
        body = kwargs["json"]
        self.assertEqual(body["model"], "deepseek-flash")
        self.assertEqual(body["thinking"], {"type": "disabled"})
        self.assertNotIn("plugins", body)
        self.assertEqual(body["messages"], [{"role": "user", "content": "ping"}])
        self.assertEqual(body["temperature"], 0)
        self.assertEqual(body["max_tokens"], 32)
        self.assertNotIn("X-Title", kwargs["headers"])
        self.assertNotIn("HTTP-Referer", kwargs["headers"])

    def test_openrouter_keeps_proxy_base(self):
        os.environ["LLM_PROVIDER"] = "openrouter"
        os.environ["OPENROUTER_API_KEY"] = "sk-or-test"
        os.environ["OPENROUTER_BASE"] = "https://nl-proxy.example/openrouter/v1"
        os.environ["OPENROUTER_MODEL"] = "openai/gpt-4.1-mini"

        client = llm_client.create_llm_client()

        self.assertEqual(client.provider, "openrouter")
        self.assertEqual(client.base_url, "https://nl-proxy.example/openrouter/v1")
        self.assertTrue(client.trust_env)
        self.assertEqual(client.request_model("google/gemini-2.5-flash"), "google/gemini-2.5-flash")


if __name__ == "__main__":
    unittest.main()
