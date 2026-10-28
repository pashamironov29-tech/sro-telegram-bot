"""Поиск организации по ИНН в MAX-оболочке (bot_MAX.py)."""

from __future__ import annotations

import pytest

import local_answers
import reestr_sync
import sro_context
from tests.support import (
    INN_ABSENT,
    INN_EXCLUDED,
    INN_IP,
    INN_MULTI,
    INN_SINGLE,
    TEST_UID,
    keyboard_buttons,
    read_fixture,
)

UID = TEST_UID
MAIN_PAYLOADS = ["menu:search", "menu:nrs", "menu:spec", "menu:nat"]
OLD_KEYBOARD_TEXTS = (
    "Другой ИНН / без ИНН",
    "Назад в меню",
    "Назад к выбору организации",
    "Сменить СРО",
    "Организация состоит в нескольких СРО",
)


def _keyboards(max_bot) -> list[list[str]]:
    """Payload'ы callback-кнопок по каждой клавиатуре, отправленной пользователю."""
    return [
        [p for kind, _t, p in keyboard_buttons(att) if kind == "callback"]
        for att in max_bot.attachments()
    ]


def _text(max_bot, value: str) -> None:
    max_bot.m.handle_text(UID, value, {})


def _open_search(max_bot) -> None:
    max_bot.m.handle_callback(UID, "menu:search", {})
    max_bot.clear()


@pytest.mark.parametrize("raw", [INN_SINGLE, "7700 000 001", "7700\u00a0000\u00a0001"])
def test_inn_found_shows_card(max_bot, raw):
    _text(max_bot, raw)

    blob = max_bot.blob()
    assert "✅ <b>ООО «Тестстрой»</b>" in blob
    assert "<b>ОГПС</b>" in blob
    assert "Член СРО" in blob
    assert "Контекст: <b>" in blob
    assert sro_context.get_user_sro_id(UID) == "OGPS"


def test_inn_found_in_search_mode_closes_search(max_bot):
    _open_search(max_bot)
    _text(max_bot, INN_SINGLE)

    assert "ООО «Тестстрой»" in max_bot.blob()
    assert not local_answers.is_search_mode(UID)


def test_inn_12_digits_found(max_bot):
    _text(max_bot, INN_IP)

    blob = max_bot.blob()
    assert "ИП Пробный П.П." in blob
    assert "<b>ОСО</b>" in blob


def test_excluded_member_status_in_card(max_bot):
    _text(max_bot, INN_EXCLUDED)

    assert "Исключен" in max_bot.blob()


def test_inn_not_found(max_bot):
    _text(max_bot, INN_ABSENT)

    blob = max_bot.blob()
    assert f"Организация с ИНН <code>{INN_ABSENT}</code>" in blob
    assert "не найдена в базе бота" in blob
    assert "✅" not in blob


def test_start_unknown_inn_is_ordinary_search(max_bot):
    """/start не включает ожидание ИНН: промах идёт обычным поиском, без «Пропустить»."""
    _text(max_bot, "/start")
    assert sro_context.is_awaiting_inn(UID) is False
    max_bot.clear()

    _text(max_bot, INN_ABSENT)

    blob = max_bot.blob()
    assert f"Организация с ИНН <code>{INN_ABSENT}</code>" in blob
    assert "не найдена в базе бота" in blob
    assert "menu:skip" not in max_bot.callback_payloads()


def test_inn_not_found_during_onboarding(max_bot):
    """Ожидание ИНН: неизвестный ИНН — просто 4 кнопки главного меню, без «Пропустить»."""
    sro_context.begin_await_inn(UID)
    _text(max_bot, INN_ABSENT)

    blob = max_bot.blob()
    assert "Организация не найдена в реестре" in blob
    assert "Пропустить" not in blob
    assert _keyboards(max_bot) == [MAIN_PAYLOADS]


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("12345678", id="8-цифр"),
        pytest.param("1234567890123", id="13-цифр"),
        pytest.param("77000O0001", id="буква-O"),
        pytest.param("7700-000-001", id="дефисы"),
    ],
)
def test_malformed_inn_is_not_treated_as_inn(max_bot, raw):
    assert not max_bot.m.looks_like_inn(raw)
    _open_search(max_bot)

    _text(max_bot, raw)

    blob = max_bot.blob()
    assert f"По запросу «<b>{raw}</b>» организация в базе не найдена" in blob
    assert "✅" not in blob


def test_too_short_query_in_search_asks_for_inn(max_bot):
    _open_search(max_bot)
    _text(max_bot, "123")

    assert "Введите <b>ИНН</b> (9–12 цифр)" in max_bot.blob()


def test_inn_callback_with_letters_rejected(max_bot):
    max_bot.m.handle_callback(UID, "inn:77ABC", {})

    assert "ИНН должен состоять из цифр" in max_bot.blob()


def test_inn_in_several_sro(max_bot):
    """Организация в двух СРО: карточка со всеми СРО и только главное меню, без выбора СРО."""
    _text(max_bot, INN_MULTI)

    blob = max_bot.blob()
    assert "<b>ОГПС</b>" in blob
    assert "<b>МОТС</b>" in blob
    for old in OLD_KEYBOARD_TEXTS:
        assert old not in blob
    assert _keyboards(max_bot)
    assert all(kb == MAIN_PAYLOADS for kb in _keyboards(max_bot))
    texts = [t for _k, t, _p in max_bot.buttons()]
    assert not any(t.startswith("📄 СРО — ") for t in texts)
    assert sro_context.pending_sro_ids(UID) is None
    assert sro_context.get_user_sro_id(UID) is None
    assert sro_context.get_user_context(UID)["inn"] == INN_MULTI


def test_multi_sro_faq_works_without_sro_choice(max_bot):
    _text(max_bot, INN_MULTI)
    max_bot.clear()

    max_bot.m.handle_callback(UID, "menu:info", {})
    max_bot.m.handle_callback(UID, "faq:root", {})

    blob = max_bot.blob()
    assert "Бланки — какого СРО" not in blob
    assert not any(p.startswith("sro:") for p in max_bot.callback_payloads())


def test_multi_sro_blanks_ask_sro_only_when_opened(max_bot):
    _text(max_bot, INN_MULTI)
    max_bot.clear()

    max_bot.m.handle_callback(UID, "info:docs", {})

    payloads = max_bot.callback_payloads()
    assert "sro:OGPS" in payloads
    assert "sro:MOTS" in payloads
    assert "Бланки — какого СРО" in max_bot.blob()


def test_multi_sro_blank_click_asks_then_sends(max_bot):
    _text(max_bot, INN_MULTI)
    max_bot.clear()

    max_bot.m.handle_callback(UID, "blank:info_list", {})
    assert "sro:MOTS:info_list" in max_bot.callback_payloads()
    assert sro_context.get_user_sro_id(UID) is None

    max_bot.clear()
    max_bot.m.handle_callback(UID, "sro:MOTS:info_list", {})
    assert sro_context.get_user_sro_id(UID) == "MOTS"
    assert sro_context.get_user_context(UID)["inn"] == INN_MULTI


def test_multi_sro_card_has_checko_button_for_everyone(max_bot, config_stub, monkeypatch):
    monkeypatch.setattr(config_stub, "CHECKO_API_KEY", "test-fake-checko-key")
    _text(max_bot, INN_MULTI)

    card_kb = _keyboards(max_bot)[0]
    assert card_kb == [f"chk:f:{INN_MULTI}"] + MAIN_PAYLOADS
    assert "📋 Проверить в Checko" in [t for _k, t, _p in max_bot.buttons()]
    assert "<b>МОТС</b>" in max_bot.blob()


def test_card_without_checko_key_has_no_checko_button(max_bot, config_stub, monkeypatch):
    monkeypatch.setattr(config_stub, "CHECKO_API_KEY", "")
    _text(max_bot, INN_SINGLE)

    assert all(kb == MAIN_PAYLOADS for kb in _keyboards(max_bot))
    assert not any(p.startswith("chk:") for p in max_bot.callback_payloads())


def test_name_search_single_hit_opens_card(max_bot):
    _open_search(max_bot)
    _text(max_bot, "двойной")

    assert "ООО «Двойной Тест»" in max_bot.blob()


def test_name_search_many_hits_lists_buttons(max_bot):
    _open_search(max_bot)
    _text(max_bot, "тест")

    assert "Найдено <b>3</b>" in max_bot.blob()
    payloads = max_bot.callback_payloads()
    assert {f"inn:{INN_SINGLE}", f"inn:{INN_MULTI}", f"inn:{INN_EXCLUDED}"} <= set(payloads)


def test_card_fetches_missing_details_from_site(max_bot, monkeypatch):
    mem = max_bot.m.reestr_database[INN_SINGLE]["memberships"]["OGPS"]
    del mem["inspections_by_year"]
    monkeypatch.setattr(reestr_sync, "_fetch", lambda _url: read_fixture("reestr_detail_full.html"))

    _text(max_bot, INN_SINGLE)

    assert max_bot.api.sent[0]["text"] == max_bot.m.CARD_LOADING_TEXT
    card = max_bot.api.edits[0]["text"]
    assert "Проверки (последние 3 года)" in card
    assert "2025 — ✅ Нарушений не выявлено" in card
    assert "КФ ВВ: ур. 2" in card


def test_card_keeps_cache_when_site_returns_stub(max_bot, monkeypatch):
    mem = max_bot.m.reestr_database[INN_SINGLE]["memberships"]["OGPS"]
    del mem["inspections_by_year"]
    monkeypatch.setattr(reestr_sync, "_fetch", lambda _url: read_fixture("reestr_detail_antibot.html"))

    _text(max_bot, INN_SINGLE)

    card = max_bot.api.edits[0]["text"]
    assert "ООО «Тестстрой»" in card
    assert "КФ ВВ: ур. 1" in card
    saved = max_bot.m.reestr_database[INN_SINGLE]["memberships"]["OGPS"]
    assert saved["director"] == "Тестов Тест Тестович"
    assert saved["reg_number"] == "OGPS-001"


def test_found_org_card_has_checko_button_for_member(max_bot, config_stub, monkeypatch):
    """Checko — для всех: кнопка под карточкой, без /controller."""
    monkeypatch.setattr(config_stub, "CHECKO_API_KEY", "test-fake-checko-key")

    _text(max_bot, INN_SINGLE)

    assert "ООО «Тестстрой»" in max_bot.blob()
    assert f"chk:f:{INN_SINGLE}" in max_bot.callback_payloads()


def test_absent_inn_offers_checko_to_member(max_bot, config_stub, monkeypatch):
    monkeypatch.setattr(config_stub, "CHECKO_API_KEY", "test-fake-checko-key")

    _text(max_bot, INN_ABSENT)

    assert "в реестре 15 СРО не найден" in max_bot.blob()
    payloads = max_bot.callback_payloads()
    assert f"chk:f:{INN_ABSENT}" in payloads
    assert f"chk:r:{INN_ABSENT}" not in payloads
