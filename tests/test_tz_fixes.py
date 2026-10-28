"""По одной проверке на правку из ТЗ: до правки тест падал."""

from __future__ import annotations

import json
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import log_redact

_real_install = log_redact.install_secret_log_redaction
log_redact.install_secret_log_redaction = lambda *a, **k: None  # type: ignore[method-assign]
import bot_FINAL_GOLD  # noqa: E402

log_redact.install_secret_log_redaction = _real_install

import bot_MAX  # noqa: E402
import checko_client  # noqa: E402
import feedback_log  # noqa: E402
import info_list_fill  # noqa: E402
import nrs_search_links  # noqa: E402
import requests  # noqa: E402
import site_health_check  # noqa: E402
from blanki_sro import blanki_file_path  # noqa: E402
from local_answers import enter_search_mode, is_search_mode  # noqa: E402
from tests.support import (  # noqa: E402
    FAKE_TG_TOKEN,
    INN_SINGLE,
    TEST_UID,
    read_fixture,
    sample_reestr,
)
import reestr_sync  # noqa: E402
import sro_context  # noqa: E402


def _text_message(chat_id: int, text: str):
    return types.SimpleNamespace(
        text=text,
        chat=types.SimpleNamespace(id=chat_id),
        from_user=types.SimpleNamespace(
            id=chat_id, first_name="Тест", last_name="", username="u"
        ),
    )


def _capture_tg_send(monkeypatch):
    sent: list[str] = []

    def send(chat_id, text, **kwargs):
        sent.append(text or "")
        return types.SimpleNamespace(message_id=len(sent))

    monkeypatch.setattr(bot_FINAL_GOLD.bot, "send_message", send)
    monkeypatch.setattr(bot_FINAL_GOLD.bot, "send_chat_action", lambda *a, **k: None)
    return sent


def _keyboard_labels(markup) -> list[str]:
    labels = []
    for row in markup.keyboard:
        for button in row:
            labels.append(button["text"] if isinstance(button, dict) else button.text)
    return labels


def test_tg_start_welcome_is_main_menu(monkeypatch):
    sent: list[tuple[str, object]] = []

    def send(chat_id, text, **kwargs):
        sent.append((text or "", kwargs.get("reply_markup")))
        return types.SimpleNamespace(message_id=len(sent))

    monkeypatch.setattr(bot_FINAL_GOLD.bot, "send_message", send)
    chat_id = 616161
    sro_context.begin_await_inn(chat_id)
    bot_FINAL_GOLD.send_welcome(_text_message(chat_id, "/start"))

    text, markup = sent[-1]
    assert "Добро пожаловать в чат-бот реестра и сервисов СРО" in text
    assert "24/7" in text
    assert "Пропустить" not in text
    assert "775-81-11" in text
    assert _keyboard_labels(markup) == _keyboard_labels(
        bot_FINAL_GOLD.get_main_keyboard(chat_id)
    )
    assert sro_context.is_awaiting_inn(chat_id) is False

    sent.clear()
    bot_FINAL_GOLD.handle_text(_text_message(chat_id, bot_FINAL_GOLD.NRS_LINK_BUTTON))
    assert "Проверка в НРС" in sent[-1][0]
    sent.clear()
    bot_FINAL_GOLD.handle_text(_text_message(chat_id, bot_FINAL_GOLD.SEARCH_ORG_BUTTON))
    assert "Универсальный поиск" in sent[-1][0]
    sent.clear()
    bot_FINAL_GOLD.handle_text(
        _text_message(chat_id, bot_FINAL_GOLD.SPECIALIST_BUTTON)
    )
    assert "Поиск специалиста по ФИО" in sent[-1][0]


def test_onboarding_and_search_question_goes_to_answer(monkeypatch, max_bot):
    chat_id = 515151
    sent = _capture_tg_send(monkeypatch)
    sro_context.begin_await_inn(chat_id)
    bot_FINAL_GOLD.handle_text(_text_message(chat_id, "Что такое НОК?"))
    blob = "\n".join(sent)
    assert "не найдена в базе" not in blob
    assert sro_context.is_awaiting_inn(chat_id)
    assert is_search_mode(chat_id) is False

    sent.clear()
    sro_context.clear_await_inn(chat_id)
    enter_search_mode(chat_id)
    bot_FINAL_GOLD.handle_text(_text_message(chat_id, "Что такое НОК?"))
    assert "не найдена в базе" not in "\n".join(sent)
    assert is_search_mode(chat_id) is False

    max_bot.m.open_search(TEST_UID)
    assert is_search_mode(TEST_UID)
    max_bot.clear()
    max_bot.m.handle_text(TEST_UID, "Что такое НОК?", {})
    assert "не найдена в базе" not in max_bot.blob()
    assert is_search_mode(TEST_UID) is False


def test_split_director_acting_titles():
    raw = "Исполняющий обязанности Генерального директора Иванов Иван Иванович"
    position, fio = info_list_fill._split_director(raw)
    initials = info_list_fill._surname_initials(fio or raw)
    assert position == "Исполняющий обязанности Генерального директора"
    assert fio == "Иванов Иван Иванович"
    assert initials == "Иванов И.И."
    assert initials != "Исполняющий о.Г.д.И.И.И."

    position, fio = info_list_fill._split_director("и.о. директора Петров Пётр Петрович")
    assert position == "Исполняющий обязанности директора"
    assert fio == "Петров Пётр Петрович"

    position, fio = info_list_fill._split_director(
        "временно исполняющий обязанности директора Сидоров Сидор Сидорович"
    )
    assert position == "Временно исполняющий обязанности директора"
    assert fio == "Сидоров Сидор Сидорович"

    position, fio = info_list_fill._split_director(
        "Генеральный директор Образцов Олег Олегович"
    )
    assert position == "Генеральный директор"
    assert fio == "Образцов Олег Олегович"


def test_site_health_exceptions_hide_bot_token(capsys, monkeypatch):
    token_url = f"https://api.telegram.org/bot{FAKE_TG_TOKEN}/sendMessage"
    monkeypatch.setattr(site_health_check, "_bot_token", lambda: FAKE_TG_TOKEN)
    monkeypatch.setattr(site_health_check, "_admin_ids", lambda: [1])

    def post(url, json=None, timeout=None):
        raise RuntimeError(f"request failed: {url}")

    monkeypatch.setattr(site_health_check.requests, "post", post)
    site_health_check._send_telegram("проверка")
    out = capsys.readouterr().out
    assert FAKE_TG_TOKEN not in out
    assert "REDACTED" in out

    def get(url, **kwargs):
        raise RuntimeError(f"fail {token_url}")

    monkeypatch.setattr(site_health_check.requests, "get", get)
    _code, _body, err = site_health_check._get("https://example.test/")
    assert err is not None
    assert FAKE_TG_TOKEN not in err
    assert "REDACTED" in err


def test_stale_callback_still_sends_company_card(monkeypatch):
    saved = bot_FINAL_GOLD.reestr_database
    bot_FINAL_GOLD.reestr_database = sample_reestr()
    sent = _capture_tg_send(monkeypatch)

    def boom(*_a, **_k):
        raise RuntimeError("query is too old")

    monkeypatch.setattr(bot_FINAL_GOLD.bot, "answer_callback_query", boom)
    monkeypatch.setattr(bot_FINAL_GOLD.bot, "delete_message", lambda *_a, **_k: None)
    call = types.SimpleNamespace(
        id="cb-old",
        data=f"search_inn:{INN_SINGLE}",
        message=types.SimpleNamespace(
            message_id=3, chat=types.SimpleNamespace(id=77)
        ),
    )
    try:
        bot_FINAL_GOLD.handle_inline_search(call)
    finally:
        bot_FINAL_GOLD.reestr_database = saved
    blob = "\n".join(sent)
    assert "Тестстрой" in blob
    assert "внутренней ошибке" not in blob


def test_checko_section_error_is_caught(monkeypatch):
    sent = _capture_tg_send(monkeypatch)
    edits: list[str] = []

    def edit(text, chat_id, message_id, **kwargs):
        edits.append(text or "")
        return types.SimpleNamespace(message_id=message_id)

    monkeypatch.setattr(bot_FINAL_GOLD.bot, "edit_message_text", edit)

    def boom(_section, _inn):
        raise RuntimeError("checko down")

    monkeypatch.setattr(bot_FINAL_GOLD, "format_checko_section", boom)
    monkeypatch.setattr(bot_FINAL_GOLD.bot, "answer_callback_query", lambda *_a, **_k: None)
    call = types.SimpleNamespace(
        id="cb",
        data="chk:s:legal:7700000001",
        message=types.SimpleNamespace(
            message_id=1, chat=types.SimpleNamespace(id=77)
        ),
    )
    bot_FINAL_GOLD.handle_checko_callbacks(call)
    bot_FINAL_GOLD.wait_heavy_tasks()
    blob = "\n".join(sent + edits)
    assert "Ищу…" in blob
    assert "Не удалось загрузить раздел" in blob
    assert "внутренней ошибке" not in blob


def test_checko_log_does_not_print_chat_id(capsys, monkeypatch):
    chat_id = 900000111
    monkeypatch.setattr(
        bot_FINAL_GOLD, "format_checko_section", lambda _section, _inn: "раздел"
    )
    monkeypatch.setattr(
        bot_FINAL_GOLD.bot,
        "send_message",
        lambda *_a, **_k: types.SimpleNamespace(message_id=1),
    )
    monkeypatch.setattr(bot_FINAL_GOLD.bot, "answer_callback_query", lambda *_a, **_k: None)
    monkeypatch.setattr(bot_FINAL_GOLD.bot, "send_chat_action", lambda *_a, **_k: None)
    monkeypatch.setattr(
        bot_FINAL_GOLD.bot,
        "edit_message_text",
        lambda *_a, **_k: None,
    )
    for data in ("chk:f:7700000001", "chk:s:legal:7700000001"):
        call = types.SimpleNamespace(
            id="cb",
            data=data,
            message=types.SimpleNamespace(
                message_id=1, chat=types.SimpleNamespace(id=chat_id)
            ),
        )
        bot_FINAL_GOLD.handle_checko_callbacks(call)
    bot_FINAL_GOLD.wait_heavy_tasks()
    out = capsys.readouterr().out
    assert "chk:f" in out and "chk:s" in out
    assert str(chat_id) not in out
    assert "chat=" not in out


def test_last_ai_reply_expires():
    chat_id = 616161
    feedback_log.remember_ai_reply(
        chat_id, question="вопрос", answer_text="ответ", route="faq", sro_id=None
    )
    assert feedback_log.has_last_ai(chat_id)
    feedback_log._last_ai[chat_id]["ts"] = time.time() - feedback_log.LAST_AI_TTL_SEC - 5
    assert feedback_log.has_last_ai(chat_id) is False
    assert feedback_log.begin_await_expected(chat_id) is False
    assert feedback_log.append_feedback(chat_id, "ждали другое") is False


def test_max_card_failure_is_one_message(max_bot, monkeypatch):
    def broken(user_id, _inn):
        max_bot.m.send(
            user_id,
            "❌ Не удалось загрузить карточку организации. Попробуйте позже.",
        )
        return False

    monkeypatch.setattr(max_bot.m, "send_company_card", broken)
    max_bot.m.open_search(TEST_UID)
    max_bot.clear()
    max_bot.m.handle_text(TEST_UID, INN_SINGLE, {})
    blob = max_bot.blob()
    assert blob.count("Не удалось загрузить карточку") == 1
    assert "не найдена в базе" not in blob


def test_empty_user_update_queue_is_removed(monkeypatch):
    monkeypatch.setattr(bot_MAX, "_run_dispatched_update", lambda _update: None)
    pool = ThreadPoolExecutor(max_workers=1)
    uid = 909909
    update = {
        "update_type": "message_created",
        "message": {"sender": {"user_id": uid}, "body": {"text": "a"}},
    }
    try:
        bot_MAX.enqueue_user_update(update, light_pool=pool, heavy_pool=pool)
        pool.shutdown(wait=True)
        with bot_MAX._user_update_guard:
            assert uid not in bot_MAX._user_update_queues
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
        with bot_MAX._user_update_guard:
            bot_MAX._user_update_queues.pop(uid, None)
            bot_MAX._user_update_busy.discard(uid)


def test_max_name_search_says_list_is_incomplete(max_bot, monkeypatch):
    rows = [(f"7700000{i:03d}", f"ООО Номер {i}") for i in range(12)]
    monkeypatch.setattr(max_bot.m, "search_companies_by_name", lambda _q: rows)
    max_bot.m.open_search(TEST_UID)
    max_bot.clear()
    max_bot.m.handle_text(TEST_UID, "номер", {})
    blob = max_bot.blob()
    assert "не все" in blob
    assert "первые 10" in blob
    inns = [p for p in max_bot.callback_payloads() if p.startswith("inn:")]
    assert len(inns) == 10


def test_blanki_fallback_folder_is_checked(tmp_path):
    root = tmp_path / "sro files"
    fallback = root / "blanki"
    fallback.mkdir(parents=True)
    (fallback / "info_list.doc").write_bytes(b"doc")
    found = blanki_file_path(str(root), "OGPS", "info_list")
    assert found == str(fallback / "info_list.doc")


def test_fresh_member_status_beats_old_exclusion():
    restored = reestr_sync._prefer_membership(
        {"status": "Исключен", "sro_id": "OGPS"},
        {"status": "Член СРО", "sro_id": "OGPS"},
    )
    assert restored["status"] == "Член СРО"
    excluded = reestr_sync._prefer_membership(
        {"status": "Член СРО", "sro_id": "OGPS"},
        {"status": "Исключен", "sro_id": "OGPS"},
    )
    assert excluded["status"] == "Исключен"
    history = [
        {"date": "01.01.2020", "measure": "Исключение из членов СРО"},
        {"date": "01.06.2024", "measure": "Предупреждение"},
    ]
    assert reestr_sync._status_from_disciplinary(history) is None
    latest = [{"date": "01.06.2024", "measure": "Исключение из членов СРО"}]
    assert reestr_sync._status_from_disciplinary(latest) == "Исключен"

    kept = reestr_sync._prefer_membership(
        {
            "status": "Исключен",
            "sro_id": "OGPS",
            "disciplinary_measures": latest,
        },
        {"status": "Член СРО", "sro_id": "OGPS"},
    )
    assert kept["status"] == "Исключен"

    reinstated = reestr_sync._prefer_membership(
        {
            "status": "Исключен",
            "sro_id": "OGPS",
            "disciplinary_measures": history,
        },
        {"status": "Член СРО", "sro_id": "OGPS"},
    )
    assert reinstated["status"] == "Член СРО"


def test_checko_quota_counts_only_success(tmp_path, monkeypatch):
    monkeypatch.setattr(checko_client, "_data_dir", lambda: tmp_path)
    monkeypatch.setattr(checko_client, "_api_key", lambda: "test-fake-checko-key")
    calls = {"n": 0}

    class Resp:
        status_code = 200

        def json(self):
            return {"data": {"name": "ООО"}}

        def raise_for_status(self):
            return None

    def post(_url, json=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise requests.ConnectionError("down")
        return Resp()

    monkeypatch.setattr(checko_client.requests, "post", post)
    _body, err = checko_client.fetch_method("company", "7700000001")
    assert err
    assert checko_client.requests_used_today() == 0
    body, err = checko_client.fetch_method("company", "7700000001")
    assert err is None
    assert body["data"]["name"] == "ООО"
    assert checko_client.requests_used_today() == 1


def test_checko_parallel_reserve_stays_within_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(checko_client, "_data_dir", lambda: tmp_path)
    monkeypatch.setattr(checko_client, "_api_key", lambda: "test-fake-checko-key")
    monkeypatch.setattr(checko_client, "DAILY_LIMIT", 1)
    entered: list[str] = []
    release = threading.Event()
    results: list[tuple] = []

    class Resp:
        status_code = 200

        def json(self):
            return {"data": {"ok": True}}

        def raise_for_status(self):
            return None

    def post(_url, json=None, timeout=None):
        entered.append((json or {}).get("inn") or "")
        release.wait(2)
        return Resp()

    monkeypatch.setattr(checko_client.requests, "post", post)

    def run(inn: str) -> None:
        results.append(checko_client.fetch_method("company", inn))

    first = threading.Thread(target=run, args=("7700000001",))
    second = threading.Thread(target=run, args=("7700000002",))
    first.start()
    second.start()
    try:
        deadline = time.time() + 2
        while time.time() < deadline and not (len(entered) >= 1 and len(results) >= 1):
            time.sleep(0.01)
        assert len(entered) == 1
        assert len(results) == 1
    finally:
        release.set()
        first.join(2)
        second.join(2)
    assert len(entered) == 1
    assert checko_client.requests_used_today() == 1
    errors = [err for _body, err in results if err]
    oks = [body for body, err in results if not err]
    assert len(oks) == 1 and len(errors) == 1
    assert "исчерпан" in errors[0]


def test_checko_cache_write_is_atomic(tmp_path, monkeypatch):
    monkeypatch.setattr(checko_client, "_data_dir", lambda: tmp_path)
    checko_client._write_cache("company", "7700000001", {"a": 1})
    path = checko_client._cache_path("company", "7700000001")
    assert json.loads(path.read_text(encoding="utf-8"))["data"]["a"] == 1

    def boom(_src, _dst):
        raise OSError("disk")

    monkeypatch.setattr(checko_client.os, "replace", boom)
    try:
        checko_client._write_cache("company", "7700000001", {"a": 2})
        raised = False
    except OSError:
        raised = True
    assert raised
    assert json.loads(path.read_text(encoding="utf-8"))["data"]["a"] == 1


def test_context_clear_is_persisted():
    chat_id = 77
    sro_context.set_user_sro(chat_id, "OGPS", inn="7700000001")
    sro_context.begin_joiner_activity_pick(chat_id)
    sro_context._user_context.clear()
    sro_context._load_persisted_context()
    assert sro_context.get_user_sro_id(chat_id) is None

    sro_context.set_user_sro(chat_id, "OGPS", inn="7700000001")
    sro_context.apply_context_from_memberships(
        chat_id, "7700000002", ["OGPS", "MOTS"]
    )
    sro_context._user_context.clear()
    sro_context._load_persisted_context()
    assert sro_context.get_user_sro_id(chat_id) is None


def test_nopriz_outage_is_not_a_miss(monkeypatch):
    nrs_search_links._nopriz_last_call.clear()

    def boom(*_a, **_k):
        raise RuntimeError("timeout")

    monkeypatch.setattr(nrs_search_links.requests, "post", boom)
    text = nrs_search_links.format_nrs_link_reply("П-122864", chat_id=88001)
    assert "Сервис недоступен, попробуйте позже." in text
    assert "не нашли" not in text

    nrs_search_links._nopriz_last_call[88002] = time.monotonic()
    throttled = nrs_search_links.format_nrs_link_reply(
        "Иванов Иван Иванович", chat_id=88002
    )
    assert "Сервис недоступен, попробуйте позже." in throttled
    assert "список пустой" not in throttled
    nrs_search_links._nopriz_last_call.clear()


def test_unspecified_plan_month_has_no_year():
    assert reestr_sync._format_plan_month("не указан") == "не указан"
    assert reestr_sync._format_plan_month("Не указан") == "не указан"
    assert reestr_sync._format_plan_month("не указан 2026") == "не указан"
    assert "2026" not in reestr_sync._format_plan_month("не указан")


def test_kf_money_drops_kopecks():
    assert reestr_sync._format_kf_money("1 500 000,00") == "1 500 000 ₽"
    assert reestr_sync._format_kf_money("1 500 000.00 руб.") == "1 500 000 ₽"
    assert reestr_sync._format_kf_money("500 000 руб.") == "500 000 ₽"


def test_card_without_kf_level_is_not_refetched():
    html = read_fixture("reestr_detail_full.html")
    html = html.replace("Возмещение вреда", "Скрытое поле ВВ")
    html = html.replace("Обеспечение договорных обязательств", "Скрытое поле ОДО")
    detail = reestr_sync._parse_detail_page(html)
    assert detail["kf_level_vv"] is None
    assert detail["kf_levels_checked"] is True
    base = {
        "url": "https://sro.example.test/reestr/x/",
        "inspections_by_year": {"2025": "Нарушений не выявлено"},
        "status": "Член СРО",
    }
    merged = reestr_sync._overlay_nonblank(base, detail)
    assert merged.get("kf_levels_checked") is True
    assert "kf_level_vv" not in merged
    assert reestr_sync.membership_needs_detail_fetch(merged) is False


def test_missing_cache_is_not_excluded():
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "plan_month_check.py"
    spec = importlib.util.spec_from_file_location("plan_month_check", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    flagged = mod.check_rows(
        [{"sro_key": "OGPS", "inn": "7700000001", "name": "А"}],
        {},
        "2026",
        False,
    )
    assert len(flagged) == 1
    assert flagged[0]["status"] == "НЕТ В КЭШЕ"
    assert flagged[0]["mark"] == "nocache"
    assert "исключена" not in flagged[0]["reason"]


def test_plan_export_filenames_use_year(tmp_path, monkeypatch):
    import importlib.util

    from docx import Document

    path = Path(__file__).resolve().parents[1] / "scripts" / "plan_proverok_export.py"
    spec = importlib.util.spec_from_file_location("plan_proverok_export", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(
        mod,
        "read_excel",
        lambda _p: (
            {
                "ОГПС": {
                    "ЯНВАРЬ": [
                        {"opf": "ООО", "name": "А", "inn": "1", "address": ""}
                    ]
                }
            },
            {},
        ),
    )
    monkeypatch.setattr(mod, "build_document", lambda *_a, **_k: Document())
    mod.export(tmp_path / "in.xlsx", tmp_path / "out", year=2027)
    names = [p.name for p in (tmp_path / "out").rglob("*.docx")]
    assert "plan_proverok_ОГПС_2027.docx" in names
    assert "ОГПС_2027_01_январь.docx" in names
    assert all("2026" not in name for name in names)


def test_telegram_html_is_clipped_on_a_safe_boundary(monkeypatch):
    captured: dict[str, str] = {}

    class Resp:
        def json(self):
            return {"ok": True}

    def post(_url, json=None, timeout=None):
        captured["text"] = json["text"]
        return Resp()

    monkeypatch.setattr(site_health_check, "_bot_token", lambda: "1:not-a-token")
    monkeypatch.setattr(site_health_check, "_admin_ids", lambda: [1])
    monkeypatch.setattr(site_health_check.requests, "post", post)
    long = "<b>" + ("я" * 5000) + "</b>"
    assert site_health_check._send_telegram(long)
    text = captured["text"]
    assert text.count("<b>") == text.count("</b>")
    assert len(text) <= 4096
    broken = "начало " + ("я" * 3990) + "<b незакрытый"
    clipped = site_health_check._clip_telegram_html(broken, 4000)
    assert "<b незакрытый" not in clipped
    assert "<" not in clipped
