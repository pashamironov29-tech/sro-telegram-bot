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
    read_fixture,
)

UID = TEST_UID


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


def test_inn_not_found_during_onboarding(max_bot):
    _text(max_bot, "/start")
    max_bot.clear()

    _text(max_bot, INN_ABSENT)

    blob = max_bot.blob()
    assert "Организация не найдена в реестре" in blob
    assert "menu:skip" in max_bot.callback_payloads()


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
    _text(max_bot, INN_MULTI)

    blob = max_bot.blob()
    assert "<b>ОГПС</b>" in blob
    assert "<b>МОТС</b>" in blob
    assert "Организация состоит в нескольких СРО" in blob
    payloads = max_bot.callback_payloads()
    assert "sro:OGPS" in payloads
    assert "sro:MOTS" in payloads
    assert sro_context.pending_sro_ids(UID) == ["OGPS", "MOTS"]


def test_pick_sro_after_multi_card(max_bot):
    _text(max_bot, INN_MULTI)
    max_bot.clear()

    max_bot.m.handle_callback(UID, "sro:MOTS", {})

    assert "Выбрано: <b>" in max_bot.blob()
    assert sro_context.get_user_sro_id(UID) == "MOTS"
    assert sro_context.get_user_context(UID)["inn"] == INN_MULTI


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


def test_controller_gets_checko_fork(max_bot, max_controller, config_stub, monkeypatch):
    monkeypatch.setattr(config_stub, "CHECKO_API_KEY", "test-fake-checko-key")
    max_bot.m.handle_text(max_controller, "/controller", {})
    max_bot.clear()

    max_bot.m.handle_text(max_controller, INN_SINGLE, {})

    assert "Организация найдена" in max_bot.blob()
    payloads = max_bot.callback_payloads()
    assert f"chk:r:{INN_SINGLE}" in payloads
    assert f"chk:f:{INN_SINGLE}" in payloads


def test_controller_absent_inn_offers_checko(max_bot, max_controller, config_stub, monkeypatch):
    monkeypatch.setattr(config_stub, "CHECKO_API_KEY", "test-fake-checko-key")
    max_bot.m.handle_text(max_controller, "/controller", {})
    max_bot.clear()

    max_bot.m.handle_text(max_controller, INN_ABSENT, {})

    assert "в реестре 15 СРО не найден" in max_bot.blob()
    payloads = max_bot.callback_payloads()
    assert f"chk:f:{INN_ABSENT}" in payloads
    assert f"chk:r:{INN_ABSENT}" not in payloads
