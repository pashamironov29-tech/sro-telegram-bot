"""Главное меню MAX: 4 крупные кнопки, те же подписи, что в Telegram; старые — алиасы."""

from __future__ import annotations

import pytest

from menu_labels import LEGACY_MENU_ALIASES, MENU_LABELS
from tests.support import TEST_UID, keyboard_buttons

NEW_LABELS = [
    "🔎 Поиск организации в СРО / Checko",
    "✅ Проверить НРС (НОСТРОЙ / НОПРИЗ)",
    "👤 Где работает специалист (по ФИО)",
    "🏢 Поиск организации в НОСТРОЙ / НОПРИЗ",
]
PAYLOADS = ["menu:search", "menu:nrs", "menu:spec", "menu:nat"]
LABEL_TO_OPENER = dict(zip(NEW_LABELS, ["open_search", "open_nrs", "open_specialist", "open_national"]))


def _rows(attachments) -> list[list[tuple[str, str]]]:
    rows = []
    for att in attachments:
        for row in att["payload"]["buttons"]:
            rows.append([(b["text"], b.get("payload", "")) for b in row])
    return rows


def test_labels_shared_with_telegram():
    assert list(MENU_LABELS) == NEW_LABELS


def test_main_keyboard_four_full_width_rows(max_bot):
    rows = _rows(max_bot.m.main_keyboard(TEST_UID))
    assert rows == [[(l, p)] for l, p in zip(NEW_LABELS, PAYLOADS)]


def test_no_fifth_button_and_no_controller_menu(max_bot):
    assert len(_rows(max_bot.m.main_keyboard(TEST_UID))) == 4
    assert len(_rows(max_bot.m.main_keyboard(1))) == 4
    assert not hasattr(max_bot.m, "controller_keyboard")


def test_card_keyboard_adds_checko_row_above_four_buttons(max_bot, config_stub, monkeypatch):
    monkeypatch.setattr(config_stub, "CHECKO_API_KEY", "test-fake-checko-key")
    rows = _rows(max_bot.m.card_keyboard("7700000001"))
    assert rows[0] == [("📋 Проверить в Checko", "chk:f:7700000001")]
    assert rows[1:] == [[(l, p)] for l, p in zip(NEW_LABELS, PAYLOADS)]


def test_old_search_label_is_alias():
    assert LEGACY_MENU_ALIASES["🔎 Поиск организации в СРО"] == NEW_LABELS[0]


@pytest.mark.parametrize("label", NEW_LABELS)
def test_typed_new_label_routes(max_bot, monkeypatch, label):
    calls = []
    for name in LABEL_TO_OPENER.values():
        monkeypatch.setattr(max_bot.m, name, lambda uid, _n=name: calls.append(_n))
    max_bot.m.handle_text(TEST_UID, label, {})
    assert calls == [LABEL_TO_OPENER[label]]


@pytest.mark.parametrize("old,new", list(LEGACY_MENU_ALIASES.items()))
def test_typed_legacy_label_routes(max_bot, monkeypatch, old, new):
    calls = []
    for name in LABEL_TO_OPENER.values():
        monkeypatch.setattr(max_bot.m, name, lambda uid, _n=name: calls.append(_n))
    max_bot.m.handle_text(TEST_UID, old, {})
    assert calls == [LABEL_TO_OPENER[new]]


@pytest.mark.parametrize("payload", PAYLOADS)
def test_old_inline_buttons_payloads_still_work(max_bot, monkeypatch, payload):
    """Кнопки из старых сообщений несут те же callback-payload."""
    calls = []
    for name in LABEL_TO_OPENER.values():
        monkeypatch.setattr(max_bot.m, name, lambda uid, _n=name: calls.append(_n))
    max_bot.m.handle_callback(TEST_UID, payload, {})
    assert calls == [LABEL_TO_OPENER[NEW_LABELS[PAYLOADS.index(payload)]]]
