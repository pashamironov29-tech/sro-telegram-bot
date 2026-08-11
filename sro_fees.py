# -*- coding: utf-8 -*-
"""Размеры взносов (КФ + членские) по СРО для кнопки FAQ.

Суммы членских — из Положений о членстве (апрель 2026), файлы в sro files/docs/.
КФ ВВ / КФ ОДО — минимальные по ГрК РФ (ст. 55.16); СРО может установить выше.
"""
from __future__ import annotations

import os
from pathlib import Path

from sro_profiles import SRO_ACTIVITY, get_sro_profile, site_base_for_sro
from reestr_sync import sro_display_name
from bot_disclaimers import FEES_UNVERIFIED_DISCLAIMER

# База docs рядом с бланками
try:
    from config_keys import SRO_FILES_DIR

    DOCS_DIR = Path(SRO_FILES_DIR) / "docs"
except Exception:
    DOCS_DIR = Path(__file__).resolve().parent / "sro files" / "docs"

# --- КФ по виду деятельности (мин. по ГрК) ---

KF_STROY = [
    ("1-й (до 90 млн)", "100 000"),
    ("2-й (до 500 млн)", "500 000"),
    ("3-й (до 3 млрд)", "1 500 000"),
    ("4-й (до 10 млрд)", "2 000 000"),
    ("5-й (свыше 10 млрд)", "5 000 000"),
    ("Простой (только снос)", "100 000"),
]

KF_PROEKT = [
    ("1-й (до 25 млн)", "50 000"),
    ("2-й (до 50 млн)", "150 000"),
    ("3-й (до 300 млн)", "500 000"),
    ("4-й (от 300 млн)", "1 000 000"),
]

# Изыскания — те же пороги, что у проектирования (ч. 10 ст. 55.16 ГрК)
KF_IZYSK = list(KF_PROEKT)

KF_ODO_HINT_STROY = (
    "🔹 <b>КФ ОДО</b> — если планируете участвовать в конкурсах/аукционах "
    "(отдельная таблица на сайте)."
)
KF_ODO_HINT_PROEKT = (
    "🔹 <b>КФ ОДО</b> — мин. <code>150 000</code> руб. при намерении заключать "
    "договоры конкурентным способом (см. Положение о КФ ОДО на сайте)."
)

# --- Членские ---

# ОГПС (Положение 10.04.2026)
MEMBER_OGPS = [
    ("1-й", "35 000"),
    ("2-й", "40 000"),
    ("3-й", "46 250"),
    ("4-й", "57 500"),
    ("5-й", "72 500"),
    ("Простой (только снос)", "35 000"),
]

# ОСО / МОТС (и близкие строительные по шаблону)
MEMBER_OSO = [
    ("1-й", "35 000"),
    ("2-й", "40 000"),
    ("3-й", "46 250"),
    ("4-й", "52 500"),
    ("5-й", "60 000"),
    ("Простой (только снос)", "35 000"),
]

# ОГПП — 4 уровня (проектирование)
MEMBER_OGPP = [
    ("1-й", "35 000"),
    ("2-й", "40 000"),
    ("3-й", "46 250"),
    ("4-й", "57 500"),
]

# СПРОФ / ПРИИС / МГЕО / ОГПО — фиксированный годовой
MEMBER_FLAT_120 = {"annual": "120 000", "quarter": "30 000"}

PAYMENT_RULES = (
    "⏱ <b>Срок оплаты:</b> не позднее 5 января / 5 апреля / 5 июля / 5 октября.\n"
    "🆕 <b>Первый платёж:</b> в течение 3 рабочих дней после приёма; "
    "за неполный квартал — пропорционально месяцу внесения в реестр.\n"
    "📅 Можно оплатить авансом за весь год."
)

PROMO_50_2026 = (
    "🎁 <b>Для вступающих в 2026:</b> регулярный членский взнос — "
    "<b>50%</b> от таблицы (протокол Правления / Совета, см. сайт)."
)

# sro_id -> конфиг
# member: "ogps" | "oso" | "ogpp" | "flat120"
# promo_50: скидка 50% для вступающих в 2026
# doc: имя файла в docs/ или None
# source: подпись источника
SRO_FEE_CONFIG: dict[str, dict] = {
    "OGPS": {
        "member": "ogps",
        "promo_50": False,
        "doc": "Pol_o_chelenstve_10042026_srogen_zam.doc",
        "source": "Положение о членстве ОГПС (10.04.2026), раздел 7",
    },
    "OGPP": {
        "member": "ogpp",
        "promo_50": True,
        "doc": "Pol_o_chelenstve_OGPP21042026.doc",
        "source": "Положение о членстве ОГПП (21.04.2026), раздел 7; акция 50% — протокол №266 от 22.12.2025",
    },
    "OSO": {
        "member": "oso",
        "promo_50": True,
        "doc": "Pol_o_chelenstve_15042026_oso.doc",
        "source": "Положение о членстве ОСО (15.04.2026), раздел 7",
    },
    "MOTS": {
        "member": "oso",
        "promo_50": True,
        "doc": "Pol_o_chelenstve_07042026_MOTS.doc",
        "source": "Положение о членстве МОТС (07.04.2026), раздел 7",
    },
    "OGPO": {
        "member": "flat120",
        "promo_50": True,
        "doc": "Pol_o_chelenstve_OGPO21042026.doc",
        "source": "Положение о членстве ОГПО (21.04.2026), п. 7.9–7.10",
    },
    "SPROF": {
        "member": "flat120",
        "promo_50": True,
        "doc": "Pol_o_chelenstve_sprof_22042026.doc",
        "source": "Положение о членстве СПРОФ (22.04.2026), п. 7.9–7.10",
    },
    "PRIIS": {
        "member": "flat120",
        "promo_50": True,
        "doc": "Pol_o_chelenstve_PRIIS_23042026.doc",
        "source": "Положение о членстве ПРИИС (23.04.2026), п. 7.9–7.10",
    },
    "MGEO": {
        "member": "flat120",
        "promo_50": True,
        "doc": "Pol_o_chelenstve_MGEO_23042026.doc",
        "source": "Положение о членстве МГЕО (23.04.2026), п. 7.9–7.10",
    },
}

# Непроверенные строительные — шаблон ОСО + дисклеймер
# Непроверенные проект/изыск — flat120 + дисклеймер
DEFAULT_STROY = {
    "member": "oso",
    "promo_50": True,
    "doc": None,
    "source": "типовые суммы по Положению о членстве партнёрских СРО; уточните на сайте своего СРО",
    "unverified": True,
}
DEFAULT_PROEKT = {
    "member": "flat120",
    "promo_50": True,
    "doc": None,
    "source": "типовые суммы по Положению о членстве партнёрских СРО; уточните на сайте своего СРО",
    "unverified": True,
}


def _cfg(sro_id: str) -> dict:
    if sro_id in SRO_FEE_CONFIG:
        return dict(SRO_FEE_CONFIG[sro_id])
    activity = SRO_ACTIVITY.get(sro_id, "stroy")
    if activity == "stroy":
        return dict(DEFAULT_STROY)
    return dict(DEFAULT_PROEKT)


def _kf_rows(activity: str) -> list[tuple[str, str]]:
    if activity == "stroy":
        return KF_STROY
    if activity == "izysk":
        return KF_IZYSK
    return KF_PROEKT


def _member_rows(kind: str) -> list[tuple[str, str]] | None:
    if kind == "ogps":
        return MEMBER_OGPS
    if kind == "oso":
        return MEMBER_OSO
    if kind == "ogpp":
        return MEMBER_OGPP
    return None


def fees_doc_path(sro_id: str) -> str | None:
    cfg = _cfg(sro_id)
    name = cfg.get("doc")
    if not name:
        return None
    path = DOCS_DIR / name
    return str(path) if path.is_file() else None


def format_fees_short_message(sro_id: str | None) -> str:
    """Короткий ответ на «членские взносы» / «размеры взносов»."""
    sro_id = sro_id or "OGPS"
    profile = get_sro_profile(sro_id) or {}
    name = profile.get("name") or sro_display_name(sro_id)
    cfg = _cfg(sro_id)
    kind = cfg.get("member")

    lines: list[str] = [f"💰 <b>Членские взносы ({name})</b>", ""]
    if kind == "flat120":
        flat = MEMBER_FLAT_120
        lines.append(
            f"• За год — <code>{flat['annual']}</code> руб. "
            f"(поквартально <code>{flat['quarter']}</code> руб.)"
        )
    else:
        rows = _member_rows(kind or "oso") or MEMBER_OSO
        lines.append("Зависят от уровня ответственности (ежеквартально):")
        for label, amount in rows:
            lines.append(f"• {label} — <code>{amount}</code> руб./квартал")

    lines.append("")
    lines.append(
        "⏱ Оплата: не позднее 5 января / 5 апреля / 5 июля / 5 октября."
    )
    if cfg.get("promo_50"):
        lines.append("🎁 Для вступающих в 2026 — часто <b>50%</b> (уточните на сайте).")
    if cfg.get("unverified"):
        lines.append(FEES_UNVERIFIED_DISCLAIMER)
    lines.append("")
    lines.append(
        "Полная таблица (КФ + членские) — кнопка "
        "<b>💰 Размеры взносов (КФ)</b> в FAQ."
    )
    return "\n".join(lines)


def format_fees_message(sro_id: str | None) -> str:
    sro_id = sro_id or "OGPS"
    profile = get_sro_profile(sro_id) or {}
    name = profile.get("name") or sro_display_name(sro_id)
    activity = profile.get("activity") or SRO_ACTIVITY.get(sro_id, "stroy")
    cfg = _cfg(sro_id)
    site = (profile.get("site") or site_base_for_sro(sro_id)).rstrip("/")

    lines: list[str] = [f"💰 <b>Взносы: КФ и членские ({name})</b>", ""]
    if cfg.get("unverified"):
        lines.append(f"{FEES_UNVERIFIED_DISCLAIMER}\n")

    lines.append("📌 <b>1. Разово при вступлении</b>")
    lines.append("")
    lines.append("🔹 <b>Компенсационный фонд возмещения вреда (КФ ВВ)</b>")
    lines.append("зависит от уровня ответственности:")
    lines.append("")
    for label, amount in _kf_rows(activity):
        lines.append(f"• {label} — <code>{amount}</code> руб.")
    lines.append("")
    if activity == "stroy":
        lines.append(KF_ODO_HINT_STROY)
    else:
        lines.append(KF_ODO_HINT_PROEKT)
    lines.append("🔹 <b>Вступительный взнос</b> — <code>0</code> руб.")
    lines.append("")

    lines.append("📌 <b>2. Членский взнос (не компфонд)</b>")
    kind = cfg.get("member")
    if kind == "flat120":
        flat = MEMBER_FLAT_120
        lines.append(
            f"• <b>За год</b> — <code>{flat['annual']}</code> руб. "
            f"(ежеквартально по <code>{flat['quarter']}</code> руб.)"
        )
    else:
        rows = _member_rows(kind or "oso") or MEMBER_OSO
        lines.append("(те же уровни ответственности)")
        lines.append("")
        for label, amount in rows:
            lines.append(f"• {label} — <code>{amount}</code> руб./квартал")
    lines.append("")
    if cfg.get("promo_50"):
        lines.append(PROMO_50_2026)
        lines.append("")
    lines.append(PAYMENT_RULES)
    lines.append("")
    lines.append(f"📄 <b>Источник:</b> {cfg.get('source') or 'Положение о членстве'}.")
    if fees_doc_path(sro_id):
        lines.append(
            "📥 Нужен файл Положения о членстве (раздел о взносах)? "
            "Скачайте по кнопке ниже."
        )
    else:
        lines.append(
            f"Таблица и документы: {site}/vstuplenie/informacija/ "
            "(или раздел «Вступление» на сайте)."
        )
    lines.append("<i>Цифры можно скопировать в один клик.</i>")
    return "\n".join(lines)
