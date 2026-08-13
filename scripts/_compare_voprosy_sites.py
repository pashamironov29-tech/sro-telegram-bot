"""Сравнение списков «Вопрос-ответ» на сайтах СРО (разовый скрипт)."""
import re
from difflib import SequenceMatcher

import requests

SITES = {
    "GEN_srogen": "https://www.srogen.ru/voprosy/",
    "OGPP_srosp": "https://www.srosp.ru/voprosy/",
    "OSO_srooso": "https://srooso.ru/voprosy/",
}

UA = {"User-Agent": "SRO-Bot/1.0 (compare faq)"}


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_questions(html: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def add(q: str) -> None:
        q = _clean(q)
        if len(q) < 20 or "?" not in q:
            return
        key = q.lower()
        if key in seen:
            return
        seen.add(key)
        found.append(q)

    for m in re.finditer(r"<li[^>]*>(.*?)</li>", html, re.I | re.S):
        add(m.group(1))
    for m in re.finditer(r"<h[234][^>]*>(.*?)</h[234]>", html, re.I | re.S):
        add(m.group(1))
    for m in re.finditer(r"<a[^>]+href=[^>]*>(.*?)</a>", html, re.I | re.S):
        t = _clean(m.group(1))
        if "?" in t and len(t) > 25:
            add(t)
    for m in re.finditer(r"\|\s*([^|]{25,}?\?)\s*\|", html):
        add(m.group(1))

    return found


def best_ratio(a: str, options: list[str]) -> float:
    al = a.lower()
    return max((SequenceMatcher(None, al, o.lower()).ratio() for o in options), default=0.0)


def main() -> None:
    data: dict[str, list[str]] = {}
    for name, url in SITES.items():
        r = requests.get(url, headers=UA, timeout=45)
        r.encoding = r.apparent_encoding or "utf-8"
        qs = extract_questions(r.text)
        data[name] = qs
        print(f"\n=== {name} ({url}) — {len(qs)} вопросов ===")
        for i, q in enumerate(qs[:12], 1):
            print(f"{i:2}. {q[:110]}{'…' if len(q) > 110 else ''}")
        if len(qs) > 12:
            print(f"    … ещё {len(qs) - 12}")

    base = data["GEN_srogen"]
    for other in ("OGPP_srosp", "OSO_srooso"):
        oqs = data[other]
        matched = sum(1 for b in base if best_ratio(b, oqs) >= 0.72)
        print(f"\nПохожие на GEN (≥0.72): {other} — {matched}/{len(base)}")

    print("\nПримеры только на GEN (нет близкого в OSO):")
    oqs = data["OSO_srooso"]
    only = [b for b in base if best_ratio(b, oqs) < 0.55][:5]
    for q in only:
        print(" •", q[:100])


if __name__ == "__main__":
    main()
