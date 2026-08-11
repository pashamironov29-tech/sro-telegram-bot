#!/usr/bin/env python3
"""
Проверка месячного плана из sro files/plany/*.docx:
- исключена ли организация (не «Член СРО»);
- сколько проверок в указанном году (по умолчанию текущий).

Перед проверкой по умолчанию всегда обновляет реестр (list-only),
чтобы статусы «Исключен» не были из устаревшего кэша.

Пример:
  py plan_month_check.py --month сентябрь --skip-sro ОСОВС,ОСОТ,НОСО,ОСОЕС --live
  py plan_month_check.py --month сентябрь --no-fresh-reestr   # только если кэш уже свежий
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from pathlib import Path

from docx import Document

from config_keys import SRO_FILES_DIR
from reestr_sync import (
    enrich_reestr_entry,
    fetch_reestr_detail,
    load_reestr_cache,
    plany_key_from_filename,
    sro_display_name,
    sync_all_sro_list_only,
)

MONTHS = [
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def _month_label(month: str) -> str:
    m = month.strip().lower()
    for name in MONTHS:
        if name in m or m in name:
            return name.upper()
    raise ValueError(f"Неизвестный месяц: {month!r}")


def _skip_sro_set(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {part.strip() for part in raw.split(",") if part.strip()}


def _reason_inspection_count(n: int, year: str) -> str:
    if n <= 0:
        return ""
    if n == 1:
        return f"1 проверка в {year}"
    if 2 <= n <= 4:
        return f"{n} проверки в {year}"
    return f"{n} проверок в {year}"


def extract_month_rows(plany_dir: Path, month_target: str, skip_sro: set[str]) -> list[dict]:
    month_upper = _month_label(month_target)
    rows: list[dict] = []

    for file_path in sorted(plany_dir.glob("*.docx")):
        sro_key = plany_key_from_filename(file_path.name)
        sro_label = sro_display_name(sro_key)
        if sro_label in skip_sro or sro_key in skip_sro:
            continue

        doc = Document(str(file_path))
        current_month = ""

        for table in doc.tables:
            for row in table.rows:
                cells_text: list[str] = []
                for cell in row.cells:
                    txt = _norm(cell.text)
                    if txt and txt not in cells_text:
                        cells_text.append(txt)
                if not cells_text:
                    continue

                joined = " ".join(cells_text).lower()
                if len(cells_text) <= 3 and any(m in joined for m in MONTHS):
                    for m in MONTHS:
                        if m in joined:
                            current_month = m.upper()
                            break
                    continue

                if current_month != month_upper:
                    continue

                inn = ""
                inn_index = -1
                for idx, text in enumerate(cells_text):
                    clean = text.replace(" ", "")
                    if clean.isdigit() and 9 <= len(clean) <= 12:
                        inn = clean
                        inn_index = idx
                        break
                if not inn:
                    continue

                name = "Организация СРО"
                potential = [
                    t
                    for t in cells_text[:inn_index]
                    if not t.replace(" ", "").isdigit() and len(t) > 2
                ]
                if potential:
                    name = max(potential, key=len)

                rows.append(
                    {
                        "sro": sro_label,
                        "sro_key": sro_key,
                        "name": name,
                        "inn": inn,
                        "source_file": file_path.name,
                    }
                )
    return rows


def check_rows(
    rows: list[dict],
    cache: dict,
    year: str,
    live: bool,
) -> list[dict]:
    if live:
        # уникальные пары СРО+ИНН — статус может отличаться по СРО
        pairs: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for row in rows:
            key = (row["sro_key"], row["inn"])
            if key in seen:
                continue
            seen.add(key)
            pairs.append(key)

        print(f"Живая проверка карточек: {len(pairs)}…", flush=True)
        start = time.time()
        for i, (sro_key, inn) in enumerate(pairs, 1):
            org = cache.get(inn) or {"inn": inn, "title": None, "memberships": {}}
            mem = (org.get("memberships") or {}).get(sro_key) or {}
            try:
                if mem.get("url"):
                    detailed = fetch_reestr_detail(mem)
                    org.setdefault("memberships", {})[sro_key] = detailed
                    cache[inn] = org
                else:
                    enrich_reestr_entry(inn, cache, timeout=25.0)
            except Exception as exc:
                print(f"  ⚠️ {sro_key}/{inn}: {exc}", flush=True)
            if i % 25 == 0 or i == len(pairs):
                print(f"  … {i}/{len(pairs)} ({int(time.time() - start)} с)", flush=True)

    flagged: list[dict] = []
    for row in rows:
        org = cache.get(row["inn"]) or {}
        mem = (org.get("memberships") or {}).get(row["sro_key"]) or {}
        status = mem.get("status") or "НЕТ В КЭШЕ"
        insp_list = mem.get("inspections") or []
        if insp_list:
            count = sum(1 for x in insp_list if str(x.get("year")) == year)
            results = [x.get("result") for x in insp_list if str(x.get("year")) == year]
        else:
            by_year = mem.get("inspections_by_year") or {}
            count = 1 if year in by_year else 0
            results = [by_year[year]] if count else []

        reasons: list[str] = []
        mark = ""
        if mem.get("duplicated"):
            reasons.append("Организация задваивается")
            mark = "duplicate"
        elif status != "Член СРО":
            reasons.append("исключена")
            mark = "exclude"
        insp_reason = _reason_inspection_count(count, year)
        if insp_reason:
            reasons.append(insp_reason)
            if not mark:
                mark = "multi" if count >= 2 else "one"

        if reasons:
            flagged.append(
                {
                    **row,
                    "status": status,
                    "reason": " + ".join(reasons),
                    "mark": mark,
                    "count_" + year: count,
                    "results_" + year: results,
                    "latest_disciplinary": mem.get("latest_disciplinary"),
                }
            )
    return flagged


def main() -> None:
    parser = argparse.ArgumentParser(description="Проверка месячного плана СРО")
    parser.add_argument("--month", required=True, help="месяц: сентябрь, октябрь…")
    parser.add_argument(
        "--skip-sro",
        default="ОСОВС,ОСОТ,НОСО,ОСОЕС",
        help="СРО через запятую (display name), не проверять",
    )
    parser.add_argument("--year", default=str(time.localtime().tm_year), help="год проверок")
    parser.add_argument("--live", action="store_true", help="догрузить карточки с сайтов")
    parser.add_argument(
        "--no-fresh-reestr",
        action="store_true",
        help="не обновлять реестр перед проверкой (только если кэш уже свежий)",
    )
    parser.add_argument("--out", default="", help="файл JSON (по умолчанию plan_check_<месяц>_flagged.json)")
    args = parser.parse_args()

    plany_dir = Path(SRO_FILES_DIR) / "plany"
    if not plany_dir.is_dir():
        raise SystemExit(f"Нет папки планов: {plany_dir}")

    if not args.no_fresh_reestr:
        print(
            "🔄 Обновляю реестр (list-only) перед проверкой плана…\n"
            "   Это нужно, чтобы «Исключен» не брался из старого кэша.",
            flush=True,
        )
        sync_all_sro_list_only(show_progress=True)
        print("✅ Реестр обновлён.\n", flush=True)
    else:
        print("⚠️ --no-fresh-reestr: беру текущий кэш без обновления списка.\n", flush=True)

    skip = _skip_sro_set(args.skip_sro)
    rows = extract_month_rows(plany_dir, args.month, skip)
    cache = load_reestr_cache()
    flagged = check_rows(rows, cache, args.year, live=args.live)

    month_slug = _month_label(args.month).lower()
    out_path = Path(args.out or f"plan_check_{month_slug}_flagged.json")
    out_path.write_text(json.dumps(flagged, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nВсего строк в плане: {len(rows)}")
    print("По СРО:", dict(Counter(r["sro"] for r in rows)))
    print(f"Отмечено: {len(flagged)}")
    print("Метки:", dict(Counter(r.get("mark") or "?" for r in flagged)))
    print(f"Сохранено: {out_path}")


if __name__ == "__main__":
    main()
