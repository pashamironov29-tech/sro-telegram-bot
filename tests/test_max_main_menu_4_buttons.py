"""Главное меню MAX: 4 крупные кнопки, те же подписи, что в Telegram; старые — алиасы."""

from __future__ import annotations

import pytest

from menu_labels import LEGACY_MENU_ALIASES, MENU_LABELS
from tests.support import TEST_UID, keyboard_buttons

NEW_LABELS = [
    "🔎 Поиск организации в СРО",
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


def test_controller_keyboard_same_four_rows(max_bot):
    kb = max_bot.m.controller_keyboard(TEST_UID)
    assert _rows(kb) == [[(l, p)] for l, p in zip(NEW_LABELS, PAYLOADS)]


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
