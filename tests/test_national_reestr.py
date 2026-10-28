# -*- coding: utf-8 -*-
"""Поиск в едином реестре НОСТРОЙ/НОПРИЗ: разбор ответа без сети."""

from __future__ import annotations

import types

import log_redact
import requests

_real_install = log_redact.install_secret_log_redaction
log_redact.install_secret_log_redaction = lambda *a, **k: None  # type: ignore[method-assign]
import bot_FINAL_GOLD  # noqa: E402

log_redact.install_secret_log_redaction = _real_install

import national_reestr  # noqa: E402
from national_reestr import (  # noqa: E402
    MemberHit,
    apply_card,
    classify_query,
    format_member_card,
    make_client,
    parse_list_row,
    search_members,
)
from specialist_sync import RegistryClient  # noqa: E402
from tests.support import TEST_UID, keyboard_buttons  # noqa: E402

NOSTROY_ROW = {
    "id": 10,
    "full_description": 'Общество с ограниченной ответственностью "Ромашка"',
    "short_description": 'ООО "Ромашка"',
    "inn": "7700000001",
    "ogrnip": "1027700000001",
    "member_status": {"id": 1, "code": "1", "title": "Является членом"},
    "registry_registration_date": "2020-02-14T00:00:00+03:00",
    "sro": {
        "id": 185,
        "full_description": "Ассоциация «Пример»",
        "registration_number": "СРО-С-001-01012010",
    },
}

NOSTROY_CARD = {
    "id": 10,
    "short_description": 'ООО "Ромашка"',
    "full_description": 'Общество с ограниченной ответственностью "Ромашка"',
    "inn": "7700000001",
    "ogrnip": "1027700000001",
    "registry_registration_date": "2020-02-14T00:00:00+03:00",
    "sro": {
        "id": 185,
        "full_description": "Ассоциация «Пример»",
        "short_description": "А «Пример»",
    },
    "responsibility_level_vv": {
        "id": 3,
        "code": "3",
        "title": "Третий уровень ответственности",
        "cost": "не превышает три миллиарда рублей",
    },
    "responsibility_level_odo": {
        "id": 2,
        "code": "2",
        "title": "Второй уровень ответственности",
        "cost": "не превышает пятьсот миллионов рублей",
    },
    "right": {
        "right_status": {"id": 1, "code": "1", "title": "Действует"},
        "is_simple": True,
        "is_extremely_dangerous": True,
        "is_nuclear": False,
        "is_odo": True,
    },
}

EXCLUDED_ROW = {
    "id": 11,
    "short_description": "ИП Сидоров Сидор Сидорович",
    "inn": "371102798545",
    "ogrnip": "322370000007349",
    "member_status": {"id": 2, "code": "2", "title": "Исключен"},
    "registry_registration_date": "2026-09-21T00:00:00+03:00",
    "suspension_date": "2026-10-14T00:00:00+03:00",
    "sro": {
        "id": 647,
        "full_description": "СРО «Иваново»",
        "registration_number": "СРО-С-316-26122024",
    },
}

NOPRIZ_CARD = {
    "short_description": "ИП Цуканов Павел Георгиевич",
    "inn": "770301252767",
    "ogrnip": "314774608000721",
    "member_status": {"id": 1, "code": "1", "title": "Является членом"},
    "registry_registration_date": "2020-12-10T00:00:00+03:00",
    "sro": {"id": 394, "full_description": "АП «АР»"},
    "responsibility_level_vv": {
        "id": 1,
        "code": "1",
        "title": "Первый уровень ответственности",
        "cost": "не превышает двадцать пять миллионов рублей",
    },
    "right": {
        "right_status": {"id": 1, "code": "1", "title": "Действует"},
        "is_simple": True,
        "is_extremely_dangerous": False,
        "is_nuclear": False,
    },
    "member_right_vv": {
        "right_status": {"id": 3, "code": "3", "title": "Прекращено"},
        "responsibility_level": {
            "code": "1",
            "title": "Первый уровень ответственности",
            "cost": "не превышает двадцать пять миллионов рублей",
        },
    },
}


def _list_payload(rows, count=None):
    return {
        "success": True,
        "data": {"data": rows, "count": len(rows) if count is None else count, "page": 1},
    }


def _client(transport) -> RegistryClient:
    return make_client(transport)


def test_parse_active_member_card_keeps_sro_number_from_list():
    hit = parse_list_row("nostroy", NOSTROY_ROW)
    assert hit is not None
    hit = apply_card(hit, NOSTROY_CARD)
    text = format_member_card(hit)
    assert "НОСТРОЙ" in text
    assert "ООО &quot;Ромашка&quot;" in text or 'ООО "Ромашка"' in text
    assert "7700000001" in text
    assert "1027700000001" in text
    assert "Ассоциация «Пример»" in text
    assert "СРО-С-001-01012010" in text
    assert "Является членом (в реестре с 14.02.2020)" in text
    assert "Право на работы: Действует" in text
    assert "обычные объекты" in text
    assert "особо опасные" in text
    assert "договоры ОДО" in text
    assert "Уровень ВВ: Третий уровень ответственности, не превышает три миллиарда рублей" in text
    assert "Уровень ОДО: Второй уровень ответственности, не превышает пятьсот миллионов рублей" in text
    assert 'href="https://reestr.nostroy.ru/member/10"' in text


def test_html_in_name_is_escaped():
    row = dict(NOSTROY_ROW)
    row["short_description"] = "ООО <script>"
    hit = parse_list_row("nostroy", row)
    text = format_member_card(hit)
    assert "<script>" not in text
    assert "&lt;script&gt;" in text


def test_excluded_member_shows_suspension_date():
    hit = parse_list_row("nostroy", EXCLUDED_ROW)
    text = format_member_card(hit)
    assert "Исключен (14.10.2026, в реестре с 21.09.2026)" in text
    assert "СРО-С-316-26122024" in text
    assert "Уровень ВВ" not in text


def test_nopriz_card_without_odo_level_skips_odo_line():
    hit = MemberHit(registry="nopriz", member_id=20, name="черновик")
    hit = apply_card(hit, NOPRIZ_CARD)
    text = format_member_card(hit)
    assert "НОПРИЗ" in text
    assert "Право на работы: Действует; ВВ — Прекращено" in text
    assert "Уровень ВВ: Первый уровень ответственности" in text
    assert "Уровень ОДО" not in text
    assert "reestr.nopriz.ru/member/20" in text
    assert hit.sro_reg == ""


def test_classify_query():
    assert classify_query("77 000 000 01") == ("inn", "7700000001")
    assert classify_query("1027700000001") == ("ogrn", "1027700000001")
    assert classify_query("12345") == ("bad", "12345")
    assert classify_query("  аб ") == ("short", "аб")
    assert classify_query(' «Ромашка» ') == ("name", "Ромашка")


def test_search_by_inn_calls_both_registries_and_card():
    calls = []

    def transport(url, body, timeout):
        calls.append((url, body, timeout))
        if url.endswith("/member/list"):
            if "nostroy" in url:
                return 200, _list_payload([NOSTROY_ROW], count=1)
            return 200, _list_payload([], count=0)
        if url.endswith("/member/10/info"):
            return 200, {"success": True, "data": NOSTROY_CARD}
        raise AssertionError(url)

    result = search_members("7700000001", client=_client(transport))
    assert "СРО-С-001-01012010" in result.text
    assert "Уровень ВВ" in result.text
    assert result.buttons == []
    urls = [url for url, _body, _timeout in calls]
    assert urls[0] == "https://reestr.nostroy.ru/api/sro/all/member/list"
    assert urls[1] == "https://reestr.nopriz.ru/api/sro/all/member/list"
    assert calls[0][1]["filters"] == {"inn": "7700000001"}
    assert calls[0][1]["searchString"] == ""
    assert calls[0][1]["pageCount"] == "20"
    assert "https://reestr.nostroy.ru/api/member/10/info" in urls
    assert all("/api/sro/185" not in url for url in urls)


def test_several_matches_are_buttons_without_card_request():
    national_reestr.clear_sro_cache()
    second = dict(NOSTROY_ROW)
    second["id"] = 12
    second["short_description"] = "ООО «Другая»"
    second["sro"] = {
        "id": 7,
        "full_description": "СРО Другая",
        "registration_number": "СРО-С-002-02022010",
    }
    calls = []

    def transport(url, body, timeout):
        calls.append(url)
        if url.endswith("/member/list") and "nostroy" in url:
            return 200, _list_payload([NOSTROY_ROW, second], count=2)
        if url.endswith("/member/list"):
            return 200, _list_payload([], count=0)
        if url.endswith("/sro/185"):
            return 200, {
                "success": True,
                "data": {
                    "id": 185,
                    "short_description": "А «Пример»",
                    "full_description": "Ассоциация «Пример»",
                    "registration_number": "СРО-С-001-01012010",
                },
            }
        if url.endswith("/sro/7"):
            return 200, {
                "success": True,
                "data": {
                    "id": 7,
                    "short_description": "СРО «Вторая»",
                    "full_description": "СРО Другая",
                    "registration_number": "СРО-С-002-02022010",
                },
            }
        raise AssertionError(url)

    result = search_members("Ромашка", client=_client(transport))
    assert "найдено: 2" in result.text
    assert "НОСТРОЙ" in result.text
    assert "Ассоциация «Пример»" in result.text
    assert "СРО-С-001-01012010" in result.text
    assert "СРО-С-002-02022010" in result.text
    assert [button.label for button in result.buttons] == [
        "Ромашка · НОСТРОЙ · Пример",
        "Другая · НОСТРОЙ · Вторая",
    ]
    assert [button.payload for button in result.buttons] == ["nat:nostroy:10", "nat:nostroy:12"]
    assert calls[0].endswith("/api/sro/all/member/list")
    assert all("/info" not in url for url in calls)
    assert any(url.endswith("/sro/185") for url in calls)
    assert calls[0] and "searchString" not in calls[0]


def test_name_search_uses_search_string():
    seen = {}

    def transport(url, body, timeout):
        if url.endswith("/member/list"):
            seen.setdefault("bodies", []).append(body)
            return 200, _list_payload([], count=0)
        raise AssertionError(url)

    result = search_members("Ромашка", client=_client(transport))
    assert "такой организации нет" in result.text
    assert seen["bodies"][0]["searchString"] == "Ромашка"
    assert seen["bodies"][0]["filters"] == {}


def test_too_many_matches_ask_to_narrow():
    def transport(url, body, timeout):
        if url.endswith("/member/list"):
            count = 30 if "nostroy" in url else 0
            rows = [NOSTROY_ROW] if count else []
            return 200, _list_payload(rows, count=count)
        raise AssertionError(url)

    result = search_members("Строй", client=_client(transport))
    assert "слишком много совпадений (30)" in result.text
    assert result.buttons == []


def test_timeout_of_both_registries_is_a_message():
    def transport(url, body, timeout):
        raise requests.Timeout("timed out")

    result = search_members("7700000001", client=_client(transport))
    assert "не ответили вовремя" in result.text
    assert result.buttons == []


def test_one_registry_down_still_shows_the_other():
    def transport(url, body, timeout):
        if "nopriz" in url:
            raise requests.Timeout("timed out")
        if url.endswith("/member/list"):
            return 200, _list_payload([NOSTROY_ROW], count=1)
        if url.endswith("/info"):
            return 200, {"success": True, "data": NOSTROY_CARD}
        raise AssertionError(url)

    result = search_members("7700000001", client=_client(transport))
    assert "Ромашка" in result.text
    assert "НОПРИЗ не ответил вовремя" in result.text
    assert "Показаны только совпадения НОСТРОЙ" in result.text


def test_http_error_does_not_raise():
    def transport(url, body, timeout):
        return 503, {"success": False}

    result = search_members("7700000001", client=_client(transport))
    assert "Не удалось выполнить поиск" in result.text


def test_bad_and_short_queries_do_not_call_api():
    def transport(url, body, timeout):
        raise AssertionError("сеть не нужна")

    client = _client(transport)
    assert "10 или 12" in search_members("123", client=client).text
    assert "3 символа" in search_members("аб", client=client).text


def test_load_card_without_cache_asks_sro_number():
    def transport(url, body, timeout):
        if url.endswith("/member/10/info"):
            return 200, {"success": True, "data": NOSTROY_CARD}
        if url.endswith("/sro/185"):
            return 200, {
                "success": True,
                "data": {
                    "id": 185,
                    "full_description": "Ассоциация «Пример»",
                    "registration_number": "СРО-С-001-01012010",
                },
            }
        raise AssertionError(url)

    text = national_reestr.load_member_text("nat:nostroy:10", client=_client(transport))
    assert "СРО-С-001-01012010" in text
    assert "Уровень ОДО" in text
    assert national_reestr.load_member_text("nat:nope:1", client=_client(transport)).startswith(
        "Кнопка устарела"
    )


def test_card_timeout_with_cached_list_keeps_status():
    hit = parse_list_row("nostroy", EXCLUDED_ROW)
    national_reestr.remember(hit)

    def transport(url, body, timeout):
        raise requests.Timeout("timed out")

    text = national_reestr.load_member_text("nat:nostroy:11", client=_client(transport))
    assert "Исключен" in text
    assert "не загрузились" in text


def test_max_button_opens_search_and_list(max_bot, monkeypatch):
    max_bot.m.handle_callback(TEST_UID, "menu:nat", {})
    assert "Единый реестр" in max_bot.blob()
    assert national_reestr.is_national_mode(TEST_UID)
    labels = [text for _k, text, payload in keyboard_buttons(max_bot.m.main_keyboard(TEST_UID))]
    assert "🏢 Поиск организации в НОСТРОЙ / НОПРИЗ" in labels

    max_bot.clear()

    def fake_search(_query, **_kwargs):
        return national_reestr.SearchResult(
            "🏛 найдено: 2",
            [national_reestr.PickButton("ООО Ромашка · член", "nat:nostroy:10")],
        )

    monkeypatch.setattr(national_reestr, "search_members", fake_search)
    max_bot.m.handle_text(TEST_UID, "Ромашка", {})
    assert "найдено: 2" in max_bot.blob()
    assert "nat:nostroy:10" in max_bot.callback_payloads()

    max_bot.clear()
    monkeypatch.setattr(
        national_reestr,
        "load_member_view",
        lambda payload, **_kwargs: national_reestr.SearchResult(f"карточка {payload}"),
    )
    max_bot.m.handle_callback(TEST_UID, "nat:nostroy:10", {})
    assert "карточка nat:nostroy:10" in max_bot.blob()


def test_tg_menu_has_button_and_handles_query(monkeypatch):
    chat_id = 717171
    sent = []

    def send(chat_id, text, **kwargs):
        sent.append((text or "", kwargs.get("reply_markup")))
        return types.SimpleNamespace(message_id=len(sent))

    edits = []

    def edit(text, chat_id, message_id, **kwargs):
        edits.append((text or "", kwargs.get("reply_markup"), message_id))
        return types.SimpleNamespace(message_id=message_id)

    monkeypatch.setattr(bot_FINAL_GOLD.bot, "send_message", send)
    monkeypatch.setattr(bot_FINAL_GOLD.bot, "edit_message_text", edit)
    monkeypatch.setattr(bot_FINAL_GOLD.bot, "answer_callback_query", lambda *a, **k: None)
    labels = []
    for row in bot_FINAL_GOLD.get_main_keyboard(chat_id).keyboard:
        for button in row:
            labels.append(button["text"] if isinstance(button, dict) else button.text)
    assert bot_FINAL_GOLD.NATIONAL_BUTTON in labels

    bot_FINAL_GOLD.handle_text(
        types.SimpleNamespace(
            text=bot_FINAL_GOLD.NATIONAL_BUTTON,
            chat=types.SimpleNamespace(id=chat_id),
            from_user=types.SimpleNamespace(id=chat_id, first_name="Т", last_name="", username="u"),
        )
    )
    assert "Единый реестр" in sent[-1][0]

    def fake_search(_query, **_kwargs):
        return national_reestr.SearchResult(
            "🏛 найдено: 2",
            [national_reestr.PickButton("ООО Ромашка · член", "nat:nostroy:10")],
        )

    monkeypatch.setattr(national_reestr, "search_members", fake_search)
    bot_FINAL_GOLD.handle_text(
        types.SimpleNamespace(
            text="Ромашка",
            chat=types.SimpleNamespace(id=chat_id),
            from_user=types.SimpleNamespace(id=chat_id, first_name="Т", last_name="", username="u"),
        )
    )
    bot_FINAL_GOLD.wait_heavy_tasks()
    assert "Ищу…" in sent[-1][0]
    text, markup, _mid = edits[-1]
    assert "найдено: 2" in text
    assert markup.keyboard[0][0].callback_data == "nat:nostroy:10"

    monkeypatch.setattr(
        national_reestr,
        "load_member_view",
        lambda payload, **_kwargs: national_reestr.SearchResult("карточка из кнопки"),
    )
    bot_FINAL_GOLD.handle_national_pick(
        types.SimpleNamespace(
            id="cb",
            data="nat:nostroy:10",
            message=types.SimpleNamespace(chat=types.SimpleNamespace(id=chat_id), message_id=3),
        )
    )
    assert sent[-1][0] == "карточка из кнопки"


PATOK_NOSTROY = {
    "id": 501,
    "short_description": "ООО «ПАТОК»",
    "full_description": "Общество с ограниченной ответственностью «ПАТОК»",
    "inn": "9723088557",
    "ogrnip": "1227700000001",
    "member_status": {"id": 1, "code": "1", "title": "Является членом"},
    "sro": {
        "id": 87,
        "full_description": "Ассоциация «Объединение генеральных подрядчиков в строительстве»",
        "registration_number": "СРО-С-020-22072009",
    },
}

PATOK_NOPRIZ = {
    "id": 502,
    "short_description": "ООО «Паток»",
    "full_description": "Общество с ограниченной ответственностью «Паток»",
    "inn": "9723088557",
    "ogrnip": "1227700000001",
    "member_status": {"id": 1, "code": "1", "title": "Является членом"},
    "sro": {
        "id": 372,
        "full_description": 'Ассоциация "Объединение градостроительных проектных организаций"',
        "registration_number": "СРО-П-196-14022018",
    },
}


def _sro_card(short: str, full: str, reg: str) -> dict:
    return {
        "success": True,
        "data": {
            "short_description": short,
            "full_description": full,
            "registration_number": reg,
        },
    }


def test_two_registries_show_sro_on_list_and_buttons():
    national_reestr.clear_sro_cache()
    calls = []

    def transport(url, body, timeout):
        calls.append(url)
        if url.endswith("/member/list") and "nostroy" in url:
            return 200, _list_payload([PATOK_NOSTROY], count=1)
        if url.endswith("/member/list"):
            return 200, _list_payload([PATOK_NOPRIZ], count=1)
        if url.endswith("/sro/87"):
            return 200, _sro_card(
                "Ассоциация «Объединение генподрядчиков в строительстве»",
                "Ассоциация «Объединение генеральных подрядчиков в строительстве»",
                "СРО-С-020-22072009",
            )
        if url.endswith("/sro/372"):
            return 200, _sro_card(
                'Ассоциация "ОГПО"',
                'Ассоциация "Объединение градостроительных проектных организаций"',
                "СРО-П-196-14022018",
            )
        raise AssertionError(url)

    result = search_members("9723088557", client=_client(transport))
    assert "найдено: 2" in result.text
    assert (
        "1. ООО «ПАТОК» — Является членом — НОСТРОЙ · "
        "Ассоциация «Объединение генеральных подрядчиков в строительстве» · "
        "СРО-С-020-22072009"
    ) in result.text
    assert (
        "2. ООО «Паток» — Является членом — НОПРИЗ · "
        'Ассоциация "Объединение градостроительных проектных организаций" · '
        "СРО-П-196-14022018"
    ) in result.text
    assert [button.label for button in result.buttons] == [
        "ПАТОК · НОСТРОЙ · Объед. генподрядчиков",
        "Паток · НОПРИЗ · ОГПО",
    ]
    assert [button.payload for button in result.buttons] == ["nat:nostroy:501", "nat:nopriz:502"]
    for button in result.buttons:
        assert len(button.label) <= 60
        assert len(button.payload.encode("utf-8")) <= 64
        assert "ПАТОК" not in button.payload
        assert "ОГПО" not in button.payload
    assert all("/member/" not in url or url.endswith("/member/list") for url in calls)
    assert any(url.endswith("/sro/87") for url in calls)
    assert any(url.endswith("/sro/372") for url in calls)


def test_sro_card_failure_still_names_registry_and_full_sro():
    national_reestr.clear_sro_cache()

    def transport(url, body, timeout):
        if url.endswith("/member/list") and "nostroy" in url:
            return 200, _list_payload([PATOK_NOSTROY], count=1)
        if url.endswith("/member/list"):
            return 200, _list_payload([PATOK_NOPRIZ], count=1)
        if "/sro/" in url:
            raise requests.Timeout("timed out")
        raise AssertionError(url)

    result = search_members("9723088557", client=_client(transport))
    assert "НОСТРОЙ" in result.text
    assert "НОПРИЗ" in result.text
    assert "СРО-С-020-22072009" in result.text
    assert "СРО-П-196-14022018" in result.text
    assert "Объединение генеральных подрядчиков в строительстве" in result.text
    assert [button.label for button in result.buttons] == [
        "ПАТОК · НОСТРОЙ · Объед. генеральных подрядчиков",
        "Паток · НОПРИЗ · Объед. градостроительных проектных…",
    ]
    assert all(len(button.label) <= 60 for button in result.buttons)
    assert [button.payload for button in result.buttons] == ["nat:nostroy:501", "nat:nopriz:502"]


def test_short_name_on_the_list_row_skips_sro_request():
    national_reestr.clear_sro_cache()
    row = dict(PATOK_NOSTROY)
    row["sro"] = dict(PATOK_NOSTROY["sro"])
    row["sro"]["short_description"] = "Ассоциация «Объединение генподрядчиков в строительстве»"
    calls = []

    def transport(url, body, timeout):
        calls.append(url)
        if url.endswith("/member/list") and "nostroy" in url:
            return 200, _list_payload([row], count=1)
        if url.endswith("/member/list"):
            return 200, _list_payload([PATOK_NOPRIZ], count=1)
        if url.endswith("/sro/372"):
            return 200, _sro_card(
                'Ассоциация "ОГПО"',
                'Ассоциация "Объединение градостроительных проектных организаций"',
                "СРО-П-196-14022018",
            )
        raise AssertionError(url)

    result = search_members("9723088557", client=_client(transport))
    assert result.buttons[0].label == "ПАТОК · НОСТРОЙ · Объед. генподрядчиков"
    assert all(not url.endswith("/sro/87") for url in calls)


def test_button_uses_distinctive_sro_short_name():
    cases = [
        ("СРО Союз «МООСС»", "nostroy", "ООО «Альфа»", "Альфа · НОСТРОЙ · МООСС"),
        ("Ассоциация СРО «МОС»", "nostroy", "ООО «Бета»", "Бета · НОСТРОЙ · МОС"),
        (
            "СРО А «Объединение строителей СПб»",
            "nostroy",
            "ИП Сидоров Сидор Сидорович",
            "Сидоров Сидор Сидорович · НОСТРОЙ · Объед. строителей СПб",
        ),
        ("Ассоциация «Сахалинстрой»", "nopriz", "АО «Гамма»", "Гамма · НОПРИЗ · Сахалинстрой"),
        (
            "(СРО) Ассоциация «Томское проектное объединение»",
            "nopriz",
            "ООО «Дельта»",
            "Дельта · НОПРИЗ · Томское проектное объединение",
        ),
    ]
    for short, registry, org, expected in cases:
        label = national_reestr.button_label(
            MemberHit(
                registry=registry,
                member_id=1,
                name=org,
                sro_short=short,
                status_code="1",
                status_title="Является членом",
            )
        )
        assert label == expected
        assert len(label) <= 60


def test_long_button_keeps_registry_and_callback_short():
    hit = MemberHit(
        registry="nostroy",
        member_id=10**12 - 1,
        name="ООО «" + ("Оченьдлинноеназвание" * 4) + "»",
        sro_name="Ассоциация «" + ("Длинное имя саморегулируемой организации " * 4) + "»",
        sro_short="Ассоциация «Объединение генподрядчиков в строительстве и ещё много лишних слов»",
        sro_reg="СРО-С-020-22072009",
        status_title="Является членом",
        status_code="1",
    )
    label = national_reestr.button_label(hit)
    assert "НОСТРОЙ" in label
    assert len(label) <= 60
    assert label.index("НОСТРОЙ") < label.rindex("·")
    payload = national_reestr.callback_payload(hit)
    assert payload == "nat:nostroy:999999999999"
    assert len(payload.encode("utf-8")) <= 64
    text = national_reestr.format_member_list("запрос <b>", [hit], 1)
    assert "НОСТРОЙ" in text
    assert "СРО-С-020-22072009" in text
    assert "запрос &lt;b&gt;" in text
    assert "запрос <b>" not in text


def test_list_escapes_sro_name():
    hit = parse_list_row(
        "nopriz",
        {
            "id": 3,
            "short_description": "ООО <script>",
            "member_status": {"code": "1", "title": "Является членом"},
            "sro": {
                "id": 1,
                "full_description": "Ассоциация <b>Злая</b>",
                "registration_number": "СРО-П-001-01012010",
            },
        },
    )
    text = national_reestr.format_member_list("имя", [hit], 1)
    assert "ООО &lt;script&gt;" in text
    assert "Ассоциация &lt;b&gt;Злая&lt;/b&gt;" in text
    assert "НОПРИЗ" in text
    assert "СРО-П-001-01012010" in text
    assert "<script>" not in text


def test_help_and_welcome_mention_button(monkeypatch):
    sent = []

    def send(*args, **kwargs):
        text = args[1] if len(args) > 1 else kwargs.get("text", "")
        sent.append(text or "")
        return types.SimpleNamespace(message_id=len(sent))

    monkeypatch.setattr(bot_FINAL_GOLD.bot, "send_message", send)
    chat_id = 818181
    message = types.SimpleNamespace(
        text="/help",
        chat=types.SimpleNamespace(id=chat_id),
        from_user=types.SimpleNamespace(id=chat_id, first_name="Т", last_name="", username="u"),
    )
    bot_FINAL_GOLD.send_help(message)
    assert "едином реестре всех СРО" in sent[-1]
    sent.clear()
    bot_FINAL_GOLD.send_welcome(message)
    assert "во всех СРО, не только у 15 партнёров" in sent[-1]
