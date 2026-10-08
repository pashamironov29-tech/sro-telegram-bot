"""Поиск организации по ИНН в Telegram-оболочке (bot_FINAL_GOLD.py), через подпроцесс."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

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


def test_tg_inn_in_several_sro(tg_results):
    case = tg_results[0]["multi"]
    blob = _blob(case)
    assert "<b>ОГПС</b>" in blob
    assert "<b>МОТС</b>" in blob
    assert "Организация состоит в нескольких СРО" in blob
    assert case["pending"] == ["OGPS", "MOTS"]
    labels = _markup(case)
    assert sum(1 for label in labels if label.startswith("📄 СРО — ")) == 2


def test_tg_present_absent_returns_none(tg_results):
    case = tg_results[0]["present_absent"]
    assert case["ret"] is None
    assert case["sent"] == []


def test_tg_looks_like_inn(tg_results):
    assert tg_results[0]["looks_like_inn"]["ret"] == [True, True, False, False]


def test_tg_probe_writes_only_to_tmp(tg_results):
    allowed = {"bot_users.json", "user_sro_context_tg.json", "nrs_link_mode_tg.json"}
    assert set(tg_results[1]) <= allowed
