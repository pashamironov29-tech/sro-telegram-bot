"""Бланки контроля: папки по СРО и имена файлов в `sro files/blanki/<SRO_ID>/`."""

from __future__ import annotations

import os

from reestr_sync import SRO_SOURCES, sro_display_name

# Все партнёрские СРО из реестра — у каждого свой комплект бланков
BLANKI_SRO_IDS: tuple[str, ...] = tuple(SRO_SOURCES.keys())
DEFAULT_BLANKI_SRO = "OGPS"

# Единые локальные имена в каждой папке (после sync_blanki_from_sites.py)
_STANDARD_FILES: dict[str, str] = {
    "info_list": "info_list.doc",
    "zayavlenie_izmeneniya": "zayavlenie_izmeneniya.docx",
    "zayavlenie_proverka": "zayavlenie_proverka.docx",
    "doverennost": "doverennost.doc",
    "svedeniya_spec": "svedeniya_spec.docx",
    "polozhenie_kontrol": "polozhenie_kontrol.doc",
    "uvedomlenie_odo": "uvedomlenie_odo.docx",
}

BLANKI_FILES: dict[str, dict[str, str]] = {
    sro_id: dict(_STANDARD_FILES) for sro_id in BLANKI_SRO_IDS
}

# Порядок и подписи для меню бота (ключ, префикс кнопки, HTML-подпись к файлу)
BLANKI_MENU_ITEMS: list[tuple[str, str, str]] = [
    (
        "info_list",
        "📄 1. Информационный лист",
        "📄 <b>Шаблон информационного листа.</b>",
    ),
    (
        "zayavlenie_izmeneniya",
        "📄 2. Заявление о внесении изменений",
        "📄 <b>Шаблон заявления о внесении изменений.</b>",
    ),
    (
        "zayavlenie_proverka",
        "📄 3. Заявление на проверку",
        "📄 <b>Шаблон заявления на плановую/внеплановую проверку.</b>",
    ),
    (
        "doverennost",
        "📄 4. Форма доверенности",
        "📄 <b>Шаблон официальной доверенности на представление интересов.</b>",
    ),
    (
        "svedeniya_spec",
        "📄 5. Сведения о специалистах",
        "📄 <b>Шаблон таблицы сведений о специалистах НРС.</b>",
    ),
    (
        "polozhenie_kontrol",
        "📄 6. Положения о контроле",
        "📄 <b>Правила и положения о контроле СРО Ассоциации.</b>",
    ),
    (
        "uvedomlenie_odo",
        "📄 7. Уведомление ОДО",
        "📄 <b>Форма уведомления о фактическом совокупном размере обязательств (ОДО).</b>",
    ),
]

_LEGACY_OGPS_NAMES = {
    "info_list": ("info_list.docx", "info_list.doc"),
    "zayavlenie_izmeneniya": ("zayavlenie_izmeneniya.docx",),
    "zayavlenie_proverka": ("zayavlenie_proverka.docx",),
    "doverennost": ("doverennost.docx", "doverennost.doc"),
    "svedeniya_spec": ("svedeniya_spec.docx",),
    "polozhenie_kontrol": ("polozhenie_kontrol.docx", "polozhenie_kontrol.doc"),
    "uvedomlenie_odo": ("uvedomlenie_odo.docx",),
}


def resolve_blanki_sro_id(sro_id: str | None) -> str:
    """Строго своё СРО; без подмены ОГПС/ОГПП."""
    if sro_id and sro_id in BLANKI_FILES:
        return sro_id
    return DEFAULT_BLANKI_SRO


def blanki_kit_description(member_sro_id: str | None) -> str:
    """Подпись: какое СРО на бланке."""
    sid = resolve_blanki_sro_id(member_sro_id)
    name = sro_display_name(sid)
    if member_sro_id and member_sro_id != sid:
        return f"{name} · выбрано: {sro_display_name(member_sro_id)}"
    return name


def blanki_dir_for_sro(sro_files_root: str, sro_id: str | None) -> str:
    sid = resolve_blanki_sro_id(sro_id)
    return os.path.join(sro_files_root, "blanki", sid)


def blanki_file_path(
    sro_files_root: str,
    sro_id: str | None,
    key: str,
    *,
    prefer_docx: bool = False,
) -> str | None:
    """
    Путь к бланку.
    Для информационного листа: по умолчанию отдаём исходный .doc (вёрстка сайта),
    .docx — только когда prefer_docx=True (автозаполнение python-docx).
    """
    sid = resolve_blanki_sro_id(sro_id)
    fname = BLANKI_FILES.get(sid, {}).get(key)
    if not fname:
        return None
    folders = [os.path.join(sro_files_root, "blanki", sid)]
    if sid == DEFAULT_BLANKI_SRO:
        folders.append(os.path.join(sro_files_root, "blanki"))
    candidates = [fname, *(_LEGACY_OGPS_NAMES.get(key, ()) if sid == DEFAULT_BLANKI_SRO else ())]
    if key == "info_list" and fname.lower().endswith(".doc"):
        docx_name = fname[:-4] + ".docx"
        if prefer_docx:
            candidates = [docx_name, *candidates]
        else:
            # Пустой бланк без ИНН: сначала оригинал .doc — иначе «улетает» таблица ИНН
            candidates = [fname, docx_name, *[c for c in candidates if c not in (fname, docx_name)]]
    seen: set[str] = set()
    for folder in folders:
        for name in candidates:
            if name in seen:
                continue
            seen.add(name)
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                return path
    return None


def blanki_source_label(sro_id: str | None) -> str:
    return blanki_kit_description(sro_id)
