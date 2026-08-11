"""Собрать ссылки на бланки со всех 15 СРО (перечень документов)."""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlparse

import requests

from reestr_sync import SRO_SOURCES

PERECHEN_PATH = "/kontrol_sro/kontrolniy_komitet/perechen_documentov/"

# эвристика: remote filename fragment -> ключ меню бота
KEY_RULES: list[tuple[str, str]] = [
    ("info_list", r"inf_list|list_[a-z]+|inform"),
    ("zayavlenie_izmeneniya", r"izm_|izmenen"),
    ("zayavlenie_proverka", r"zayavlenie(?!.*odo)"),
    ("doverennost", r"dov_"),
    ("svedeniya_spec", r"sved_"),
    ("polozhenie_kontrol", r"kontrol_"),
    ("uvedomlenie_odo", r"uvedomlenie"),
]


def _site_base(list_url: str) -> str:
    p = urlparse(list_url)
    return f"{p.scheme}://{p.netloc}"


def _classify(href: str) -> str | None:
    name = href.lower()
    for key, pattern in KEY_RULES:
        if re.search(pattern, name):
            if key == "zayavlenie_proverka" and "izm_" in name:
                continue
            return key
    return None


def discover_sro(sro_id: str, list_url: str) -> dict:
    base = _site_base(list_url)
    url = urljoin(base, PERECHEN_PATH)
    out: dict[str, str] = {"_page": url, "_base": base}
    try:
        r = requests.get(url, timeout=45, headers={"User-Agent": "GOLD-blanki-discover/1.0"})
        r.raise_for_status()
    except Exception as exc:
        out["_error"] = str(exc)
        return out

    links = re.findall(r'href=["\']([^"\']+\.(?:docx?|DOCX?))["\']', r.text, re.I)
    for href in links:
        if "/upload/" not in href.lower():
            continue
        key = _classify(href)
        if not key:
            continue
        path = href if href.startswith("/") else "/" + href.split("/", 3)[-1]
        if not path.startswith("/"):
            path = "/" + href.lstrip("/")
        # keep shortest path form
        if not path.startswith("/upload"):
            idx = href.find("/upload")
            if idx >= 0:
                path = href[idx:]
        if key not in out or len(path) < len(out[key]):
            out[key] = path
    return out


def main() -> None:
    result = {}
    for sro_id, meta in SRO_SOURCES.items():
        result[sro_id] = discover_sro(sro_id, meta["list_url"])
        keys = [k for k in result[sro_id] if not k.startswith("_")]
        print(sro_id, len(keys), "files", result[sro_id].get("_error", ""))

    from pathlib import Path

    path = Path(__file__).with_name("blanki_remote_map.json")
    with path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("written", path)


if __name__ == "__main__":
    main()
