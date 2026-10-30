"""Поиск организации по ИНН в Telegram-оболочке (bot_FINAL_GOLD.py), через подпроцесс."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

SPECIALIST_BUTTON = "👤 Где работает специалист (НОСТРОЙ/НОПРИЗ)"
from tests.support import FAKE_TG_TOKEN, INN_ABSENT, ROOT

PROBE = ROOT / "tests" / "tg_search_probe.py"


@pytest.fixture(scope="module")
def tg_results(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("tg-probe")
    env = dict(os.environ, PYTHONIOENCODING="utf-8", BOT_PLATFORM="tg")
    proc = subprocess.run(
        [sys.executable, str(PROBE), str(tmp)],
        cwd=tmp,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    out = proc.stdout
    assert proc.returncode == 0, out + proc.stderr
    assert FAKE_TG_TOKEN.split(":", 1)[1] not in out + proc.stderr
    begin = out.index("<<<TG_PROBE_JSON>>>") + len("<<<TG_PROBE_JSON>>>")
    end = out.index("<<<END_TG_PROBE_JSON>>>")
    leftovers = sorted(p.name for p in tmp.iterdir() if p.name != "sro files")
    return json.loads(out[begin:end]), leftovers


def _blob(case: dict) -> str:
    return "\n".join(item["text"] for item in case["sent"])


def _markup(case: dict) -> list[str]:
    return [s for item in case["sent"] for s in item["markup"]]


@pytest.mark.parametrize("case_name", ["found", "found_spaces"])
def test_tg_inn_found(tg_results, case_name):
    case = tg_results[0][case_name]
    blob = _blob(case)
    assert "✅ <b>ООО «Тестстрой»</b>" in blob
    assert "<b>ОГПС</b>" in blob
    assert case["sro_id"] == "OGPS"
    assert case["search_mode"] is False


def test_tg_inn_12_digits_found(tg_results):
    assert "ИП Пробный П.П." in _blob(tg_results[0]["found_ip"])


def test_tg_inn_not_found(tg_results):
    blob = _blob(tg_results[0]["not_found"])
    assert f"Организация с ИНН <code>{INN_ABSENT}</code>" in blob
    assert "не найдена в базе бота" in blob


@pytest.mark.parametrize("raw", ["12345678", "1234567890123", "77000O0001"])
def test_tg_malformed_inn(tg_results, raw):
    blob = _blob(tg_results[0][f"malformed:{raw}"])
    assert f"По запросу «<b>{raw}</b>» организация в базе не найдена" in blob
    assert "✅" not in blob


def test_tg_short_query(tg_results):
    assert "Введите <b>ИНН</b> (9–12 цифр)" in _blob(tg_results[0]["short"])


MAIN_LABELS = [
    "🔎 Поиск организации в СРО / Checko",
    "✅ Проверить НРС (НОСТРОЙ / НОПРИЗ)",
    "👤 Где работает специалист (НОСТРОЙ/НОПРИЗ)",
    "🏢 Поиск организации в НОСТРОЙ / НОПРИЗ",
]
OLD_TEXTS = (
    "Другой ИНН / без ИНН",
    "Назад в меню",
    "Назад к выбору организации",
    "Сменить СРО",
    "Организация состоит в нескольких СРО",
)


def test_tg_inn_in_several_sro(tg_results):
    """Организация в двух СРО: карточка со всеми СРО, без выбора СРО, клавиатура — 4 кнопки."""
    case = tg_results[0]["multi"]
    blob = _blob(case)
    assert "<b>ОГПС</b>" in blob
    assert "<b>МОТС</b>" in blob
    for old in OLD_TEXTS:
        assert old not in blob
    assert not case["pending"]
    assert case["sro_id"] is None
    labels = _markup(case)
    assert labels == MAIN_LABELS
    assert not any(label.startswith("📄 СРО — ") for label in labels)
    assert not any(old in label for label in labels for old in OLD_TEXTS)


def test_tg_multi_sro_blanks_ask_inline_only_on_open(tg_results):
    case = tg_results[0]["multi_blanks"]
    assert case["ret"] is True
    assert case["sro_id"] is None
    assert "Бланки — какого СРО" in _blob(case)
    markup = _markup(case)
    assert any(m.startswith("ctxset:OGPS:info_list") for m in markup)
    assert any(m.startswith("ctxset:MOTS:info_list") for m in markup)


def test_tg_multi_sro_ctxset_callback_sets_sro(tg_results):
    case = tg_results[0]["multi_ctxset"]
    assert case["sro_id"] == "MOTS"
    assert "Бланки:" in _blob(case)
    assert not case["pending"]


def test_tg_multi_sro_card_has_checko_button_when_configured(tg_results):
    case = tg_results[0]["multi_checko"]
    markup = _markup(case)
    assert "📋 Проверить в Checko" in markup
    assert any(m.startswith("chk:f:") for m in markup)
    assert not case["pending"]
    assert not any("Назад в меню" in m or "Другой ИНН" in m for m in markup)


def test_tg_absent_inn_offers_checko_to_everyone(tg_results):
    case = tg_results[0]["absent_checko"]
    assert "в реестре 15 СРО не найден" in _blob(case)
    assert any(m.startswith("chk:f:") for m in _markup(case))


def test_tg_card_without_checko_has_no_checko_button(tg_results):
    markup = _markup(tg_results[0]["multi"])
    assert not any(m.startswith("chk:") for m in markup)


def test_tg_present_absent_returns_none(tg_results):
    case = tg_results[0]["present_absent"]
    assert case["ret"] is None
    assert case["sent"] == []


def test_tg_looks_like_inn(tg_results):
    assert tg_results[0]["looks_like_inn"]["ret"] == [True, True, False, False]


def test_tg_probe_writes_only_to_tmp(tg_results):
    allowed = {
        "bot_users.json",
        "bot_users.json.lock",
        "bot_users.sqlite",
        "bot_users.sqlite-wal",
        "bot_users.sqlite-shm",
        "user_sro_context_tg.json",
        "nrs_link_mode_tg.json",
        "specialist_mode_tg.json",
        "national_mode_tg.json",
        "session_state_tg.json",
        "specialists.sqlite",
        "specialists.sqlite-wal",
        "specialists.sqlite-shm",
    }
    assert set(tg_results[1]) <= allowed


def test_tg_specialist_button_and_fio(tg_results):
    blob = _blob(tg_results[0]["specialist"])
    assert "Поиск специалиста по ФИО" in blob
    assert "Сидоров Пётр Сергеевич" in blob
    assert "С-77-100001" in blob
    assert "ООО Проба" in blob
    assert "reestr.nostroy.ru/member/10" in blob
    assert tg_results[0]["specialist"]["specialist_mode"] is True
    assert SPECIALIST_BUTTON in _markup(tg_results[0]["main_keyboard"])
