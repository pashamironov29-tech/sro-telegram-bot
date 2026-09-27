# -*- coding: utf-8 -*-
"""Общее ядро режимов и гейтов для Telegram и MAX.

Оболочки (bot_FINAL_GOLD / bot_MAX) рисуют клавиатуры и шлют сообщения.
Смена режимов и проверка прав контролёра — только здесь, чтобы TG и MAX
не разъезжались снова.
"""

from __future__ import annotations

from ai_assistant import (
    enter_ai_mode,
    enter_faq_mode,
    enter_search_mode,
    exit_ai_mode,
    exit_faq_mode,
    exit_search_mode,
    is_ai_mode,
    is_faq_mode,
    is_search_mode,
)
from controller_access import (
    enter_controller_work_mode,
    exit_controller_work_mode,
    is_controller,
)
from controller_ai import (
    enter_controller_ai_mode,
    exit_controller_ai_mode,
    is_controller_ai_mode,
)
from nrs_search_links import enter_nrs_link_mode, exit_nrs_link_mode, is_nrs_link_mode

try:
    from doc_qa import enter_doc_ask_mode, exit_doc_ask_mode
except ImportError:  # pragma: no cover
    def enter_doc_ask_mode(_chat_id: int) -> None:
        return None

    def exit_doc_ask_mode(_chat_id: int) -> None:
        return None

CONTROLLER_AI_DENIED = (
    "⛔ Режим «🎙 ИИ-помощник» — только сотрудникам контроля."
)


def clear_chat_modes(
    chat_id: int,
    *,
    ai: bool = True,
    faq: bool = True,
    search: bool = True,
    nrs: bool = True,
    doc_ask: bool = True,
    controller_ai: bool = True,
    controller_work: bool = False,
) -> None:
    """Сбросить выбранные режимы. controller_work по умолчанию не трогаем."""
    if ai:
        exit_ai_mode(chat_id)
    if faq:
        exit_faq_mode(chat_id)
    if search:
        exit_search_mode(chat_id)
    if nrs:
        exit_nrs_link_mode(chat_id)
    if doc_ask:
        exit_doc_ask_mode(chat_id)
    if controller_ai:
        exit_controller_ai_mode(chat_id)
    if controller_work:
        exit_controller_work_mode(chat_id)


def prepare_welcome_reset(chat_id: int) -> None:
    """ /start — полный сброс, включая кабинет контролёра."""
    clear_chat_modes(chat_id, controller_work=True)


def prepare_main_menu(chat_id: int) -> None:
    """«Назад в меню» — выйти из ИИ/поиска/НРС/🎙, кабинет контролёра оставить."""
    clear_chat_modes(chat_id, controller_work=False)


def prepare_controller_menu(chat_id: int) -> None:
    """Открыть кабинет /controller."""
    clear_chat_modes(chat_id, controller_work=False)
    enter_controller_work_mode(chat_id)


def prepare_controller_ai(chat_id: int) -> bool:
    """Включить 🎙. False — не контролёр (устаревший режим тоже сбрасывается)."""
    if not is_controller(chat_id):
        exit_controller_ai_mode(chat_id)
        return False
    clear_chat_modes(chat_id, controller_ai=False, controller_work=False)
    enter_controller_work_mode(chat_id)
    enter_controller_ai_mode(chat_id)
    return True


def prepare_ai_assistant(chat_id: int) -> None:
    """Обычный ИИ-помощник (не контролёрский)."""
    clear_chat_modes(
        chat_id,
        ai=False,
        faq=True,
        search=True,
        nrs=True,
        doc_ask=True,
        controller_ai=True,
        controller_work=False,
    )
    enter_ai_mode(chat_id)


def prepare_faq(chat_id: int) -> None:
    """Полезная информация / FAQ."""
    clear_chat_modes(
        chat_id,
        ai=True,
        faq=False,
        search=True,
        nrs=True,
        doc_ask=True,
        controller_ai=True,
        controller_work=False,
    )
    enter_faq_mode(chat_id)


def prepare_search(chat_id: int) -> None:
    clear_chat_modes(
        chat_id,
        ai=True,
        faq=True,
        search=False,
        nrs=True,
        doc_ask=True,
        controller_ai=True,
        controller_work=False,
    )
    enter_search_mode(chat_id)


def prepare_nrs(chat_id: int) -> None:
    clear_chat_modes(
        chat_id,
        ai=True,
        faq=True,
        search=True,
        nrs=False,
        doc_ask=True,
        controller_ai=True,
        controller_work=False,
    )
    enter_nrs_link_mode(chat_id)


def prepare_doc_qa(chat_id: int) -> None:
    clear_chat_modes(
        chat_id,
        ai=True,
        faq=True,
        search=True,
        nrs=True,
        doc_ask=False,
        controller_ai=True,
        controller_work=False,
    )
    enter_doc_ask_mode(chat_id)


def active_input_mode(chat_id: int) -> str:
    """Какой режим ждёт текст пользователя.

    Приоритет (страховка, если флаги пересеклись):
    controller_ai → search → ai → nrs → faq → none.
    Нормально prepare_* держит режимы взаимоисключающими.
    """
    if is_controller_ai_mode(chat_id):
        return "controller_ai"
    if is_search_mode(chat_id):
        return "search"
    if is_ai_mode(chat_id):
        return "ai"
    if is_nrs_link_mode(chat_id):
        return "nrs"
    if is_faq_mode(chat_id):
        return "faq"
    return "none"


def gate_controller_ai_text(chat_id: int) -> str:
    """Маршрутизация текста в режиме 🎙: pass | deny | skip."""
    if not is_controller_ai_mode(chat_id):
        return "skip"
    if not is_controller(chat_id):
        exit_controller_ai_mode(chat_id)
        return "deny"
    return "pass"


def gate_controller_ai_media(chat_id: int) -> str:
    """Вложение в 🎙: pass | deny | need_mode | skip.

    need_mode — контролёр в кабинете, но не открыл 🎙.
    """
    if not is_controller(chat_id):
        exit_controller_ai_mode(chat_id)
        return "deny"
    if is_controller_ai_mode(chat_id):
        return "pass"
    from controller_access import is_controller_work_mode

    if is_controller_work_mode(chat_id):
        return "need_mode"
    return "skip"
