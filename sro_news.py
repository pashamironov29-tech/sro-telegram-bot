# -*- coding: utf-8 -*-
"""Новости НОСТРОЙ / НОПРИЗ / Минстрой для СРО-бота.

MVP: кнопка «Новости стройки» → свежие заголовки + ссылки.
Кэш на диске рядом с ботом (news_cache.json). Не класть секреты.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, parse_qs

import requests

NEWS_BUTTON = "📰 Новости стройки"

def is_news_button_text(text: str) -> bool:
    """Кнопка/фраза новостей — с любым эмодзи или без (📰/🏗 и т.п.)."""
    raw = (text or "").strip()
    if not raw:
        return False
    if raw == NEWS_BUTTON:
        return True
    low = raw.lower().replace("ё", "е")
    if "новости стройки" in low:
        return True
    # без эмодзи в начале
    core = re.sub(r"^[\s\W_]+", "", raw, flags=re.UNICODE).lower().replace("ё", "е")
    return core.startswith("новости стройки") or core == "новости"


NEWS_BACK_HINT = "⬅️ Назад в меню"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
}

SOURCES: list[dict[str, str]] = [
    {
        "id": "nostroy",
        "name": "НОСТРОЙ",
        "list_url": "https://nostroy.ru/news/",
        "base": "https://nostroy.ru",
    },
    {
        "id": "nopriz",
        "name": "НОПРИЗ",
        "list_url": "https://nopriz.ru/news/",
        "base": "https://nopriz.ru",
    },
    {
        "id": "minstroy",
        "name": "Минстрой",
        "list_url": "https://minstroyrf.gov.ru/press/news/",
        "base": "https://minstroyrf.gov.ru",
    },
]

_CACHE_NAME = "news_cache.json"
_CACHE_TTL_SEC = 6 * 3600
_MAX_ITEMS = 40
_SHOW_DEFAULT = 5


def _cache_path() -> Path:
    return Path(__file__).resolve().parent / _CACHE_NAME


def _clean_title(raw: str) -> str:
    t = unescape(re.sub(r"<[^>]+>", "", raw or ""))
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _abs_url(base: str, href: str) -> str:
    return urljoin(base.rstrip("/") + "/", href)


def _item_id(source_id: str, url: str) -> str:
    return f"{source_id}:{url}"


def _parse_list_html(source: dict[str, str], html: str) -> list[dict[str, str]]:
    sid = source["id"]
    base = source["base"]
    out: list[dict[str, str]] = []
    seen: set[str] = set()

    for href, title_raw in re.findall(
        r'href="([^"]+)"[^>]*>([^<]{12,220})',
        html,
        flags=re.I,
    ):
        title = _clean_title(title_raw)
        if len(title) < 25:
            continue
        href_l = href.lower()
        ok = False
        if sid == "nostroy":
            if "eid=" in href_l and "/news/" in href_l and "operativnyy" not in href_l:
                ok = True
        elif sid == "nopriz":
            if re.search(r"[?&]id=\d+", href_l) and "/news/" in href_l:
                ok = True
        elif sid == "minstroy":
            if href_l.startswith("/press/") and href_l.rstrip("/") != "/press/news":
                if "press/news" not in href_l or href_l.count("/") > 2:
                    # /press/slug/
                    if re.match(r"^/press/[a-z0-9_\-]+/?$", href_l):
                        ok = True
        if not ok:
            continue
        url = _abs_url(base, href)
        if url in seen:
            continue
        seen.add(url)
        out.append(
            {
                "id": _item_id(sid, url),
                "source": sid,
                "source_name": source["name"],
                "title": title[:200],
                "url": url,
            }
        )
        if len(out) >= 15:
            break
    return out


def fetch_source(source: dict[str, str], timeout: float = 20.0) -> list[dict[str, str]]:
    try:
        resp = requests.get(source["list_url"], headers=_UA, timeout=timeout)
        resp.raise_for_status()
        # encoding
        resp.encoding = resp.apparent_encoding or "utf-8"
        return _parse_list_html(source, resp.text)
    except Exception as exc:
        logging.warning("sro_news fetch %s failed: %s", source["id"], exc)
        return []


def load_cache() -> dict[str, Any]:
    path = _cache_path()
    if not path.exists():
        return {"updated_at": 0, "items": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"updated_at": 0, "items": []}
        data.setdefault("updated_at", 0)
        data.setdefault("items", [])
        return data
    except Exception:
        return {"updated_at": 0, "items": []}


def save_cache(items: list[dict[str, str]]) -> dict[str, Any]:
    data = {
        "updated_at": time.time(),
        "updated_iso": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M"),
        "items": items[:_MAX_ITEMS],
    }
    path = _cache_path()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def refresh_news(*, force: bool = False) -> dict[str, Any]:
    cache = load_cache()
    age = time.time() - float(cache.get("updated_at") or 0)
    if not force and cache.get("items") and age < _CACHE_TTL_SEC:
        return cache

    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    # round-robin: take from each source in turn so лента смешанная
    buckets = [fetch_source(src) for src in SOURCES]
    max_len = max((len(b) for b in buckets), default=0)
    for i in range(max_len):
        for bucket in buckets:
            if i >= len(bucket):
                continue
            item = bucket[i]
            if item["url"] in seen:
                continue
            seen.add(item["url"])
            item["fetched_at"] = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
            merged.append(item)
            if len(merged) >= _MAX_ITEMS:
                break
        if len(merged) >= _MAX_ITEMS:
            break

    if not merged and cache.get("items"):
        # сеть упала — оставить старое
        return cache
    return save_cache(merged)


def format_news_message(limit: int = _SHOW_DEFAULT, *, force_refresh: bool = False) -> str:
    data = refresh_news(force=force_refresh)
    items = list(data.get("items") or [])[: max(1, limit)]
    updated = data.get("updated_iso") or "—"
    if not items:
        return (
            "📰 <b>Новости стройки</b>\n\n"
            "Сейчас не удалось загрузить ленту. Попробуйте позже.\n\n"
            "<i>Источники: НОСТРОЙ, НОПРИЗ, Минстрой РФ.</i>"
        )

    lines = [
        "📰 <b>Новости стройки / СРО</b>",
        f"<i>Обновлено: {updated}</i>",
        "",
    ]
    for i, it in enumerate(items, 1):
        src = it.get("source_name") or it.get("source") or ""
        title = (it.get("title") or "").replace("<", "&lt;").replace(">", "&gt;")
        url = it.get("url") or ""
        lines.append(f"{i}. <b>[{src}]</b> {title}")
        lines.append(f'   <a href="{url}">открыть</a>')
        lines.append("")
    lines.append("⚠️ <i>Кратко по заголовкам. Полный текст — по ссылке. Не юридическая консультация.</i>")
    lines.append("")
    lines.append("Источники: nostroy.ru · nopriz.ru · minstroyrf.gov.ru")
    return "\n".join(lines)


def news_sources_footer() -> str:
    return "nostroy.ru · nopriz.ru · minstroyrf.gov.ru"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(format_news_message(limit=5, force_refresh=True))
