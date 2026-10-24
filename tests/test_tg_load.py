# -*- coding: utf-8 -*-
"""Нагрузка Telegram: 429, лимитер исходящих, поиск не в потоке обработчика."""

from __future__ import annotations

import threading
import time
import types

import log_redact

_real_install = log_redact.install_secret_log_redaction
log_redact.install_secret_log_redaction = lambda *a, **k: None  # type: ignore[method-assign]
import bot_FINAL_GOLD  # noqa: E402

log_redact.install_secret_log_redaction = _real_install

import national_reestr  # noqa: E402
import pytest  # noqa: E402
from telebot.apihelper import ApiTelegramException  # noqa: E402


def _tg_429(retry_after: float) -> ApiTelegramException:
    return ApiTelegramException(
        "sendMessage",
        None,
        {
            "ok": False,
            "error_code": 429,
            "description": "Too Many Requests: retry after",
            "parameters": {"retry_after": retry_after},
        },
    )


def _text(chat_id: int, text: str):
    return types.SimpleNamespace(
        text=text,
        chat=types.SimpleNamespace(id=chat_id),
        from_user=types.SimpleNamespace(
            id=chat_id, first_name="Тест", last_name="", username="u"
        ),
    )


def _event(chat_id: int = 5):
    return _text(chat_id, "привет")


def test_worker_threads_raised():
    assert bot_FINAL_GOLD.bot.worker_pool.num_threads == 16


def test_outgoing_limit_is_about_25_per_second():
    limiter = bot_FINAL_GOLD._outgoing_limiter
    assert limiter.rate == 25
    assert limiter.capacity == 25


def test_token_bucket_allows_burst_then_waits():
    clock = {"t": 0.0}
    sleeps: list[float] = []

    def monotonic() -> float:
        return clock["t"]

    def sleep(sec: float) -> None:
        sleeps.append(sec)
        clock["t"] += sec

    bucket = bot_FINAL_GOLD.TokenBucket(rate=25, capacity=25, clock=monotonic, sleep=sleep)
    for _ in range(25):
        bucket.acquire()
    assert sleeps == []
    bucket.acquire()
    assert sleeps
    assert abs(sum(sleeps) - (1 / 25)) < 1e-9


def test_token_bucket_acquire_is_thread_safe():
    bucket = bot_FINAL_GOLD.TokenBucket(rate=5000, capacity=40)
    errors: list[BaseException] = []

    def work() -> None:
        try:
            for _ in range(15):
                bucket.acquire()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(2)
        assert not thread.is_alive()
    assert errors == []


def test_send_helpers_take_a_token(monkeypatch):
    taken: list[int] = []
    monkeypatch.setattr(bot_FINAL_GOLD._outgoing_limiter, "acquire", lambda: taken.append(1))
    monkeypatch.setattr(
        bot_FINAL_GOLD.bot,
        "send_message",
        lambda *_a, **_k: types.SimpleNamespace(message_id=1),
    )
    monkeypatch.setattr(bot_FINAL_GOLD.bot, "edit_message_text", lambda *_a, **_k: None)
    bot_FINAL_GOLD.safe_send_message(1, "a")
    bot_FINAL_GOLD.safe_edit_message_text(1, 2, "b")
    bot_FINAL_GOLD.finish_button_reply(1, "c")
    assert taken == [1, 1, 1]


def test_429_waits_retry_after_and_retries(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(bot_FINAL_GOLD, "_retry_sleep", lambda sec: slept.append(sec))
    calls = {"n": 0}

    def send(_chat_id, _text, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _tg_429(1)
        return types.SimpleNamespace(message_id=3)

    monkeypatch.setattr(bot_FINAL_GOLD.bot, "send_message", send)
    msg = bot_FINAL_GOLD.safe_send_message(1, "hi")
    assert msg.message_id == 3
    assert calls["n"] == 2
    assert slept == [1.0]


def test_429_retries_are_bounded(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(bot_FINAL_GOLD, "_retry_sleep", lambda sec: slept.append(sec))

    def send(_chat_id, _text, **_kwargs):
        raise _tg_429(1)

    monkeypatch.setattr(bot_FINAL_GOLD.bot, "send_message", send)
    with pytest.raises(ApiTelegramException) as caught:
        bot_FINAL_GOLD.safe_send_message(1, "hi", retries=5)
    assert caught.value.error_code == 429
    assert len(slept) == bot_FINAL_GOLD._TG_429_MAX_TRIES - 1


def test_finish_button_reply_retries_429(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(bot_FINAL_GOLD, "_retry_sleep", lambda sec: slept.append(sec))
    calls = {"n": 0}

    def send(_chat_id, _text, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _tg_429(1)
        return types.SimpleNamespace(message_id=8)

    monkeypatch.setattr(bot_FINAL_GOLD.bot, "send_message", send)
    bot_FINAL_GOLD.finish_button_reply(1, "кнопка")
    assert calls["n"] == 2
    assert slept == [1.0]


def test_edit_retries_429(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(bot_FINAL_GOLD, "_retry_sleep", lambda sec: slept.append(sec))
    calls = {"n": 0}

    def edit(_text, _chat_id, _message_id, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _tg_429(1)
        return None

    monkeypatch.setattr(bot_FINAL_GOLD.bot, "edit_message_text", edit)
    bot_FINAL_GOLD.safe_edit_message_text(1, 9, "текст")
    assert calls["n"] == 2
    assert slept == [1.0]


def test_long_429_is_retried_off_the_caller(monkeypatch):
    slept: list[tuple[str, float]] = []

    def sleep(sec: float) -> None:
        slept.append((threading.current_thread().name, sec))

    monkeypatch.setattr(bot_FINAL_GOLD, "_retry_sleep", sleep)
    calls = {"n": 0}

    def send(_chat_id, _text, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _tg_429(30)
        return types.SimpleNamespace(message_id=7)

    monkeypatch.setattr(bot_FINAL_GOLD.bot, "send_message", send)
    assert bot_FINAL_GOLD.safe_send_message(1, "hi") is None
    bot_FINAL_GOLD.wait_retry_tasks()
    assert calls["n"] == 2
    assert slept
    assert all(name.startswith("tg-retry") for name, _sec in slept)
    assert all(sec <= bot_FINAL_GOLD._TG_429_SLEEP_CAP for _name, sec in slept)
    assert any(sec == bot_FINAL_GOLD._TG_429_SLEEP_CAP for _name, sec in slept)


def test_direct_send_message_retries_429(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(bot_FINAL_GOLD, "_retry_sleep", lambda sec: slept.append(sec))
    calls = {"n": 0}

    def raw(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _tg_429(1)
        return types.SimpleNamespace(message_id=4)

    monkeypatch.setattr(bot_FINAL_GOLD, "_raw_send_message", raw)
    msg = bot_FINAL_GOLD.bot.send_message(1, "прямая")
    assert msg.message_id == 4
    assert calls["n"] == 2
    assert slept == [1.0]


def test_log_errors_does_not_message_user_on_429(monkeypatch):
    sent: list = []
    notes: list = []
    monkeypatch.setattr(bot_FINAL_GOLD.bot, "send_message", lambda *a, **_k: sent.append(a))
    monkeypatch.setattr(
        bot_FINAL_GOLD, "notify_admins_about_error", lambda *_a, **_k: notes.append(1)
    )

    @bot_FINAL_GOLD.log_errors
    def boom(_event):
        raise _tg_429(2)

    assert boom(_event()) is None
    assert sent == []
    assert notes == []


def test_handler_exhausted_429_stays_quiet(monkeypatch):
    texts: list[str] = []

    def send(_chat_id, text, **_kwargs):
        texts.append(text)
        raise _tg_429(1)

    monkeypatch.setattr(bot_FINAL_GOLD.bot, "send_message", send)
    monkeypatch.setattr(bot_FINAL_GOLD, "_retry_sleep", lambda _s: None)
    monkeypatch.setattr(bot_FINAL_GOLD, "notify_admins_about_error", lambda *_a, **_k: None)

    @bot_FINAL_GOLD.log_errors
    def handler(_event):
        bot_FINAL_GOLD.safe_send_message(5, "ответ")

    handler(_event())
    assert texts == ["ответ", "ответ", "ответ"]


def test_transient_retry_sleep_is_capped(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(bot_FINAL_GOLD, "_retry_sleep", lambda sec: slept.append(sec))
    n = {"i": 0}

    def send(_chat_id, _text, **_kwargs):
        n["i"] += 1
        if n["i"] < 3:
            raise ConnectionError("connection reset by peer")
        return types.SimpleNamespace(message_id=1)

    monkeypatch.setattr(bot_FINAL_GOLD.bot, "send_message", send)
    bot_FINAL_GOLD.safe_send_message(1, "a", parse_mode="HTML")
    assert slept == [
        bot_FINAL_GOLD._TRANSIENT_SLEEP_CAP,
        bot_FINAL_GOLD._TRANSIENT_SLEEP_CAP,
    ]


def test_fast_reply_skips_typing(monkeypatch):
    actions: list = []
    monkeypatch.setattr(
        bot_FINAL_GOLD.bot, "send_chat_action", lambda *a, **_k: actions.append(a)
    )
    monkeypatch.setattr(
        bot_FINAL_GOLD.bot,
        "send_message",
        lambda *_a, **_k: types.SimpleNamespace(message_id=1),
    )
    bot_FINAL_GOLD.send_question_reply(4242, "Что такое НОК?")
    assert actions == []


def test_slow_reply_still_sends_typing(monkeypatch):
    actions: list = []

    def slow(_question, chat_id=None):
        del chat_id
        time.sleep(bot_FINAL_GOLD._FAST_REPLY_SEC + 0.05)
        return {"ok": True, "text": "долго", "not_found": False}

    monkeypatch.setattr(bot_FINAL_GOLD, "answer_question", slow)
    monkeypatch.setattr(
        bot_FINAL_GOLD.bot, "send_chat_action", lambda *a, **_k: actions.append(a)
    )
    monkeypatch.setattr(
        bot_FINAL_GOLD.bot,
        "send_message",
        lambda *_a, **_k: types.SimpleNamespace(message_id=1),
    )
    bot_FINAL_GOLD.send_question_reply(4242, "долгий вопрос")
    assert actions
    assert actions[0][1] == "typing"


def test_max_search_timeout_stays_12():
    assert national_reestr.REQUEST_TIMEOUT == 12
    assert national_reestr.make_client().timeout == 12
    assert national_reestr.make_client(timeout=6).timeout == 6


def test_national_search_runs_off_the_worker_and_edits(monkeypatch):
    chat_id = 818181
    national_reestr.enter_national_mode(chat_id)
    sent: list[str] = []
    edits: list[tuple] = []
    gate = threading.Event()
    seen: dict = {}

    def send(_chat_id, text, **_kwargs):
        sent.append(text or "")
        return types.SimpleNamespace(message_id=len(sent))

    def edit(text, _chat_id, message_id, **kwargs):
        edits.append((text, kwargs.get("reply_markup"), message_id))
        return None

    def search(query, client=None):
        seen["thread"] = threading.current_thread().name
        seen["timeout"] = None if client is None else client.timeout
        assert any("Ищу…" in item for item in sent)
        assert gate.wait(2)
        return national_reestr.SearchResult(
            "🏛 готово",
            [national_reestr.PickButton("ООО", "nat:nostroy:1")],
        )

    monkeypatch.setattr(bot_FINAL_GOLD.bot, "send_message", send)
    monkeypatch.setattr(bot_FINAL_GOLD.bot, "edit_message_text", edit)
    monkeypatch.setattr(national_reestr, "search_members", search)
    try:
        started = time.monotonic()
        bot_FINAL_GOLD.handle_text(_text(chat_id, "Ромашка"))
        elapsed = time.monotonic() - started
        assert elapsed < 0.5
        deadline = time.monotonic() + 1
        while "thread" not in seen and time.monotonic() < deadline:
            time.sleep(0.01)
        assert str(seen["thread"]).startswith("tg-heavy")
        assert seen["timeout"] == 6
    finally:
        gate.set()
        bot_FINAL_GOLD.wait_heavy_tasks()
    assert any("Ищу…" in item for item in sent)
    assert edits[-1][2] == 1
    assert "готово" in edits[-1][0]
    assert edits[-1][1].keyboard[0][0].callback_data == "nat:nostroy:1"


def test_identical_national_query_is_cached(monkeypatch):
    chat_id = 828282
    national_reestr.enter_national_mode(chat_id)
    calls: list[str] = []

    def search(query, client=None):
        del client
        calls.append(query)
        return national_reestr.SearchResult("один")

    monkeypatch.setattr(national_reestr, "search_members", search)
    monkeypatch.setattr(
        bot_FINAL_GOLD.bot,
        "send_message",
        lambda *_a, **_k: types.SimpleNamespace(message_id=1),
    )
    monkeypatch.setattr(bot_FINAL_GOLD.bot, "edit_message_text", lambda *_a, **_k: None)
    bot_FINAL_GOLD.handle_text(_text(chat_id, "Ромашка"))
    bot_FINAL_GOLD.wait_heavy_tasks()
    bot_FINAL_GOLD.handle_text(_text(chat_id, "  ромашка "))
    bot_FINAL_GOLD.wait_heavy_tasks()
    assert calls == ["Ромашка"]


def test_parallel_national_queries_share_one_request(monkeypatch):
    chat_id = 838383
    national_reestr.enter_national_mode(chat_id)
    entered = threading.Event()
    release = threading.Event()
    calls = {"n": 0}

    def search(_query, client=None):
        del client
        calls["n"] += 1
        entered.set()
        assert release.wait(2)
        return national_reestr.SearchResult("один")

    monkeypatch.setattr(national_reestr, "search_members", search)
    monkeypatch.setattr(
        bot_FINAL_GOLD.bot,
        "send_message",
        lambda *_a, **_k: types.SimpleNamespace(message_id=1),
    )
    monkeypatch.setattr(bot_FINAL_GOLD.bot, "edit_message_text", lambda *_a, **_k: None)
    try:
        bot_FINAL_GOLD.handle_text(_text(chat_id, "Ромашка"))
        assert entered.wait(1)
        bot_FINAL_GOLD.handle_text(_text(chat_id, "Ромашка"))
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            with bot_FINAL_GOLD._heavy_lock:
                pending = sum(1 for item in bot_FINAL_GOLD._heavy_pending if not item.done())
            if pending >= 2:
                break
            time.sleep(0.01)
        assert calls["n"] == 1
    finally:
        release.set()
        bot_FINAL_GOLD.wait_heavy_tasks()
    assert calls["n"] == 1


def test_checko_runs_off_the_worker(monkeypatch):
    sent: list[str] = []
    edits: list[str] = []
    gate = threading.Event()
    seen: dict = {}
    monkeypatch.setattr(bot_FINAL_GOLD, "can_use_checko", lambda _cid: True)
    monkeypatch.setattr(bot_FINAL_GOLD.bot, "answer_callback_query", lambda *_a, **_k: None)

    def send(_chat_id, text, **_kwargs):
        sent.append(text or "")
        return types.SimpleNamespace(message_id=1)

    def edit(text, *_args, **_kwargs):
        edits.append(text or "")

    def section(name, inn):
        seen["thread"] = threading.current_thread().name
        assert any("Ищу…" in item for item in sent)
        assert gate.wait(2)
        return f"раздел {name} {inn}"

    monkeypatch.setattr(bot_FINAL_GOLD.bot, "send_message", send)
    monkeypatch.setattr(bot_FINAL_GOLD.bot, "edit_message_text", edit)
    monkeypatch.setattr(bot_FINAL_GOLD, "format_checko_section", section)
    call = types.SimpleNamespace(
        id="cb",
        data="chk:f:7700000001",
        message=types.SimpleNamespace(
            message_id=4, chat=types.SimpleNamespace(id=77)
        ),
    )
    try:
        started = time.monotonic()
        bot_FINAL_GOLD.handle_checko_callbacks(call)
        assert time.monotonic() - started < 0.5
        deadline = time.monotonic() + 1
        while "thread" not in seen and time.monotonic() < deadline:
            time.sleep(0.01)
        assert str(seen["thread"]).startswith("tg-heavy")
    finally:
        gate.set()
        bot_FINAL_GOLD.wait_heavy_tasks()
    assert any("Ищу…" in item for item in sent)
    assert "раздел general 7700000001" in edits[-1]
