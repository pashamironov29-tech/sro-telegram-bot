"""Контакты партнёрских СРО (блок «Связаться с нами» с сайтов).

Запросы: «номер осот», «связь с огпо», «телефон гпс», «контакты мотс».
"""

from __future__ import annotations

import re

from sro_profiles import site_base_for_sro
from reestr_sync import sro_display_name

# lines: список {"label": str|None, "value": str}
# label=None — номер без подписи (как у ОСОТ основной)
SRO_CONTACTS: dict[str, dict] = {
    "OGPS": {
        "lines": [
            {"label": "Многоканальный телефон", "value": "+7 (495) 775 81 11"},
            {"label": "Факс", "value": "+7 (495) 517 92 35"},
            {"label": "Телефон доверия", "value": "+7 (905) 757 66 99"},
        ],
        "email": "info@srogen.ru",
        "aliases": ["огпс", "ген", "srogen", "ассоциация ген"],
    },
    "MOTS": {
        "lines": [
            {"label": "Многоканальный телефон", "value": "+7 (495) 775 81 11"},
            {"label": None, "value": "+7 (978) 781 68 76"},
            {"label": None, "value": "+7 (978) 904 45 32"},
            {"label": "Факс", "value": "+7 (495) 517 92 35"},
            {"label": "Телефон доверия", "value": "+7 (905) 757 66 99"},
        ],
        "email": "info@sro-mots.ru",
        "aliases": ["мотс", "mots", "sro-mots"],
    },
    "OGPP": {
        "lines": [
            {"label": "Многоканальный телефон", "value": "+7 (495) 775 81 11"},
            {"label": "Факс", "value": "+7 (495) 517 92 35"},
            {"label": "Телефон доверия", "value": "+7 (905) 757 66 99"},
        ],
        "email": "info@srosp.ru",
        "aliases": ["огпп", "градстройпроект", "srosp"],
    },
    "OSO": {
        "lines": [
            {"label": "Многоканальный телефон", "value": "+7 (495) 775 81 11"},
            {"label": "Факс", "value": "+7 (495) 517 92 35"},
            {"label": "Телефон доверия", "value": "+7 (905) 757 66 99"},
        ],
        "email": "info@srooso.ru",
        "aliases": ["осо", "srooso"],
    },
    "SPROF": {
        "lines": [
            {"label": "Многоканальный телефон", "value": "+7 (495) 775 81 11"},
            {"label": "Телефон доверия", "value": "+7 (905) 757 66 99"},
        ],
        "email": "info@sprofproekt.ru",
        "aliases": ["спроф", "спрофпроект", "sprofproekt"],
    },
    "PRIIS": {
        "lines": [
            {"label": "Многоканальный телефон", "value": "+7 (495) 775 81 11"},
            {"label": "Телефон доверия", "value": "+7 (905) 757 66 99"},
        ],
        "email": "info@sro-priis.ru",
        "aliases": ["приис", "sro-priis"],
    },
    "OPP": {
        "lines": [
            {
                "label": "Многоканальный телефон",
                "value": "+7 (495) 775-8-111 (доб. 271)",
            },
        ],
        "email": "info@np-pspz.ru",
        "aliases": ["опп", "np-pspz"],
    },
    "NOSO": {
        "lines": [
            {"label": "Телефоны", "value": "+7 (831) 433-15-27"},
            {"label": None, "value": "+7 (831) 419-72-25"},
            {"label": "Многоканальный телефон", "value": "+7 (495) 775 81 11"},
            {"label": "Телефон доверия", "value": "+7 (910) 139 17 62"},
            {"label": None, "value": "+7 (905) 757 66 99"},
        ],
        "email": "info@sronoso.ru",
        "aliases": ["носо", "sronoso"],
    },
    "OSOES": {
        "lines": [
            {"label": "Многоканальный телефон", "value": "+7 (343) 385 85 27"},
            {"label": "Многоканальный телефон", "value": "+7 (495) 775 81 11"},
            {"label": "Факс", "value": "+7 (495) 517 92 35"},
            {"label": "Телефон доверия", "value": "+7 (905) 757 66 99"},
        ],
        "email": "info@assrtm.ru",
        "aliases": ["осоес", "assrtm"],
    },
    "OSOT": {
        "lines": [
            {"label": None, "value": "+7 (843) 562-02-44"},
            {"label": "Многоканальный телефон", "value": "+7 (495) 775 81 11"},
            {"label": "Телефон доверия", "value": "+7 (905) 757 66 99"},
        ],
        "email": "info@nup-sro.ru",
        "aliases": ["осот", "nup-sro"],
    },
    "SOVS": {
        "lines": [
            {"label": "Многоканальный телефон", "value": "+7 (4112) 31-81-65"},
            {"label": None, "value": "+7 (4112) 31-81-95"},
        ],
        "email": "info@msro-sibir.ru",
        "aliases": ["осовс", "msro-sibir", "msro sibir"],
    },
    "OGPO": {
        "lines": [
            {"label": "Многоканальный телефон", "value": "+7 (495) 775 81 11"},
            {"label": "Телефон доверия", "value": "+7 (905) 757 66 99"},
        ],
        "email": "info@sroogpo.ru",
        "aliases": ["огпо", "sroogpo"],
    },
    "MGEO": {
        "lines": [
            {"label": "Многоканальный телефон", "value": "+7 (495) 775 81 11"},
            {"label": "Факс", "value": "+7 (495) 517 92 35"},
        ],
        "email": "info@sroigeo.ru",
        "aliases": ["мгео", "sroigeo", "гео изыскатели"],
    },
    "GEOIND": {
        "lines": [
            {"label": "Многоканальный телефон", "value": "+7 (495) 775 81 11"},
            {"label": "Факс", "value": "+7 (495) 517 92 35"},
            {"label": "Телефон доверия", "value": "+7 (905) 757 66 99"},
        ],
        "email": "info@srogeo.ru",
        "aliases": [
            "геоиндустрия",
            "гео индустрия",
            "srogeo",
            "геоиндустри",
        ],
    },
    "GPS": {
        "lines": [
            {"label": "Многоканальный телефон", "value": "+7 (495) 775 81 11"},
            {"label": "Факс", "value": "+7 (495) 517 92 35"},
            {"label": "Телефон доверия", "value": "+7 (905) 757 66 99"},
        ],
        "email": "info@sro-gps.ru",
        "aliases": ["гпс", "sro-gps", "генподрядчиков"],
    },
}

_CONTACT_INTENT = (
    "номер",
    "телефон",
    "телефона",
    "телефоны",
    "связь",
    "связаться",
    "контакт",
    "контакты",
    "позвонить",
    "звонить",
    "куда звонить",
    "почта",
    "email",
    "e-mail",
    "мейл",
    "эл. почта",
    "электронная почта",
)


def _normalize(text: str) -> str:
    text = (text or "").lower().replace("ё", "е")
    return re.sub(r"\s+", " ", text.strip())


def _has_contact_intent(normalized: str) -> bool:
    if any(p in normalized for p in _CONTACT_INTENT):
        return True
    # «номер осот» / «осот номер» без других слов тоже ок, если есть alias
    return False


def _alias_in_text(alias: str, normalized: str) -> bool:
    alias = _normalize(alias)
    if not alias:
        return False
    if " " in alias:
        return alias in normalized
    return bool(
        re.search(rf"(?<![a-zа-я0-9]){re.escape(alias)}(?![a-zа-я0-9])", normalized)
    )


def match_sro_contact_query(text: str) -> str | None:
    """
    Если запрос про контакты конкретного СРО — вернуть sro_id.
    Иначе None (пусть обрабатывают партнёры / ИИ).
    """
    normalized = _normalize(text)
    if not normalized or not _has_contact_intent(normalized):
        return None

    # Длинные алиасы первыми (осот / осоес / осовс раньше «осо»)
    ranked: list[tuple[int, str, str]] = []
    for sro_id, data in SRO_CONTACTS.items():
        for alias in data.get("aliases") or []:
            if _alias_in_text(alias, normalized):
                ranked.append((len(alias), sro_id, alias))
    if not ranked:
        # «номер ген» и т.п. — display name
        for sro_id in SRO_CONTACTS:
            name = _normalize(sro_display_name(sro_id))
            if name and _alias_in_text(name, normalized):
                ranked.append((len(name), sro_id, name))
    if not ranked:
        return None
    ranked.sort(key=lambda x: -x[0])
    return ranked[0][1]


def format_sro_contacts(sro_id: str, *, question: str | None = None) -> str | None:
    data = SRO_CONTACTS.get(sro_id)
    if not data:
        return None
    name = sro_display_name(sro_id)
    site = site_base_for_sro(sro_id).replace("https://", "").replace("http://", "")
    lines_out: list[str] = []
    if question:
        lines_out.append(f"🤖 По запросу «<b>{question}</b>»:\n")
    lines_out.append(f"📞 <b>Связаться с {name}</b>\n")

    for row in data.get("lines") or []:
        label = row.get("label")
        value = row.get("value") or ""
        if not value:
            continue
        if label:
            lines_out.append(f"{label}:")
        lines_out.append(f"<code>{value}</code>")
        lines_out.append("")

    email = data.get("email")
    if email:
        lines_out.append("E-mail:")
        lines_out.append(f"<code>{email}</code>")
        lines_out.append("")

    lines_out.append(f"🌐 Сайт: <code>{site}</code>")
    multi = "7758111"

    def _core(digits: str) -> str:
        return digits[-10:] if len(digits) >= 10 else digits

    digits_list = [
        re.sub(r"\D", "", row.get("value") or "")
        for row in (data.get("lines") or [])
    ]
    has_local = any(d and multi not in _core(d) for d in digits_list)
    if has_local:
        lines_out.append(
            "\n<i>Многоканальный 775-81-11 — общий для экосистемы. "
            "В региональный офис этого СРО звоните по местному номеру выше.</i>"
        )
    return "\n".join(lines_out).rstrip()
