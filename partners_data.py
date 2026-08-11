"""Партнёры и национальные объединения СРО «ГЕН» — сайты и поиск по запросу."""

import re

from bot_disclaimers import OFFICIAL_SOURCE_DISCLAIMER

PARTNERS_PAGE_URL = "https://www.srogen.ru/kontakty/partnery/"

PARTNER_SRO = [
    {"name": "МОТС", "url": "https://www.sro-mots.ru/", "aliases": ["мотс", "mots", "sro-mots", "sro mots"]},
    {"name": "ГрадСтройПроект", "url": "https://www.srosp.ru/", "aliases": ["градстройпроект", "srosp", "огпс"]},
    {"name": "ОСО", "url": "https://www.srooso.ru/", "aliases": ["осо", "srooso"]},
    {"name": "Гео", "url": "https://www.srogeo.ru/", "aliases": ["srogeo", "гео сро"]},
    {"name": "НОСО", "url": "https://www.sronoso.ru/", "aliases": ["носо", "sronoso"]},
    {"name": "ОСОЕС", "url": "https://www.assrtm.ru/", "aliases": ["осоес", "assrtm"]},
    {"name": "ОСОВС", "url": "https://www.msro-sibir.ru/", "aliases": ["осовс", "msro-sibir"]},
    {"name": "ОСОТ", "url": "https://www.nup-sro.ru/", "aliases": ["осот", "nup-sro"]},
    {"name": "ОГПО", "url": "https://www.sroogpo.ru/", "aliases": ["огпо", "огпп", "sroogpo"]},
    {"name": "ГЕО", "url": "https://www.sroigeo.ru/", "aliases": ["sroigeo"]},
    {"name": "СПрофПроект", "url": "https://www.sprofproekt.ru/", "aliases": ["sprofproekt", "спрофпроект"]},
    {"name": "ПРИИС", "url": "https://www.sro-priis.ru/", "aliases": ["приис", "sro-priis"]},
    {"name": "ОПП", "url": "https://www.np-pspz.ru/", "aliases": ["опп", "np-pspz"]},
    {"name": "Генподрядчиков", "url": "https://www.sro-gps.ru/", "aliases": ["sro-gps", "генподрядчиков"]},
]

NATIONAL_UNIONS = [
    {
        "name": "НОСТРОЙ",
        "url": "https://www.nostroy.ru/",
        "phone": "+7 (495) 987-31-47",
        "email": "info@nostroy.ru",
        "aliases": ["нострой", "nostroy"],
    },
    {
        "name": "НОПРИЗ",
        "url": "https://www.nopriz.ru/",
        "phone": "+7 (495) 984-21-33",
        "email": "info@nopriz.ru",
        "aliases": ["ноприз", "nopriz"],
    },
]

EDUCATION_PARTNERS = [
    {"name": "ООО «МЦЭ»", "url": "https://www.omrce.ru/", "aliases": ["мцэ", "omrce"]},
    {"name": "АНО «ЦНЭ»", "url": "https://www.mcne.ru/", "aliases": ["цнэ", "mcne"]},
    {"name": "ОМОР «Российский Союз строителей»", "url": "https://www.omorrss.ru/", "aliases": ["омор", "omorrss", "российский союз строителей"]},
    {"name": "АНО ДПО «Учебный центр РСС»", "url": "https://www.dporss.ru/", "aliases": ["учебный центр рсс", "dporss", "центр рсс"]},
]

GENERAL_PARTNER_PHRASES = (
    "партнеры и но",
    "партнёры и но",
    "партнеры",
    "партнёры",
    "партнер и но",
    "партнёр и но",
    "национальные объединения",
    "партнерские сро",
    "партнёрские сро",
)


def _normalize(text: str) -> str:
    text = text.lower().replace("ё", "e")
    return re.sub(r"\s+", " ", text.strip())


def _host_label(url: str) -> str:
    return url.replace("https://", "").replace("http://", "").replace("www.", "")


def _web_link(url: str, label: str | None = None) -> str:
    return f'<a href="{url}">{label or _host_label(url)}</a>'


def _phone_link(phone: str) -> str:
    digits = re.sub(r"[^\d+]", "", phone)
    return f'<a href="tel:{digits}">{phone}</a>'


def _email_link(email: str) -> str:
    return f'<a href="mailto:{email}">{email}</a>'


def get_partners_full_text() -> str:
    lines = [
        "🤝 <b>Партнёры и национальные объединения</b>",
        "",
        "Ассоциация сотрудничает с <b>национальными объединениями (НО)</b>, "
        "<b>партнёрскими СРО</b>, а также организациями экспертизы "
        "и дополнительного профессионального образования.",
        "",
        "🏛 <b>Национальные объединения:</b>",
    ]
    for item in NATIONAL_UNIONS:
        lines.append(f"🔹 <b>{item['name']}</b> — {_web_link(item['url'])}")
        lines.append(
            f"📞 {_phone_link(item['phone'])}, 📧 {_email_link(item['email'])}"
        )

    lines.append("")
    lines.append("🏗 <b>Партнёрские СРО:</b>")
    for item in PARTNER_SRO:
        lines.append(f"🔹 <b>{item['name']}</b> — {_web_link(item['url'])}")

    lines.append("")
    lines.append("🔬 <b>Экспертиза и образование:</b>")
    for item in EDUCATION_PARTNERS:
        lines.append(f"🔹 {item['name']} — {_web_link(item['url'])}")

    lines.append("")
    lines.append("👇 Полный официальный перечень партнёров — на сайте Ассоциации по кнопке ниже.")
    return "\n".join(lines)


def _alias_in_text(alias: str, normalized: str) -> bool:
    alias = alias.strip().lower()
    if not alias:
        return False
    if " " in alias:
        return alias in normalized
    return bool(
        re.search(rf"(?<![a-zа-я0-9]){re.escape(alias)}(?![a-zа-я0-9])", normalized)
    )


def match_partner_query(text: str):
    normalized = _normalize(text)
    if not normalized:
        return None

    # Контакты СРО («номер осот») — отдельный модуль sro_contacts
    try:
        from sro_contacts import match_sro_contact_query

        if match_sro_contact_query(text):
            return None
    except Exception:
        pass

    if any(w in normalized for w in ("реестр", "nrs.", "nrs ", " нрс", "специалист")):
        return None

    if any(
        w in normalized
        for w in (
            "взнос",
            "компенсацион",
            "членск",
            "кф вв",
            "кф одо",
            "таблица взнос",
            "размер взнос",
            "уровень ответственности",
        )
    ):
        return None

    for phrase in GENERAL_PARTNER_PHRASES:
        if phrase in normalized or normalized == phrase.rstrip("ы").rstrip("и"):
            return {"type": "all"}

    if normalized in ("партнер", "партнёр", "партнеры", "партнёры"):
        return {"type": "all"}

    all_items = []
    for group in (PARTNER_SRO, NATIONAL_UNIONS, EDUCATION_PARTNERS):
        all_items.extend(group)

    best = None
    best_len = 0
    for item in all_items:
        for alias in item["aliases"]:
            if _alias_in_text(alias, normalized) and len(alias) > best_len:
                best = item
                best_len = len(alias)

    if best:
        return {"type": "one", "item": best}
    return None


def format_partner_response(question: str, match: dict) -> dict:
    if match["type"] == "all":
        return {
            "ok": True,
            "text": (
                f"🤖 По вашему вопросу «<b>{question}</b>»:\n\n"
                f"{get_partners_full_text()}"
            ),
        }

    item = match["item"]
    extra = ""
    if item.get("phone"):
        extra = (
            f"\n📞 {_phone_link(item['phone'])}, "
            f"📧 {_email_link(item['email'])}"
        )

    return {
        "ok": True,
        "text": (
            f"🤖 По вашему вопросу «<b>{question}</b>»:\n\n"
            f"💡 <b>Кратко:</b> <b>{item['name']}</b> — партнёр Ассоциации, "
            f"сайт: {_web_link(item['url'])}{extra}\n\n"
            f"📄 Полный список партнёров и НО:\n"
            f"🔗 {_web_link(PARTNERS_PAGE_URL)}\n\n"
            f"{OFFICIAL_SOURCE_DISCLAIMER}"
        ),
    }
