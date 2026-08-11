"""Синхронизация реестров всех партнёрских СРО и форматирование карточки организации."""

from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from html import unescape
from urllib.parse import urljoin

import requests

REQUEST_HEADERS = {"User-Agent": "SRO-Bot/1.0 (+reestr sync)"}
REQUEST_TIMEOUT = 45
DETAIL_WORKERS = 6
DETAIL_DELAY = 0.12

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(CURRENT_DIR, "reestr_cache.json")
PLAN_YEAR = datetime.now().year
INSPECTION_YEARS_SHOWN = 3

# Все партнёрские СРО: id -> название и URL реестра
SRO_SOURCES = {
    "OGPS": {"name": "ОГПС", "list_url": "https://www.srogen.ru/reestr/"},
    "MOTS": {"name": "МОТС", "list_url": "https://www.sro-mots.ru/reestr/"},
    "OGPP": {"name": "ОГПП", "list_url": "https://www.srosp.ru/reestr/"},
    "OSO": {"name": "ОСО", "list_url": "https://srooso.ru/reestr/"},
    "SPROF": {"name": "СПРОФ", "list_url": "https://sprofproekt.ru/reestr/"},
    "PRIIS": {"name": "ПРИИС", "list_url": "https://sro-priis.ru/reestr/"},
    "OPP": {"name": "ОПП", "list_url": "https://np-pspz.ru/reestr/"},
    "NOSO": {"name": "НОСО", "list_url": "https://www.sronoso.ru/reestr/"},
    "OSOES": {"name": "ОСОЕС", "list_url": "https://assrtm.ru/reestr/"},
    "OSOT": {"name": "ОСОТ", "list_url": "https://nup-sro.ru/reestr/"},
    "SOVS": {"name": "ОСОВС", "list_url": "https://www.msro-sibir.ru/reestr/"},
    "OGPO": {"name": "ОГПО", "list_url": "https://sroogpo.ru/reestr/"},
    "MGEO": {"name": "МГЕО", "list_url": "https://sroigeo.ru/reestr/"},
    "GEOIND": {"name": "ГеоИндустрия", "list_url": "https://www.srogeo.ru/reestr/"},
    "GPS": {"name": "ГПС", "list_url": "https://sro-gps.ru/reestr/"},
}

# Имена файлов plany/*.docx -> id СРО
PLANY_FILE_TO_SRO = {
    "OGPS": "OGPS",
    "GEOINDUSTRIYA": "GEOIND",
    "GEO": "MGEO",
    "GPS": "GPS",
    "OGPP": "OGPP",
    "OGPO": "OGPO",
    "OSO": "OSO",
    "OSOES": "OSOES",
    "OSOT": "OSOT",
    "OSOVS": "SOVS",
    "NOSO": "NOSO",
    "OPP": "OPP",
    "PRIIS": "PRIIS",
    "SPROFPROEKT": "SPROF",
    "MOTS": "MOTS",
}


def plany_key_from_filename(file_name: str) -> str:
    base = file_name.replace(".docx", "")
    base = re.sub(r"_20\d{2}$", "", base, flags=re.I).upper()
    return PLANY_FILE_TO_SRO.get(base, base)


def sro_display_name(sro_id: str) -> str:
    return SRO_SOURCES.get(sro_id, {}).get("name", sro_id)


def _clean_html(text: str) -> str:
    text = unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _label_value(html: str, label: str) -> str | None:
    # Учитываем атрибуты в кавычках (у «Страховая компания» в title есть <b>…</b>)
    match = re.search(
        rf'<span class="label">{re.escape(label)}:</span>\s*'
        rf'<span\b(?:[^>"\']|"[^"]*"|\'[^\']*\')*>\s*(.*?)\s*</span>',
        html,
        re.S,
    )
    if not match:
        return None
    return _clean_html(match.group(1)) or None


def _fetch(url: str) -> str:
    response = requests.get(url, timeout=REQUEST_TIMEOUT, headers=REQUEST_HEADERS)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def _parse_list_page(html: str, list_url: str) -> list[dict]:
    entries = []
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        if "/reestr/" not in row_html:
            continue
        uuid_match = re.search(r"/reestr/([a-f0-9-]{36})/", row_html)
        if not uuid_match:
            continue
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S)
        clean_cells = [_clean_html(cell) for cell in cells]
        clean_cells = [cell for cell in clean_cells if cell]
        if len(clean_cells) < 4:
            continue
        inn_match = re.search(r"\d{9,12}", " ".join(clean_cells))
        if not inn_match:
            continue
        status, short_name, _, reg_date = clean_cells[:4]
        uuid = uuid_match.group(1)
        entries.append(
            {
                "inn": inn_match.group(0),
                "short_name": short_name,
                "status": status,
                "reg_date": reg_date,
                "uuid": uuid,
                "url": urljoin(list_url, f"/reestr/{uuid}/"),
            }
        )
    return entries


def _max_list_page(html: str) -> int:
    pages = [int(value) for value in re.findall(r"PAGEN_1=(\d+)", html)]
    return max(pages) if pages else 1


def _parse_inspections(html: str) -> list[dict]:
    marker = "Сведения о результатах проведенных"
    start = html.find(marker)
    if start == -1:
        return []
    chunk = html[start : start + 12000]
    inspections = []
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", chunk, re.S)[1:]:
        cells = [_clean_html(cell) for cell in re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S)]
        if len(cells) >= 2 and re.fullmatch(r"\d{4}", cells[0]):
            inspections.append({"year": cells[0], "result": cells[1]})
    return inspections


def _group_inspections_by_year(inspections: list[dict]) -> dict[str, str]:
    grouped: dict[str, str] = {}
    for item in inspections:
        year = item["year"]
        result = item["result"]
        if year not in grouped:
            grouped[year] = result
            continue
        if "не выявлено" not in grouped[year].lower():
            continue
        grouped[year] = result
    return grouped


def _parse_disciplinary(html: str) -> list[dict]:
    marker = "Сведения о фактах применения мер дисциплинарного"
    start = html.find(marker)
    if start == -1:
        return []
    chunk = html[start : start + 20000]
    measures = []
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", chunk, re.S)[1:]:
        cells = [_clean_html(cell) for cell in re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S)]
        if len(cells) < 2:
            continue
        date_raw, measure = cells[0].strip(), cells[1].strip()
        if date_raw and measure:
            measures.append({"date": date_raw, "measure": measure})
    return measures


def _latest_disciplinary(measures: list[dict]) -> dict | None:
    if not measures:
        return None
    return measures[-1]


def _status_from_disciplinary(measures: list[dict]) -> str | None:
    """На карточке исключение часто только в дисциплине, а в списке ещё «Член СРО»."""
    for item in reversed(measures or []):
        measure = (item.get("measure") or "").lower()
        if "исключен" in measure or "права прекращено" in measure:
            return "Исключен"
    return None


def _recent_inspection_years() -> set[str]:
    current = datetime.now().year
    return {str(current - offset) for offset in range(INSPECTION_YEARS_SHOWN - 1, -1, -1)}



def _format_discipline_date(date_raw: str) -> str:
    return date_raw.replace("\xa0", " ").replace(" г.", "").strip()


def _format_discipline_line(latest: dict) -> str:
    measure = latest.get("measure", "").strip()
    date_raw = _format_discipline_date(latest.get("date", ""))
    measure_lower = measure[:1].lower() + measure[1:] if measure else measure
    return f"{measure_lower} от {date_raw}"


def membership_needs_detail_fetch(membership: dict) -> bool:
    if not membership.get("url"):
        return False
    if not membership.get("inspections_by_year"):
        return True
    # уровни КФ появились позже — один раз дотянуть карточку
    if "kf_level_vv" not in membership:
        return True
    return False


_LEVEL_WORD_TO_NUM = (
    ("перв", 1),
    ("втор", 2),
    ("треть", 3),
    ("трет", 3),
    ("четверт", 4),
    ("пят", 5),
    ("шест", 6),
    ("седьм", 7),
    ("восьм", 8),
    ("девят", 9),
    ("десят", 10),
)


def _parse_level_number(text: str | None) -> int | None:
    """«Первый уровень…» / «уровень 2» → 1/2. Пусто / не предусмотрено → None."""
    if not text:
        return None
    low = text.lower().replace("ё", "е")
    if any(
        x in low
        for x in (
            "не предусмотрен",
            "не предусмотр",
            "отсутств",
            "не вносился",
            "не вносилась",
            "нет данных",
        )
    ):
        return None
    if low.strip() in {"—", "-", "нет", ""}:
        return None
    m = re.search(r"(?<!\d)([1-9]|10)(?!\d)", low)
    if m and ("уровн" in low or "ответственн" in low or low.strip().isdigit()):
        return int(m.group(1))
    for stem, num in _LEVEL_WORD_TO_NUM:
        if stem in low:
            return num
    m2 = re.search(r"уровен[ья]\s*([1-9]|10)\b", low)
    if m2:
        return int(m2.group(1))
    return None


def _name_line_value(html: str, name: str) -> str | None:
    """Блок <div class=\"name\">…</div><div class=\"item\"><div class=\"line\">…"""
    match = re.search(
        rf'<div class="name">\s*{re.escape(name)}\s*:?\s*</div>\s*'
        rf'<div class="item">\s*<div class="line">\s*(.*?)\s*</div>',
        html,
        re.S | re.I,
    )
    if not match:
        return None
    return _clean_html(match.group(1)) or None


def _format_kf_money(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = re.sub(r"[^\d]", "", raw)
    if not digits:
        return None
    try:
        n = int(digits)
    except ValueError:
        return raw.strip()
    return f"{n:,}".replace(",", " ") + " ₽"


def _format_kf_level_line(level: int | None, money: str | None, *, label: str) -> str | None:
    if level is None and not money:
        return None
    if level is not None and money:
        return f"  🛡️ {label}: ур. {level} · {money}"
    if level is not None:
        return f"  🛡️ {label}: ур. {level}"
    return f"  🛡️ {label}: {money}"


def _parse_detail_page(html: str) -> dict:
    h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    title = _clean_html(h1_match.group(1)) if h1_match else None
    full_name = _label_value(html, "Полное наименование организации")
    if not full_name:
        full_name = _label_value(html, "Индивидуальный предприниматель")
    reg_date = _label_value(html, "Дата регистрации в реестре")
    reg_number = _label_value(html, "Регистрационный номер в реестре")
    location = _label_value(html, "Местонахождение")
    director = _label_value(html, "Сведения о руководителе")
    insurance_company = _label_value(html, "Страховая компания")
    insurance_sum = _label_value(html, "Страховая сумма по договору страхования")
    ogrn = _label_value(html, "ОГРН")
    level_vv_raw = _name_line_value(html, "Возмещение вреда")
    level_odo_raw = _name_line_value(html, "Обеспечение договорных обязательств")
    kf_sum_vv = _label_value(html, "Сумма взноса в компенсационный фонд возмещения вреда")
    kf_sum_odo = _label_value(
        html, "Сумма взноса в компенсационный фонд договорных обязательств"
    )
    if not kf_sum_odo:
        kf_sum_odo = _label_value(
            html,
            "Сумма взноса в компенсационный фонд обеспечения договорных обязательств",
        )
    inspections = _parse_inspections(html)
    disciplinary = _parse_disciplinary(html)
    detail = {
        "title": title,
        "full_name": full_name,
        "reg_date": reg_date,
        "reg_number": reg_number,
        "location": location,
        "director": director,
        "insurance_company": insurance_company,
        "insurance_sum": insurance_sum,
        "ogrn": ogrn,
        "kf_level_vv": _parse_level_number(level_vv_raw),
        "kf_level_odo": _parse_level_number(level_odo_raw),
        "kf_level_vv_raw": level_vv_raw,
        "kf_level_odo_raw": level_odo_raw,
        "kf_sum_vv": kf_sum_vv,
        "kf_sum_odo": kf_sum_odo,
        "inspections": inspections,
        "inspections_by_year": _group_inspections_by_year(inspections),
        "disciplinary_measures": disciplinary,
        "latest_disciplinary": _latest_disciplinary(disciplinary),
    }
    status_from_disc = _status_from_disciplinary(disciplinary)
    if status_from_disc:
        detail["status"] = status_from_disc
    return detail


def _prefer_membership(current: dict | None, new: dict) -> dict:
    """Слияние записи: свежий статус из списка + детали карточки из кэша."""
    if current is None:
        return new
    merged = {**current, **new}
    for key in ("status", "reg_date", "short_name", "title", "url", "uuid", "sro_id", "sro_name"):
        if new.get(key) is not None and new.get(key) != "":
            merged[key] = new[key]
    # детали карточки не затираем пустым списком
    for key in (
        "inspections",
        "inspections_by_year",
        "disciplinary_measures",
        "latest_disciplinary",
        "reg_number",
        "location",
        "director",
        "insurance_company",
        "insurance_sum",
        "full_name",
        "ogrn",
    ):
        if not new.get(key) and current.get(key):
            merged[key] = current[key]
    # уровни/суммы КФ: не затирать list-only записью без этих ключей
    for key in (
        "kf_level_vv",
        "kf_level_odo",
        "kf_level_vv_raw",
        "kf_level_odo_raw",
        "kf_sum_vv",
        "kf_sum_odo",
    ):
        if key not in new and key in current:
            merged[key] = current[key]
    # Свежий «Исключен» из списка всегда побеждает.
    # Если список ещё «Член СРО», а в кэше уже исключение с карточки — оставляем исключение.
    new_status = (new.get("status") or "").strip()
    cur_status = (current.get("status") or "").strip()
    if new_status and new_status != "Член СРО":
        merged["status"] = new_status
    elif cur_status == "Исключен" and new_status == "Член СРО":
        merged["status"] = "Исключен"
    if current.get("duplicated") or new.get("duplicated"):
        merged["duplicated"] = True
    return merged


def _empty_org(inn: str) -> dict:
    return {"inn": inn, "title": None, "memberships": {}}


def _migrate_org_entry(inn: str, entry: dict) -> dict:
    if "memberships" in entry:
        return entry
    membership = {k: v for k, v in entry.items() if k not in {"inn", "title", "memberships"}}
    membership.setdefault("sro_id", "OGPS")
    membership.setdefault("sro_name", "ОГПС")
    return {
        "inn": inn,
        "title": entry.get("title") or entry.get("short_name"),
        "memberships": {"OGPS": membership},
    }


def _save_cache(by_inn: dict, show_progress: bool = False) -> None:
    payload = {
        "synced_at": datetime.now().isoformat(timespec="seconds"),
        "count": len(by_inn),
        "sro_count": len(SRO_SOURCES),
        "organizations": by_inn,
    }
    with open(CACHE_FILE, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
    if show_progress:
        print(f"💾 Кэш сохранён: {len(by_inn)} организаций", flush=True)


def fetch_reestr_detail(entry: dict) -> dict:
    html = _fetch(entry["url"])
    detail = _parse_detail_page(html)
    merged = {**entry, **detail}
    for key in (
        "reg_date",
        "reg_number",
        "location",
        "director",
        "insurance_company",
        "insurance_sum",
        "full_name",
        "ogrn",
        "status",
    ):
        if detail.get(key):
            merged[key] = detail[key]
    return merged


_DETAIL_FILL_KEYS = (
    "reg_number",
    "location",
    "director",
    "insurance_company",
    "insurance_sum",
    "ogrn",
)


def ensure_membership_details(membership: dict) -> dict:
    """Догружает карточку, если нет полей для бланка (даже когда проверки уже в кэше)."""
    if not membership.get("url"):
        return membership
    if all(membership.get(k) for k in _DETAIL_FILL_KEYS):
        return membership
    try:
        return fetch_reestr_detail(membership)
    except Exception:
        return membership


def ensure_membership_reg_number(membership: dict) -> dict:
    """Совместимость со старым именем."""
    return ensure_membership_details(membership)


def _fetch_detail(entry: dict) -> dict:
    time.sleep(DETAIL_DELAY)
    return fetch_reestr_detail(entry)


def sync_one_sro_list(sro_id: str, by_inn: dict, show_progress: bool = True) -> int:
    source = SRO_SOURCES[sro_id]
    list_url = source["list_url"]
    if show_progress:
        print(f"\n📂 {source['name']} ({list_url})", flush=True)

    first_page_html = _fetch(list_url)
    max_page = _max_list_page(first_page_html)
    added = 0
    inn_uuids: dict[str, set[str]] = {}

    for page in range(1, max_page + 1):
        try:
            html = first_page_html if page == 1 else _fetch(f"{list_url}?PAGEN_1={page}")
        except Exception as exc:
            if show_progress:
                print(f"  ⚠️ страница {page}/{max_page}: {exc}", flush=True)
            continue
        for entry in _parse_list_page(html, list_url):
            inn = entry["inn"]
            uuid = entry.get("uuid")
            if uuid:
                inn_uuids.setdefault(inn, set()).add(uuid)
            org = by_inn.setdefault(inn, _empty_org(inn))
            membership = {
                **entry,
                "sro_id": sro_id,
                "sro_name": source["name"],
                "title": entry.get("short_name"),
            }
            if len(inn_uuids.get(inn, set())) > 1:
                membership["duplicated"] = True
            merged = _prefer_membership(org["memberships"].get(sro_id), membership)
            if len(inn_uuids.get(inn, set())) > 1:
                merged["duplicated"] = True
            org["memberships"][sro_id] = merged
            if not org.get("title"):
                org["title"] = entry.get("short_name")
            added += 1
        if show_progress:
            print(f"  📄 {page}/{max_page}", flush=True)
    return added


def sync_all_sro_list_only(
    show_progress: bool = True,
    sro_ids: list[str] | None = None,
    merge_existing: bool = True,
) -> dict:
    ids = sro_ids or list(SRO_SOURCES.keys())
    by_inn: dict[str, dict] = load_reestr_cache() if merge_existing else {}
    if show_progress:
        print(f"⏳ Загружаю списки реестров ({len(ids)} СРО)...", flush=True)
    for sro_id in ids:
        try:
            sync_one_sro_list(sro_id, by_inn, show_progress=show_progress)
        except Exception as exc:
            print(f"  ❌ {sro_id}: {exc}", flush=True)
    _save_cache(by_inn, show_progress=show_progress)
    return {"count": len(by_inn), "organizations": by_inn}


def sync_all_sro_full(
    show_progress: bool = True,
    sro_ids: list[str] | None = None,
    merge_existing: bool = True,
) -> dict:
    result = sync_all_sro_list_only(
        show_progress=show_progress,
        sro_ids=sro_ids,
        merge_existing=merge_existing,
    )
    by_inn = result["organizations"]

    tasks = []
    for org in by_inn.values():
        for membership in org.get("memberships", {}).values():
            if membership.get("url") and not membership.get("inspections_by_year"):
                tasks.append(membership)

    if show_progress:
        print(f"\n⏳ Загружаю карточки: {len(tasks)} шт.", flush=True)

    completed = 0
    with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as executor:
        futures = {executor.submit(_fetch_detail, m): m for m in tasks}
        for future in as_completed(futures):
            membership = futures[future]
            try:
                enriched = future.result()
                inn = membership["inn"]
                sro_id = membership["sro_id"]
                by_inn[inn]["memberships"][sro_id] = enriched
            except Exception as exc:
                membership["sync_error"] = str(exc)
            completed += 1
            if completed % 200 == 0:
                _save_cache(by_inn)
            if show_progress and completed % 200 == 0:
                print(f"  ✅ {completed}/{len(tasks)}", flush=True)

    _save_cache(by_inn, show_progress=show_progress)
    return {"count": len(by_inn), "organizations": by_inn}


def sync_all_sro_refresh_inspections(
    show_progress: bool = True,
    sro_ids: list[str] | None = None,
    members_only: bool = True,
) -> dict:
    """Повторно качает карточки и обновляет проверки/дисциплину (даже если уже в кэше).

    По умолчанию только статус «Член СРО» — чтобы ночной прогон укладывался во время.
    """
    by_inn = load_reestr_cache()
    allowed = set(sro_ids) if sro_ids else None
    tasks: list[dict] = []
    for org in by_inn.values():
        for membership in org.get("memberships", {}).values():
            if not membership.get("url"):
                continue
            if allowed is not None and membership.get("sro_id") not in allowed:
                continue
            status = (membership.get("status") or "").strip()
            if members_only and status != "Член СРО":
                continue
            tasks.append(membership)

    if show_progress:
        scope = "члены СРО" if members_only else "все с URL"
        print(
            f"\n⏳ Обновляю карточки ({scope}): {len(tasks)} шт.",
            flush=True,
        )

    completed = 0
    errors = 0
    with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as executor:
        futures = {executor.submit(_fetch_detail, m): m for m in tasks}
        for future in as_completed(futures):
            membership = futures[future]
            try:
                enriched = future.result()
                inn = membership["inn"]
                sro_id = membership["sro_id"]
                by_inn[inn]["memberships"][sro_id] = enriched
            except Exception as exc:
                membership["sync_error"] = str(exc)
                errors += 1
            completed += 1
            if completed % 200 == 0:
                _save_cache(by_inn)
            if show_progress and completed % 200 == 0:
                print(f"  ✅ {completed}/{len(tasks)} (ошибок: {errors})", flush=True)

    _save_cache(by_inn, show_progress=show_progress)
    if show_progress:
        print(
            f"Готово refresh-inspections: {completed} карточек, ошибок: {errors}",
            flush=True,
        )
    return {
        "count": len(by_inn),
        "refreshed": completed,
        "errors": errors,
        "organizations": by_inn,
    }


def sync_all_sro_daily(
    show_progress: bool = True,
    sro_ids: list[str] | None = None,
) -> dict:
    """Ночной режим: list-only (статусы) + refresh карточек членов СРО."""
    if show_progress:
        print("=== DAILY: list-only ===", flush=True)
    list_res = sync_all_sro_list_only(
        show_progress=show_progress,
        sro_ids=sro_ids,
        merge_existing=True,
    )
    if show_progress:
        print("=== DAILY: refresh-inspections (Член СРО) ===", flush=True)
    refresh_res = sync_all_sro_refresh_inspections(
        show_progress=show_progress,
        sro_ids=sro_ids,
        members_only=True,
    )
    return {
        "count": refresh_res.get("count") or list_res.get("count"),
        "refreshed": refresh_res.get("refreshed", 0),
        "errors": refresh_res.get("errors", 0),
    }


def load_reestr_cache() -> dict[str, dict]:
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, encoding="utf-8") as file:
            payload = json.load(file)
        raw = payload.get("organizations", {})
        return {inn: _migrate_org_entry(inn, entry) for inn, entry in raw.items()}
    except Exception:
        return {}


def get_org_memberships(reestr_data: dict | None) -> dict[str, dict]:
    if not reestr_data:
        return {}
    return reestr_data.get("memberships") or {}


def enrich_reestr_entry(inn: str, cache: dict[str, dict], timeout: float = 20.0) -> dict | None:
    org = cache.get(inn)
    if not org:
        return org

    tasks = [
        (sro_id, membership)
        for sro_id, membership in org.get("memberships", {}).items()
        if membership_needs_detail_fetch(membership)
    ]
    if not tasks:
        return org

    changed = False
    workers = min(4, len(tasks))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(fetch_reestr_detail, membership): sro_id
            for sro_id, membership in tasks
        }
        for future in as_completed(futures, timeout=timeout):
            sro_id = futures[future]
            try:
                org["memberships"][sro_id] = future.result()
                changed = True
            except Exception:
                pass

    if changed:
        cache[inn] = org
    return org


# --- обратная совместимость ---
def sync_reestr(show_progress: bool = True) -> dict:
    return sync_all_sro_full(show_progress=show_progress, sro_ids=["OGPS"])


def sync_reestr_list_only(show_progress: bool = True) -> dict:
    return sync_all_sro_list_only(show_progress=show_progress, sro_ids=["OGPS"])


def _normalize_display_name(name: str, inn: str) -> str:
    if inn == "5018154265":
        return "ООО «ГТК»"
    display_name = (name or "").strip()
    if any(x in display_name.lower() for x in ("г.москва", "г. москва", "ул.", "дом ", "индекс")):
        if "," in display_name:
            parts = display_name.split(",")
            first_part = parts[0].strip()
            display_name = parts[1].strip() if first_part.isdigit() and len(parts) > 1 else first_part
    if display_name.lower() in {"г.москва", "г. москва", "москва"} or display_name.isdigit() or len(display_name) < 3:
        return f"Компания (ИНН: {inn})"
    return display_name


def _inspection_icon(result: str) -> str:
    return "✅" if "не выявлено" in result.lower() else "⚠️"


def _format_plan_month(month_raw: str) -> str:
    if not month_raw or month_raw == "Не указан":
        return "не указан"
    part = month_raw.strip()
    if re.search(r"\d{4}", part):
        return part
    return f"{part} {PLAN_YEAR}"


def _parse_plany_sro_map(plany_data: dict) -> dict[str, str]:
    if plany_data.get("plans"):
        return plany_data["plans"]
    sro_raw = plany_data.get("sro_type", "")
    month_raw = plany_data.get("month", "")
    sro_parts = [p.strip() for p in sro_raw.split(",") if p.strip()]
    month_parts = [p.strip() for p in month_raw.split(",") if p.strip()]
    result = {}
    for idx, sro_part in enumerate(sro_parts):
        key = PLANY_FILE_TO_SRO.get(sro_part.upper(), sro_part.upper())
        month = month_parts[idx] if idx < len(month_parts) else (month_parts[0] if month_parts else "Не указан")
        result[key] = month
    return result


def format_company_card(inn: str, plany_data: dict | None, reestr_data: dict | None) -> str:
    plany_data = plany_data or {}
    reestr_data = reestr_data or {}
    plany_plans = _parse_plany_sro_map(plany_data)
    reestr_memberships = get_org_memberships(reestr_data)

    display_name = (
        reestr_data.get("title")
        or plany_data.get("name")
        or next((m.get("title") or m.get("short_name") for m in reestr_memberships.values()), None)
        or f"Компания (ИНН: {inn})"
    )
    display_name = _normalize_display_name(display_name, inn)

    all_sro_ids = list(dict.fromkeys(list(plany_plans.keys()) + list(reestr_memberships.keys())))

    lines = [f"✅ {display_name}", ""]

    if not all_sro_ids:
        lines.extend(["📦 СРО: —", "📋 Статус: —", "📅 В реестре с: —", "🔍 Плановая проверка: —"])
    else:
        lines.append("📦 Членство в СРО:")
        for sro_id in all_sro_ids:
            mem = reestr_memberships.get(sro_id, {})
            sro_name = mem.get("sro_name") or sro_display_name(sro_id)
            status = mem.get("status") or "—"
            reg_date = mem.get("reg_date") or "—"
            plan = _format_plan_month(plany_plans.get(sro_id, "не указан"))
            lines.append(f"\n<b>{sro_name}</b>")
            lines.append(f"  📋 {status} | 📅 с {reg_date}")
            vv_line = _format_kf_level_line(
                mem.get("kf_level_vv"),
                _format_kf_money(mem.get("kf_sum_vv")),
                label="КФ ВВ",
            )
            odo_line = _format_kf_level_line(
                mem.get("kf_level_odo"),
                _format_kf_money(mem.get("kf_sum_odo")),
                label="КФ ОДО",
            )
            if vv_line:
                lines.append(vv_line)
            if odo_line:
                lines.append(odo_line)
            lines.append(f"  🔍 Плановая проверка: {plan}")
            latest_disciplinary = mem.get("latest_disciplinary")
            if latest_disciplinary:
                lines.append(f"  ⚠️ Дисциплина: {_format_discipline_line(latest_disciplinary)}")
            inspections = mem.get("inspections_by_year") or {}
            recent_years = _recent_inspection_years()
            shown_years = sorted((year for year in inspections if year in recent_years), key=int)
            if shown_years:
                lines.append("  📊 Проверки (последние 3 года):")
                for year in shown_years:
                    result = inspections[year]
                    lines.append(f"    {year} — {_inspection_icon(result)} {result}")
            url = mem.get("url")
            if url:
                lines.append(f"  🔗 {url}")

    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Синхронизация реестров СРО")
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Только списки (статус/даты), без карточек",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Списки + карточки только где ещё нет inspections_by_year",
    )
    parser.add_argument(
        "--refresh-inspections",
        action="store_true",
        help="Повторно скачать карточки «Член СРО» (обновить проверки/дисциплину)",
    )
    parser.add_argument(
        "--daily",
        action="store_true",
        help="Ночной режим: list-only + refresh-inspections",
    )
    parser.add_argument(
        "--all-statuses",
        action="store_true",
        help="С --refresh-inspections: все статусы, не только «Член СРО»",
    )
    args = parser.parse_args()

    if args.daily:
        sync_all_sro_daily(show_progress=True)
    elif args.refresh_inspections:
        sync_all_sro_refresh_inspections(
            show_progress=True,
            members_only=not args.all_statuses,
        )
    elif args.full:
        sync_all_sro_full(show_progress=True)
    else:
        # по умолчанию и при --list-only
        sync_all_sro_list_only(show_progress=True)
