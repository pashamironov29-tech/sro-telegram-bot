# -*- coding: utf-8 -*-
"""Скачать ключевые положения со всех сайтов партнёрских СРО → docs_qa/_raw/{suffix}/."""
from __future__ import annotations

import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = ROOT / "sro files" / "docs_qa" / "_raw"

REQUEST_HEADERS = {"User-Agent": "SRO-Bot/1.0 (+docs sync)"}
TIMEOUT = 60

# sro_id -> (filename_suffix, docs page URL)
SRO_DOCS = {
    "OGPS": ("ogps", "https://www.srogen.ru/sro/documenty_sro/"),
    "OGPP": ("ogpp", "https://www.srosp.ru/sro/documenty_sro/"),
    "GEOIND": ("geo", "https://www.srogeo.ru/sro/documenty_sro/"),
    "MOTS": ("mots", "https://www.sro-mots.ru/sro/documenty_sro/"),
    "OSO": ("oso", "https://www.srooso.ru/sro/documenty_sro/"),
    "SPROF": ("sprof", "https://www.sprofproekt.ru/sro/documenty_sro/"),
    "PRIIS": ("priis", "https://www.sro-priis.ru/sro/documenty_sro/"),
    "OPP": ("opp", "https://www.np-pspz.ru/sro/documenty_sro/"),
    "NOSO": ("noso", "https://www.sronoso.ru/sro/documenty_sro/"),
    "OSOES": ("osoes", "https://www.assrtm.ru/sro/documenty_sro/"),
    "OSOT": ("osot", "https://www.nup-sro.ru/sro/documenty_sro/"),
    "SOVS": ("sovs", "https://www.msro-sibir.ru/sro/documenty_sro/"),
    "OGPO": ("ogpo", "https://www.sroogpo.ru/sro/documenty_sro/"),
    "MGEO": ("mgeo", "https://www.sroigeo.ru/sro/documenty_sro/"),
    "GPS": ("gps", "https://www.sro-gps.ru/sro/documenty_sro/"),
}

# kind -> (out stem without suffix, title keywords any-of groups)
# Prefer more specific patterns first.
KIND_RULES: list[tuple[str, list[str]]] = [
    ("ustav", ["устав"]),
    ("standart", ["стандарт ассоциации", "стандарт сро", "стандартсаморегулируемой", "стандарт асс"]),
    ("chlenstvo", ["о членстве", "членстве в саморегулируемой"]),
    ("kontrol", ["о контроле", "контроле саморегулируемой", "контроле за деятельностью"]),
    ("kk", ["контрольном комитете", "контрольный комитет", "о контрольном комитете"]),
    ("reestr", ["о реестре членов", "реестре членов"]),
    ("zhaloby", ["жалоб", "рассмотрении жалоб"]),
    ("mery_disc", ["дисциплинарного воздействия", "мер дисциплинарного"]),
    ("kf_vv", ["компенсационном фонде возмещения вреда", "фонд возмещения вреда"]),
    ("kf_odo", ["компенсационном фонде обеспечения договорных", "фонд обеспечения договорных", "фонд договорных обязательств"]),
    ("strah_go", ["страховании гражданской ответственности"]),
    ("strah_odo", ["страховании риска", "риска ответственности"]),
    ("uved_dogovor", ["порядке уведомления", "уведомления членами"]),
    ("obmen_dok", ["обмене документами"]),
    ("analiz", ["анализе деятельности", "анализа деятельности"]),
    ("inform_otkrytost", ["информационной открытости", "раскрытии информации", "раскрытия информации"]),
]

SKIP_IF = (
    "свидетельство",
    "лист записи",
    "егрюл",
    "соут",
    "квалификационный стандарт",
    "антикоррупц",
    "правила деловой",
    "приложение к решению",
    "решение федеральной",
    "уведомление федеральной",
    "уведомление территориального",
    "приказ ростехнадзора",
)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower().replace("ё", "е")


def _fetch(url: str) -> str:
    r = requests.get(url, timeout=TIMEOUT, headers=REQUEST_HEADERS)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def _extract_links(html: str, base: str) -> list[tuple[str, str]]:
    # (href, surrounding text)
    out = []
    for m in re.finditer(
        r'<a[^>]+href=["\']([^"\']+\.(?:pdf|docx?|rtf))["\'][^>]*>(.*?)</a>',
        html,
        re.I | re.S,
    ):
        href = urljoin(base, m.group(1))
        text = re.sub(r"<[^>]+>", " ", m.group(2))
        out.append((href, _clean(text)))
    # sometimes title is outside <a> — also scan list items with href nearby
    for m in re.finditer(
        r'(?:<li[^>]*>|<div[^>]*class="[^"]*item[^"]*"[^>]*>)(.*?)(?:</li>|</div>)',
        html,
        re.I | re.S,
    ):
        block = m.group(1)
        hm = re.search(r'href=["\']([^"\']+\.(?:pdf|docx?|rtf))["\']', block, re.I)
        if not hm:
            continue
        href = urljoin(base, hm.group(1))
        text = _clean(re.sub(r"<[^>]+>", " ", block))
        out.append((href, text))
    # dedupe by href keeping longest text
    by_href: dict[str, str] = {}
    for href, text in out:
        if href not in by_href or len(text) > len(by_href[href]):
            by_href[href] = text
    return [(h, t) for h, t in by_href.items()]


def _match_kind(text: str, href: str) -> str | None:
    low = text + " " + _clean(Path(urlparse(href).path).name)
    if any(s in low for s in SKIP_IF):
        # allow ustav even if... no
        if "устав" not in low[:40] and "устав" not in Path(urlparse(href).path).name.lower():
            pass
    # skip noise
    for s in SKIP_IF:
        if s in low and "устав" not in low[:20]:
            # квалификационный стандарт — skip; стандарт ассоциации — keep via rules
            if s == "квалификационный стандарт":
                return None
            if s in ("свидетельство", "лист записи", "егрюл", "соут", "приложение к решению", "решение федеральной", "уведомление федеральной", "уведомление территориального", "приказ ростехнадзора", "антикоррупц", "правила деловой"):
                return None
    for kind, keys in KIND_RULES:
        if any(k in low for k in keys):
            # refine standart vs kvalif
            if kind == "standart" and "квалификационн" in low:
                continue
            # refine kontrol vs kk
            if kind == "kontrol" and ("комитет" in low or "kk_" in low):
                continue
            if kind == "strah_go" and ("риска" in low or "odo" in low):
                continue
            if kind == "kf_vv" and ("договорных" in low or "odo" in low):
                continue
            if kind == "kf_odo" and "возмещения вреда" in low and "договорных" not in low:
                continue
            return kind
    return None


def download_sro(sro_id: str, *, skip_existing: bool = True) -> dict:
    suffix, page_url = SRO_DOCS[sro_id]
    out_dir = RAW_ROOT / suffix
    out_dir.mkdir(parents=True, exist_ok=True)
    html = _fetch(page_url)
    links = _extract_links(html, page_url)
    picked: dict[str, tuple[str, str]] = {}
    for href, text in links:
        kind = _match_kind(text, href)
        if not kind:
            continue
        # prefer newer / longer filename if duplicate kind
        if kind not in picked or len(text) > len(picked[kind][1]):
            picked[kind] = (href, text)

    stats = {"sro": sro_id, "found": len(picked), "downloaded": 0, "kinds": sorted(picked)}
    for kind, (href, text) in picked.items():
        ext = Path(urlparse(href).path).suffix.lower() or ".doc"
        if ext not in {".doc", ".docx", ".pdf", ".rtf"}:
            ext = ".doc"
        dest = out_dir / f"polozhenie_{kind}_{suffix}{ext}"
        if kind == "ustav":
            dest = out_dir / f"ustav_{suffix}{ext}"
        elif kind == "standart":
            dest = out_dir / f"standart_assotsiatsii_{suffix}{ext}"
        elif kind == "inform_otkrytost":
            dest = out_dir / f"polozhenie_inform_otkrytost_{suffix}{ext}"
        else:
            dest = out_dir / f"polozhenie_{kind}_{suffix}{ext}"

        if skip_existing and dest.is_file() and dest.stat().st_size > 1000:
            continue
        try:
            r = requests.get(href, timeout=TIMEOUT, headers=REQUEST_HEADERS)
            r.raise_for_status()
            dest.write_bytes(r.content)
            stats["downloaded"] += 1
            print(f"  ok {dest.name} ({len(r.content)} b) ← {kind}")
            time.sleep(0.15)
        except Exception as e:
            print(f"  FAIL {kind}: {e}")
    print(f"{sro_id}: found {stats['found']} kinds {stats['kinds']}, new {stats['downloaded']}")
    return stats


def main() -> None:
    # skip already-complete locally if desired — still refresh missing kinds
    order = [
        "MOTS", "OSO", "SPROF", "PRIIS", "OPP", "NOSO", "OSOES", "OSOT",
        "SOVS", "OGPO", "MGEO", "GPS",
        # refresh missing for already done if any
        "OGPS", "OGPP", "GEOIND",
    ]
    all_stats = []
    for sro_id in order:
        print(f"\n=== {sro_id} ===")
        try:
            all_stats.append(download_sro(sro_id, skip_existing=True))
        except Exception as e:
            print(f"PAGE FAIL {sro_id}: {e}")
            all_stats.append({"sro": sro_id, "error": str(e)})
    print("\nDONE")
    for s in all_stats:
        print(s)


if __name__ == "__main__":
    main()
