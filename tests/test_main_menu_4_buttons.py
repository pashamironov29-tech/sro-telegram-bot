"""Главное меню Telegram: 4 крупные кнопки, новые подписи, старые — алиасы."""

from __future__ import annotations

import types

import pytest

import log_redact

_real_install = log_redact.install_secret_log_redaction
log_redact.install_secret_log_redaction = lambda *a, **k: None  # type: ignore[method-assign]
import bot_FINAL_GOLD as tg  # noqa: E402

log_redact.install_secret_log_redaction = _real_install

NEW_LABELS = [
    "🔎 Поиск организации в СРО",
    "✅ Проверить НРС (НОСТРОЙ / НОПРИЗ)",
    "👤 Где работает специалист (по ФИО)",
    "🏢 Поиск организации в НОСТРОЙ / НОПРИЗ",
]

# старые подписи -> новая (клавиатура у пользователя может быть старой)
LEGACY = {
    "🔍 Поиск организации": NEW_LABELS[0],
    "👤 Проверить в НРС": NEW_LABELS[1],
    "👤 НРС ссылка (пилот)": NEW_LABELS[1],
    "🔎 Поиск специалиста по ФИО": NEW_LABELS[2],
    "🏛 Поиск в НОСТРОЙ / НОПРИЗ": NEW_LABELS[3],
}


def _msg(chat_id: int, text: str):
    return types.SimpleNamespace(
        text=text,
        chat=types.SimpleNamespace(id=chat_id),
        from_user=types.SimpleNamespace(id=chat_id, first_name="Т", last_name="", username="u"),
    )


def _rows(markup) -> list[list[str]]:
    return [
        [b["text"] if isinstance(b, dict) else b.text for b in row]
        for row in markup.keyboard
    ]


@pytest.fixture
def routed(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(tg, "_open_org_search", lambda cid: calls.append("org_sro"))
    monkeypatch.setattr(tg, "open_specialist_search", lambda cid: calls.append("specialist"))
    monkeypatch.setattr(tg, "open_national_search", lambda cid: calls.append("national"))
    monkeypatch.setattr(tg, "prepare_nrs", lambda cid: calls.append("nrs"))
    monkeypatch.setattr(tg, "finish_button_reply", lambda *a, **k: None)
    monkeypatch.setattr(tg.bot, "send_message", lambda *a, **k: types.SimpleNamespace(message_id=1))
    monkeypatch.setattr(tg.bot, "send_chat_action", lambda *a, **k: None)
    return calls


def test_main_keyboard_is_four_full_width_buttons():
    markup = tg.get_main_keyboard(818181)
    assert _rows(markup) == [[label] for label in NEW_LABELS]
    assert markup.resize_keyboard is True


def test_controller_keyboard_same_four_buttons():
    assert _rows(tg.get_controller_keyboard(818181)) == [[label] for label in NEW_LABELS]


def test_constants_match_labels():
    assert [
        tg.SEARCH_ORG_BUTTON,
        tg.NRS_LINK_BUTTON,
        tg.SPECIALIST_BUTTON,
        tg.NATIONAL_BUTTON,
    ] == NEW_LABELS


@pytest.mark.parametrize(
    "label,expected",
    list(zip(NEW_LABELS, ["org_sro", "nrs", "specialist", "national"])),
)
def test_new_labels_route_to_handlers(routed, label, expected):
    tg.handle_text(_msg(818182, label))
    assert routed == [expected]


@pytest.mark.parametrize("old,new", list(LEGACY.items()))
def test_legacy_labels_still_route(routed, old, new):
    expected = dict(zip(NEW_LABELS, ["org_sro", "nrs", "specialist", "national"]))[new]
    assert tg.normalize_menu_label(old) == new
    tg.handle_text(_msg(818183, old))
    assert routed == [expected]


def test_menu_labels_are_not_treated_as_nrs_query():
    for label in [*NEW_LABELS, *LEGACY]:
        assert tg._is_reply_menu_button(label)
