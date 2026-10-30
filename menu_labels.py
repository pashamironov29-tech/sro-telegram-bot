"""Подписи 4 кнопок главного меню — общие для Telegram и MAX.

Старые подписи оставлены как алиасы: у пользователей может висеть старая
клавиатура или старое сообщение с кнопками.
"""

from __future__ import annotations

SEARCH_ORG_BUTTON = "🔎 Поиск организации в СРО / Checko"
CHECKO_CARD_BUTTON = "📋 Проверить в Checko"  # под карточкой организации, не в главном меню
NRS_LINK_BUTTON = "✅ Проверить НРС (НОСТРОЙ / НОПРИЗ)"
SPECIALIST_BUTTON = "👤 Где работает специалист (по ФИО) — с сайта НОСТРОЙ/НОПРИЗ"
NATIONAL_BUTTON = "🏢 Поиск организации в НОСТРОЙ / НОПРИЗ"

MENU_LABELS = (SEARCH_ORG_BUTTON, NRS_LINK_BUTTON, SPECIALIST_BUTTON, NATIONAL_BUTTON)

LEGACY_MENU_ALIASES = {
    "🔍 Поиск организации": SEARCH_ORG_BUTTON,
    "🔎 Поиск организации в СРО": SEARCH_ORG_BUTTON,  # подпись 1.14.8–1.14.9
    "👤 Проверить в НРС": NRS_LINK_BUTTON,
    "👤 НРС ссылка (пилот)": NRS_LINK_BUTTON,
    "👤 Где работает специалист (по ФИО)": SPECIALIST_BUTTON,  # подпись 1.14.8–1.14.10
    "🔎 Поиск специалиста по ФИО": SPECIALIST_BUTTON,
    "🏛 Поиск в НОСТРОЙ / НОПРИЗ": NATIONAL_BUTTON,
}


def normalize_menu_label(text: str) -> str:
    """Старая подпись кнопки меню -> новая. Остальной текст без изменений."""
    return LEGACY_MENU_ALIASES.get(text, text)
