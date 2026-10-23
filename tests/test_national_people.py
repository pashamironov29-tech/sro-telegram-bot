# -*- coding: utf-8 -*-
"""Специалисты НРС сразу в карточке организации из поиска НОСТРОЙ/НОПРИЗ."""

from __future__ import annotations

import types

import log_redact
import requests

_real_install = log_redact.install_secret_log_redaction
log_redact.install_secret_log_redaction = lambda *a, **k: None  # type: ignore[method-assign]
import bot_FINAL_GOLD  # noqa: E402

log_redact.install_secret_log_redaction = _real_install

import national_reestr  # noqa: E402
from national_reestr import format_people, load_member_view, parse_page_callback  # noqa: E402
from specialist_sync import RegistryClient  # noqa: E402
from tests.support import TEST_UID  # noqa: E402

SRO = {"id": 185, "full_description": "Ассоциация «Пример»", "registration_number": "СРО-С-001-01012010"}


def _nostroy_card(count: int) -> dict:
    return {
        "id": 10,
        "short_description": 'ООО "Ромашка"',
        "inn": "7700000001",
        "sro": {"id": 185, "full_description": "Ассоциация «Пример»"},
        "experts_by_category": {
            "regular": [
                {
                    "id": i,
                    "is_highlighted": False,
                    "expert_type": {"id": 1, "code": "regular", "title": "Специалист"},
                    "fio": f"Иванов Иван {i:02d}",
                    "number": f"С-77-{i:06d}",
                }
                for i in range(1, count + 1)
            ],
            "danger": [],
            "other": [],
        },
    }


NOPRIZ_CARD = {
    "id": 20,
    "short_description": 'ООО "Проект"',
    "sro": {"id": 5, "full_description": "Ассоциация «Проектировщики»", "registration_number": "СРО-П-005"},
    "specialists_data": {
        "regular": [
            {
                "id": 1,
                "spec_type": {"code": "regular", "title": "Специалист"},
                "work_type": {"code": "project", "title": "Подготовка проектной документации"},
                "fio": "Петров Пётр Петрович",
                "created": "2026-09-17T12:58:24+03:00",
                "registration_number": "П-017925",
            }
        ],
        "danger": [],
        "other": [],
    },
}


def _client(transport):
    return RegistryClient(transport, min_interval=0, timeout=1, retries=1, sleep=lambda _s: None)


def _transport(card):
    def transport(url, body, timeout):
        if "/member/" in url and url.endswith("/info"):
            return 200, {"success": True, "data": card}
        if "/sro/" in url:
            return 200, {"success": True, "data": SRO}
        raise AssertionError(url)

    return transport


def setup_function(_fn):
    national_reestr.clear_hit_cache()
    national_reestr.clear_sro_cache()


def test_pick_shows_card_and_people_at_once():
    view = load_member_view("nat:nostroy:10", client=_client(_transport(_nostroy_card(3))))
    assert "ООО" in view.text and "СРО-С-001-01012010" in view.text
    assert "Специалисты НРС: 3" in view.text
    assert "Иванов Иван 01" in view.text and "<code>С-77-000003</code>" in view.text
    assert "Специалист" in view.text
    assert view.buttons == []


def test_nopriz_people_have_work_type_and_date():
    view = load_member_view("nat:nopriz:20", client=_client(_transport(NOPRIZ_CARD)))
    assert "Петров Пётр Петрович" in view.text
    assert "П-017925" in view.text
    assert "Подготовка проектной документации" in view.text
    assert "17.09.2026" in view.text


def test_long_list_is_paginated():
    card = _nostroy_card(25)
    view = load_member_view("nat:nostroy:10", client=_client(_transport(card)))
    assert "стр. 1 из 3" in view.text
    assert "Иванов Иван 10" in view.text and "Иванов Иван 11" not in view.text
    assert [b.payload for b in view.buttons] == ["natp:nostroy:10:2"]
    assert all(len(b.payload.encode()) <= 64 for b in view.buttons)

    page = load_member_view("natp:nostroy:10:3", client=_client(_transport(card)))
    assert "стр. 3 из 3" in page.text
    assert "21. <b>Иванов Иван 21</b>" in page.text and "Иванов Иван 25" in page.text
    assert "Ромашка" in page.text
    assert [b.payload for b in page.buttons] == ["natp:nostroy:10:2"]

    page2 = load_member_view("natp:nostroy:10:2", client=_client(_transport(card)))
    assert [b.payload for b in page2.buttons] == ["natp:nostroy:10:1", "natp:nostroy:10:3"]
    # страница за пределами — последняя
    assert "стр. 3 из 3" in format_people(card, 99)[0]


def test_no_people_and_missing_block():
    empty = _nostroy_card(0)
    assert "нет данных о специалистах" in load_member_view(
        "nat:nostroy:10", client=_client(_transport(empty))
    ).text
    card = _nostroy_card(1)
    del card["experts_by_category"]
    assert "не отдал список" in format_people(card)[0]


def test_duplicates_merged_and_html_escaped():
    card = _nostroy_card(0)
    person = {"fio": "<b>Злой</b> Ф", "number": "С-1", "expert_type": {"title": "Специалист"}}
    card["experts_by_category"]["regular"] = [person, dict(person)]
    card["experts_by_category"]["danger"] = [dict(person, expert_type={"title": "ООО"})]
    text = format_people(card)[0]
    assert "Специалисты НРС: 1" in text
    assert "&lt;b&gt;Злой" in text and "<b>Злой" not in text


def test_api_errors_are_graceful():
    def down(url, body, timeout):
        raise requests.Timeout("timed out")

    assert load_member_view("nat:nostroy:10", client=_client(down)).text == national_reestr.CARD_FAIL
    assert load_member_view("natp:nostroy:10:2", client=_client(down)).text == national_reestr.PEOPLE_FAIL
    # карточка из кэша списка есть — показываем её и пишем про специалистов
    national_reestr.remember(national_reestr.MemberHit("nostroy", 10, name="ООО Ромашка"))
    text = load_member_view("nat:nostroy:10", client=_client(down)).text
    assert "ООО Ромашка" in text and national_reestr.PEOPLE_FAIL in text
    assert load_member_view("natp:bad", client=_client(down)).text.startswith("Кнопка устарела")


def test_parse_page_callback():
    assert parse_page_callback("natp:nopriz:123:4") == ("nopriz", 123, 4)
    assert parse_page_callback("natp:nopriz:123:0") == ("nopriz", 123, 1)
    assert parse_page_callback("nat:nopriz:123") is None


def test_max_page_button_routes(max_bot, monkeypatch):
    seen = []

    def fake_view(payload, **_kwargs):
        seen.append(payload)
        return national_reestr.SearchResult(
            f"люди {payload}", [national_reestr.PickButton("стр. 2 ▶", "natp:nostroy:10:2")]
        )

    monkeypatch.setattr(national_reestr, "load_member_view", fake_view)
    max_bot.m.handle_callback(TEST_UID, "nat:nostroy:10", {})
    assert "люди nat:nostroy:10" in max_bot.blob()
    assert "natp:nostroy:10:2" in max_bot.callback_payloads()
    max_bot.m.handle_callback(TEST_UID, "natp:nostroy:10:2", {})
    assert seen == ["nat:nostroy:10", "natp:nostroy:10:2"]


def test_tg_page_button_routes(monkeypatch):
    sent = []

    def send(chat_id, text, **kwargs):
        sent.append((text or "", kwargs.get("reply_markup")))
        return types.SimpleNamespace(message_id=len(sent))

    monkeypatch.setattr(bot_FINAL_GOLD.bot, "send_message", send)
    monkeypatch.setattr(bot_FINAL_GOLD.bot, "answer_callback_query", lambda *a, **k: None)
    monkeypatch.setattr(
        national_reestr,
        "load_member_view",
        lambda payload, **_k: national_reestr.SearchResult(
            f"люди {payload}", [national_reestr.PickButton("стр. 3 ▶", "natp:nostroy:10:3")]
        ),
    )
    bot_FINAL_GOLD.handle_national_pick(
        types.SimpleNamespace(
            id="cb",
            data="natp:nostroy:10:2",
            message=types.SimpleNamespace(chat=types.SimpleNamespace(id=727272), message_id=3),
        )
    )
    text, markup = sent[-1]
    assert text == "люди natp:nostroy:10:2"
    assert markup.keyboard[0][0].callback_data == "natp:nostroy:10:3"
