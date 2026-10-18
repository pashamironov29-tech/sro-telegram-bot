"""Мелкие находки ревью S4–S13."""

from __future__ import annotations

import json
import threading
import time
import types
from datetime import datetime

import log_redact

_real_install = log_redact.install_secret_log_redaction
log_redact.install_secret_log_redaction = lambda *a, **k: None  # type: ignore[method-assign]
import bot_FINAL_GOLD  # noqa: E402

log_redact.install_secret_log_redaction = _real_install

import bot_MAX  # noqa: E402
import feedback_log  # noqa: E402
import reestr_sync  # noqa: E402

_REAL_MAX_SEND = bot_MAX.send
from contacts_search import format_directory_search_results  # noqa: E402
from docx import Document  # noqa: E402
from max_api import MaxApiError  # noqa: E402
from partners_data import _normalize as partner_norm  # noqa: E402
from partners_data import format_partner_response  # noqa: E402
from sro_contacts import format_sro_contacts  # noqa: E402
from sro_site_qa import _normalize as site_norm  # noqa: E402
from sro_site_qa import format_sro_site_qa_response  # noqa: E402
from tests.support import TEST_UID  # noqa: E402
from users_log import format_users_report, touch_user  # noqa: E402
from voprosy_faq import _normalize as faq_norm  # noqa: E402
from voprosy_faq import (  # noqa: E402
    format_scope_mismatch_response,
    format_voprosy_faq_response,
    match_voprosy_faq,
)

INJECT = "<img src=x>"


def _no_raw_tag(text: str) -> None:
    assert "&lt;img" in text
    assert INJECT not in text


def test_user_question_is_escaped_in_html_answers():
    item = {
        "label": "Метка",
        "short": "Кратко",
        "menu_hint": "",
        "scopes": ["proekt"],
    }
    _no_raw_tag(format_voprosy_faq_response(INJECT, item)["text"])
    _no_raw_tag(format_scope_mismatch_response(INJECT, "stroy", item)["text"])
    _no_raw_tag(format_partner_response(INJECT, {"type": "all"})["text"])
    _no_raw_tag(
        format_partner_response(
            INJECT,
            {"type": "one", "item": {"name": "НОСО", "url": "https://example.test", "phone": "", "email": ""}},
        )["text"]
    )
    _no_raw_tag(format_sro_contacts("OGPS", question=INJECT) or "")
    _no_raw_tag(
        format_sro_site_qa_response(
            INJECT,
            {"short": "Кратко", "links": (("Сайт", "https://example.test"),)},
        )["text"]
    )
    _no_raw_tag(format_directory_search_results(INJECT, []))
    many = format_directory_search_results(
        INJECT,
        [
            {"department": "Отдел", "name": "А", "role": "", "block": "блок"},
            {"department": "Отдел", "name": "Б", "role": "", "block": "блок"},
        ],
    )
    _no_raw_tag(many)


def test_users_report_escapes_name_and_username():
    message = types.SimpleNamespace(
        chat=types.SimpleNamespace(id=77),
        from_user=types.SimpleNamespace(
            id=77, first_name="<admin>", last_name="", username="a<b>"
        ),
    )
    touch_user(message, event="start")
    report = format_users_report()
    assert "<b>&lt;admin&gt;</b>" in report
    assert "(@a&lt;b&gt;)" in report
    assert "<b><admin></b>" not in report


def test_yo_becomes_cyrillic_e_and_matches_faq():
    cyr_e = "е"
    assert faq_norm("учёт") == "учет"
    assert faq_norm("ё") == cyr_e
    assert ord(faq_norm("Учёт")[2]) == ord(cyr_e)
    assert partner_norm("партнёр")[5] == cyr_e
    assert site_norm("ёлка")[0] == cyr_e
    found = match_voprosy_faq("учёт расходов по налогу")
    assert found and "налогов" in found["label"].lower()


def test_max_menu_and_help_are_not_welcome(max_bot):
    max_bot.m.handle_text(TEST_UID, "меню", {})
    blob = max_bot.blob()
    assert "Главное меню" in blob
    assert "С чего начать" not in blob

    max_bot.clear()
    max_bot.m.handle_text(TEST_UID, "help", {})
    blob = max_bot.blob()
    assert "Справка — Помощник СРО" in blob
    assert "С чего начать" not in blob


def test_one_user_does_not_fill_the_pool(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    import bot_MAX

    release = threading.Event()
    got_a = threading.Event()
    got_b = threading.Event()

    def runner(update):
        mark = update["mark"]
        if mark == "A1":
            got_a.set()
            release.wait(3)
        if mark == "B":
            got_b.set()

    monkeypatch.setattr(bot_MAX, "_run_dispatched_update", runner)
    light = ThreadPoolExecutor(max_workers=2)
    heavy = ThreadPoolExecutor(max_workers=1)

    def upd(uid, mark):
        return {
            "update_type": "message_created",
            "mark": mark,
            "message": {"sender": {"user_id": uid}, "body": {"text": mark}},
        }

    try:
        bot_MAX.enqueue_user_update(upd(1, "A1"), light_pool=light, heavy_pool=heavy)
        assert got_a.wait(2)
        bot_MAX.enqueue_user_update(upd(1, "A2"), light_pool=light, heavy_pool=heavy)
        bot_MAX.enqueue_user_update(upd(2, "B"), light_pool=light, heavy_pool=heavy)
        assert got_b.wait(1)
    finally:
        release.set()
        light.shutdown(wait=True, cancel_futures=True)
        heavy.shutdown(wait=True, cancel_futures=True)
        with bot_MAX._user_update_guard:
            bot_MAX._user_update_queues.clear()
            bot_MAX._user_update_busy.clear()


def test_plain_fallback_drops_attachments_that_cause_400(max_bot, monkeypatch):
    calls = []

    class Api:
        def send_message(self, **kwargs):
            calls.append(kwargs)
            if kwargs.get("attachments"):
                raise MaxApiError("attachment", status=400)
            return {"ok": True}

    monkeypatch.setattr(bot_MAX, "api", Api())
    _REAL_MAX_SEND(TEST_UID, "<b>текст</b>", [{"type": "inline_keyboard"}])
    assert any(call.get("attachments") is None for call in calls)
    assert calls[-1].get("format") is None


def test_plain_fallback_keeps_attachments_when_html_is_the_problem(max_bot, monkeypatch):
    calls = []

    class Api:
        def send_message(self, **kwargs):
            calls.append(kwargs)
            # MaxApi по умолчанию шлёт format=html, даже если вызывающий его не передал.
            if kwargs.get("format", "html") == "html":
                raise MaxApiError("html", status=400)
            return {"ok": True}

    monkeypatch.setattr(bot_MAX, "api", Api())
    buttons = [{"type": "inline_keyboard"}]
    _REAL_MAX_SEND(TEST_UID, "<b>текст</b>", buttons)
    assert calls[-1].get("attachments") == buttons
    assert calls[-1].get("format") is None


def test_feedback_ignores_menu_button_and_expires(monkeypatch):
    chat_id = 4242
    feedback_log.remember_ai_reply(
        chat_id, question="вопрос", answer_text="ответ", route="faq", sro_id=None
    )
    assert feedback_log.begin_await_expected(chat_id)
    sent = []
    monkeypatch.setattr(bot_FINAL_GOLD.bot, "send_message", lambda *a, **k: sent.append(k or a))
    message = types.SimpleNamespace(
        text=bot_FINAL_GOLD.SEARCH_ORG_BUTTON,
        chat=types.SimpleNamespace(id=chat_id),
        from_user=types.SimpleNamespace(id=chat_id, first_name="А", last_name="", username="u"),
    )
    bot_FINAL_GOLD.handle_text(message)
    raw = ""
    if feedback_log.FEEDBACK_FILE.is_file():
        raw = feedback_log.FEEDBACK_FILE.read_text(encoding="utf-8")
    assert "Поиск организации" not in raw
    assert not feedback_log.is_awaiting_expected(chat_id)

    feedback_log.remember_ai_reply(
        chat_id, question="вопрос", answer_text="ответ", route="faq", sro_id=None
    )
    feedback_log.begin_await_expected(chat_id)
    feedback_log._await_expected[chat_id] = time.time() - feedback_log.AWAIT_TTL_SEC - 5
    assert feedback_log.is_awaiting_expected(chat_id) is False


def test_corrupt_users_journal_is_quarantined(tmp_path, monkeypatch):
    import users_log

    path = tmp_path / "bot_users.json"
    monkeypatch.setattr(users_log, "USERS_FILE", path)
    original = (
        json.dumps(
            {"users": {"5": {"chat_id": 5, "full_name": "Живой", "username": "ok"}}},
            ensure_ascii=False,
        )
        + "\nNOT JSON"
    )
    path.write_text(original, encoding="utf-8")
    message = types.SimpleNamespace(
        chat=types.SimpleNamespace(id=9),
        from_user=types.SimpleNamespace(id=9, first_name="Новый", last_name="", username="n"),
    )
    assert touch_user(message) is True
    bad = list(path.parent.glob("bot_users.json.bad-*"))
    assert len(bad) == 1
    assert bad[0].read_text(encoding="utf-8") == original
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["users"]["9"]["full_name"] == "Новый"


def test_plan_year_is_taken_at_format_time_and_from_filename(monkeypatch, tmp_path):
    class Clock:
        @staticmethod
        def now(tz=None):
            return datetime(2031, 1, 5)

    monkeypatch.setattr(reestr_sync, "datetime", Clock)
    assert reestr_sync._format_plan_month("март") == "март 2031"
    assert reestr_sync._format_plan_month("март 2024") == "март 2024"

    plany = tmp_path / "plany"
    plany.mkdir()
    doc = Document()
    table = doc.add_table(rows=0, cols=3)
    row = table.add_row()
    row.cells[0].text = "Февраль"
    row = table.add_row()
    row.cells[0].text = "ООО Год"
    row.cells[1].text = "7700000099"
    doc.save(plany / "OGPS_2025.docx")
    data = bot_FINAL_GOLD.load_plany_folder(str(plany))
    assert "2025" in data["7700000099"]["month"]
    assert "2031" not in data["7700000099"]["month"]


def test_admin_alert_truncation_finishes():
    event = types.SimpleNamespace(
        chat=types.SimpleNamespace(id=1),
        from_user=types.SimpleNamespace(
            id=1, first_name="<" * 80, last_name="", username="u"
        ),
        text="<" * 500,
    )
    try:
        raise ValueError("<" * 400)
    except ValueError as exc:
        error = exc
    done: list[bool] = []

    def run():
        bot_FINAL_GOLD.notify_admins_about_error("shrink-probe", event, error)
        done.append(True)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(2)
    assert not worker.is_alive()
    assert done
