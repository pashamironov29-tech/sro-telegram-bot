"""Меню MAX: кейсы из scripts/check_max_menu.py без сети и без рассылки."""

from __future__ import annotations

import pytest

from checko_client import SECTIONS as CHECKO_SECTIONS
from nrs_search_links import nrs_registry_link_buttons
from tests.support import TEST_UID, keyboard_buttons

UID = TEST_UID
CHECKO_INN = "7700000001"

NOK_TOPICS = {
    # тема: (должно быть, не должно быть — признак соседней кнопки)
    "nrs_docs": ("Документы для внесения в НРС", "Кураторы по вопросам НРС"),
    "nrs_cur": ("Кураторы по вопросам НРС", "Нотариальная копия"),
    "nok_rules": ("Правила независимой оценки", "480 тестовых"),
    "nok_prep": ("курс подготовки к НОК", "не реже одного раза в 5 лет"),
}

FAQ_TOPICS = {
    "specs": "Требования к специалистам",
    "join_docs": "Пакет документов для вступления",
    "how": "вступ",
    "terms": "срок",
    "extract": "выписк",
    "changes": "изменен",
    "schedule": "проверя",
    "violations": "нарушен",
    "laws": "Нормативно-правовая",
    "refund": "Возврат взноса",
    "own": "собственных нужд",
    "lk": "кабинет",
    "about": "Ассоциац",
    "trusted": "известные компании",
    "partners": "Партнёр",
    "regions": "Филиал",
    "feedback": "Жалоб",
    "charity": "Благотворит",
    "fees": "взнос",
}


def _first_text(max_bot) -> str:
    texts = max_bot.texts()
    assert texts, "нет ответа"
    return texts[0]


@pytest.mark.parametrize("topic", list(NOK_TOPICS))
def test_nok_buttons_open_own_text(max_bot, topic):
    must, must_not = NOK_TOPICS[topic]
    max_bot.m.send_faq_topic(UID, topic)

    text = _first_text(max_bot)
    assert must.lower() in text.lower()
    assert must_not.lower() not in text.lower()


@pytest.mark.parametrize("topic", list(FAQ_TOPICS))
def test_faq_topic_has_text(max_bot, topic):
    max_bot.m.send_faq_topic(UID, topic)

    text = _first_text(max_bot)
    if topic not in ("how", "fees", "about"):
        assert "готовится" not in text.lower()
    assert FAQ_TOPICS[topic].lower() in text.lower()


MENU_ROUTES = [
    ("menu:search", "ИНН"),
    ("menu:info", "Полезная информация"),
    ("menu:help", "Справка"),
    ("menu:nrs", "НРС"),
    ("faq:root", "FAQ"),
    ("faq:join", "Для вступающих"),
    ("faq:members", "Действующим членам"),
    ("faq:nok", "Специалисты и НОК"),
    ("faq:assoc", "Ассоциация"),
]


@pytest.mark.parametrize(("payload", "needle"), MENU_ROUTES)
def test_menu_payload_opens_screen(max_bot, payload, needle):
    max_bot.m.handle_callback(UID, payload, {})
    assert needle.lower() in max_bot.blob().lower()


def test_menu_controller_for_controller(max_bot, max_controller):
    max_bot.m.handle_callback(max_controller, "menu:controller", {})
    assert "Меню контролёра" in max_bot.blob()


def test_menu_controller_refused_for_member(max_bot):
    max_bot.m.handle_callback(UID, "menu:controller", {})
    blob = max_bot.blob()
    assert "только для сотрудников контроля СРО" in blob
    assert "Меню контролёра" not in blob


def test_nok_keyboard_buttons(max_bot):
    buttons = keyboard_buttons(max_bot.m.faq_nok_keyboard())
    labels = [text for _kind, text, _p in buttons]
    for need in ("Документы в НРС", "Кураторы НРС", "Правила НОК", "Подготовка к НОК"):
        assert any(need in label for label in labels), need
    by_payload = {p: t for kind, t, p in buttons if kind == "callback"}
    assert "Документы" in by_payload["faq:nrs_docs"]
    assert "Кураторы" in by_payload["faq:nrs_cur"]


@pytest.mark.parametrize(
    ("query", "expect"),
    [
        ("С-55-267917", "nostroy"),
        ("C-BY-260757", "nostroy"),
        ("П-122864", "nopriz"),
        ("ПИ-083721", "nopriz"),
        ("Иванов Иван Иванович", "both"),
    ],
)
def test_nrs_buttons_lead_to_own_registry(query, expect):
    buttons = nrs_registry_link_buttons(query)
    nostroy = [u for label, u in buttons if "НОСТРОЙ" in label]
    nopriz = [u for label, u in buttons if "НОПРИЗ" in label]
    if expect == "nostroy":
        assert len(nostroy) == 1 and not nopriz
        assert "nrs.nostroy.ru" in nostroy[0] and "nopriz" not in nostroy[0]
    elif expect == "nopriz":
        assert len(nopriz) == 1 and not nostroy
        assert "nrs.nopriz.ru" in nopriz[0] and "nostroy" not in nopriz[0]
    else:
        assert len(nostroy) == 1 and len(nopriz) == 1
        assert "nrs.nostroy.ru" in nostroy[0]
        assert "nrs.nopriz.ru" in nopriz[0]
        assert nostroy[0] != nopriz[0]


def test_checko_keyboard_has_each_section_once(max_bot):
    buttons = keyboard_buttons(max_bot.m.checko_sections_keyboard(CHECKO_INN))
    seen: dict[str, str] = {}
    for kind, text, payload in buttons:
        if kind != "callback" or not payload.startswith("chk:s:"):
            continue
        _chk, _s, code, inn = payload.split(":")
        assert inn == CHECKO_INN
        assert code not in seen, f"секция {code} на двух кнопках"
        seen[code] = text
    assert set(seen) == {code for code, _label, _method in CHECKO_SECTIONS}


@pytest.fixture
def checko_controller(max_bot, max_controller, monkeypatch):
    """Контролёр в кабинете, Checko подменён: в сеть не ходим."""
    monkeypatch.setattr(
        max_bot.m,
        "format_checko_section",
        lambda section, inn: f"CHECKO_SECTION={section}|INN={inn}",
    )
    max_bot.m.handle_text(max_controller, "/controller", {})
    max_bot.clear()
    return max_controller


@pytest.mark.parametrize(("code", "label"), [(c, label) for c, label, _m in CHECKO_SECTIONS])
def test_checko_section_button_opens_section(max_bot, checko_controller, code, label):
    max_bot.m.handle_checko(checko_controller, f"chk:s:{code}:{CHECKO_INN}")

    blob = max_bot.blob()
    assert f"CHECKO_SECTION={code}" in blob, label
    assert f"INN={CHECKO_INN}" in blob


def test_checko_full_info_opens_general(max_bot, checko_controller):
    max_bot.m.handle_checko(checko_controller, f"chk:f:{CHECKO_INN}")
    assert "CHECKO_SECTION=general" in max_bot.blob()


def test_checko_refused_outside_controller(max_bot):
    max_bot.m.handle_checko(UID, f"chk:s:general:{CHECKO_INN}")
    assert "Checko доступен в /controller" in max_bot.blob()


def test_command_start(max_bot):
    max_bot.m.handle_text(UID, "/start", {})
    blob = max_bot.blob()
    assert "ИНН" in blob or "СРО" in blob


def test_command_search(max_bot):
    max_bot.m.handle_text(UID, "/search", {})
    assert "ИНН" in max_bot.blob()


def test_command_info(max_bot):
    max_bot.m.handle_text(UID, "/info", {})
    assert "Полезная информация" in max_bot.blob()


def test_command_controller_for_controller(max_bot, max_controller):
    max_bot.m.handle_text(max_controller, "/controller", {})
    assert "контролёр" in max_bot.blob().lower()


def test_command_controller_refused_for_member(max_bot):
    max_bot.m.handle_text(UID, "/controller", {})
    assert "только для сотрудников контроля СРО" in max_bot.blob()
