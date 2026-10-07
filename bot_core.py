# -*- coding: utf-8 -*-
"""Общее ядро режимов и гейтов для Telegram и MAX.

Оболочки (bot_FINAL_GOLD / bot_MAX) рисуют клавиатуры и шлют сообщения.
Смена режимов и проверка прав контролёра — только здесь, чтобы TG и MAX
не разъезжались снова.
"""

from __future__ import annotations

from controller_access import exit_controller_work_mode, enter_controller_work_mode
from local_answers import (
    enter_faq_mode,
    enter_search_mode,
    exit_faq_mode,
    exit_search_mode,
    is_faq_mode,
    is_search_mode,
)
from nrs_search_links import enter_nrs_link_mode, exit_nrs_link_mode, is_nrs_link_mode


def clear_chat_modes(
    chat_id: int,
    *,
    faq: bool = True,
    search: bool = True,
    nrs: bool = True,
    controller_work: bool = False,
) -> None:
    """Сбросить выбранные режимы. controller_work по умолчанию не трогаем."""
    if faq:
        exit_faq_mode(chat_id)
    if search:
        exit_search_mode(chat_id)
    if nrs:
        exit_nrs_link_mode(chat_id)
    if controller_work:
        exit_controller_work_mode(chat_id)


def prepare_welcome_reset(chat_id: int) -> None:
    """ /start — полный сброс, включая кабинет контролёра."""
    clear_chat_modes(chat_id, controller_work=True)


def prepare_main_menu(chat_id: int) -> None:
    """«Назад в меню» — выйти из поиска и НРС, кабинет контролёра оставить."""
    clear_chat_modes(chat_id, controller_work=False)


def prepare_controller_menu(chat_id: int) -> None:
    """Открыть кабинет /controller."""
    clear_chat_modes(chat_id, controller_work=False)
    enter_controller_work_mode(chat_id)


def prepare_faq(chat_id: int) -> None:
    """Полезная информация / FAQ."""
    clear_chat_modes(
        chat_id,
        faq=False,
        search=True,
        nrs=True,
        controller_work=False,
    )
    enter_faq_mode(chat_id)


def prepare_search(chat_id: int) -> None:
    clear_chat_modes(
        chat_id,
        faq=True,
        search=False,
        nrs=True,
        controller_work=False,
    )
    enter_search_mode(chat_id)


def prepare_nrs(chat_id: int) -> None:
    clear_chat_modes(
        chat_id,
        faq=True,
        search=True,
        nrs=False,
        controller_work=False,
    )
    enter_nrs_link_mode(chat_id)


def active_input_mode(chat_id: int) -> str:
    """Какой режим ждёт текст пользователя.

    Приоритет: search → nrs → faq → none.
    Нормально prepare_* держит режимы взаимоисключающими.
    """
    if is_search_mode(chat_id):
        return "search"
    if is_nrs_link_mode(chat_id):
        return "nrs"
    if is_faq_mode(chat_id):
        return "faq"
    return "none"
