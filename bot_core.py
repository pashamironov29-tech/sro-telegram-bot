# -*- coding: utf-8 -*-
"""Общее ядро режимов и гейтов для Telegram и MAX.

Оболочки (bot_FINAL_GOLD / bot_MAX) рисуют клавиатуры и шлют сообщения.
Смена режимов — только здесь, чтобы TG и MAX
не разъезжались снова.
"""

from __future__ import annotations

from local_answers import (
    enter_faq_mode,
    enter_search_mode,
    exit_faq_mode,
    exit_search_mode,
    is_faq_mode,
    is_search_mode,
)
from national_reestr import enter_national_mode, exit_national_mode, is_national_mode
from nrs_search_links import enter_nrs_link_mode, exit_nrs_link_mode, is_nrs_link_mode
from specialist_reestr import (
    enter_specialist_mode,
    exit_specialist_mode,
    is_specialist_mode,
)


def clear_chat_modes(
    chat_id: int,
    *,
    faq: bool = True,
    search: bool = True,
    nrs: bool = True,
    specialist: bool = True,
    national: bool = True,
) -> None:
    """Сбросить выбранные режимы."""
    if faq:
        exit_faq_mode(chat_id)
    if search:
        exit_search_mode(chat_id)
    if nrs:
        exit_nrs_link_mode(chat_id)
    if specialist:
        exit_specialist_mode(chat_id)
    if national:
        exit_national_mode(chat_id)


def prepare_welcome_reset(chat_id: int) -> None:
    """ /start — полный сброс режимов."""
    clear_chat_modes(chat_id)


def prepare_main_menu(chat_id: int) -> None:
    """«Назад в меню» — выйти из поиска и НРС."""
    clear_chat_modes(chat_id)


def prepare_faq(chat_id: int) -> None:
    """Полезная информация / FAQ."""
    clear_chat_modes(
        chat_id,
        faq=False,
        search=True,
        nrs=True,
    )
    enter_faq_mode(chat_id)


def prepare_search(chat_id: int) -> None:
    clear_chat_modes(
        chat_id,
        faq=True,
        search=False,
        nrs=True,
    )
    enter_search_mode(chat_id)


def prepare_nrs(chat_id: int) -> None:
    clear_chat_modes(
        chat_id,
        faq=True,
        search=True,
        nrs=False,
        specialist=True,
    )
    enter_nrs_link_mode(chat_id)


def prepare_specialist(chat_id: int) -> None:
    """Поиск специалиста по ФИО в локальной базе реестров."""
    clear_chat_modes(
        chat_id,
        faq=True,
        search=True,
        nrs=True,
        specialist=False,
    )
    enter_specialist_mode(chat_id)


def prepare_national(chat_id: int) -> None:
    """Поиск организации во всех СРО НОСТРОЙ и НОПРИЗ."""
    clear_chat_modes(
        chat_id,
        faq=True,
        search=True,
        nrs=True,
        specialist=True,
        national=False,
    )
    enter_national_mode(chat_id)


def active_input_mode(chat_id: int) -> str:
    """Какой режим ждёт текст пользователя.

    Приоритет: search → national → specialist → nrs → faq → none.
    Нормально prepare_* держит режимы взаимоисключающими.
    """
    if is_search_mode(chat_id):
        return "search"
    if is_national_mode(chat_id):
        return "national"
    if is_specialist_mode(chat_id):
        return "specialist"
    if is_nrs_link_mode(chat_id):
        return "nrs"
    if is_faq_mode(chat_id):
        return "faq"
    return "none"
