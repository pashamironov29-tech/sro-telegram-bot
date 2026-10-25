"""Журнал bot_users.sqlite: сбой записи, два процесса, перенос JSON."""

from __future__ import annotations

import json
import multiprocessing
import os
import sqlite3
import types
from pathlib import Path

import pytest

import users_log
from users_log import format_users_report, list_users, touch_user, users_count


def _message(chat_id: int, first_name: str = "U"):
    return types.SimpleNamespace(
        chat=types.SimpleNamespace(id=chat_id),
        from_user=types.SimpleNamespace(
            id=chat_id, first_name=first_name, last_name="", username="u"
        ),
    )


def _touch_users_in_child(path: str, chat_ids: list[int], start) -> None:
    """Пишет своих пользователей в общую sqlite. Процессы стартуют вместе."""
    import sys

    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    import users_log as journal

    journal.USERS_FILE = Path(path)
    journal._ready_path = None
    start.wait(15)
    for chat_id in chat_ids:
        if journal.touch_user(_message(chat_id)) is not True:
            raise SystemExit(2)


def _touch_same_user(path: str, times: int, start) -> None:
    import sys

    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    import users_log as journal

    journal.USERS_FILE = Path(path)
    journal._ready_path = None
    start.wait(15)
    for _ in range(times):
        journal.touch_user(_message(1))


def test_touch_user_and_report_swallow_write_errors(monkeypatch, capsys):
    """Ошибка записи не вылетает из touch_user, счётчика и отчёта. В логе нет имени."""

    def boom(*_args, **_kwargs):
        raise OSError("disk")

    monkeypatch.setattr(users_log, "_save", boom)
    assert touch_user(_message(11, first_name="Секретноеимя")) is False
    assert users_count() == 0
    report = format_users_report()
    assert isinstance(report, str)
    logged = capsys.readouterr().out
    assert "Секретноеимя" not in logged
    assert "Секретноеимя" not in report
    assert "disk" not in logged


def test_readers_swallow_load_errors(monkeypatch, capsys):
    def boom(*_args, **_kwargs):
        raise OSError("Секретноеимя")

    monkeypatch.setattr(users_log, "_load", boom)
    assert users_count() == 0
    report = format_users_report()
    assert "Секретноеимя" not in report
    assert "Секретноеимя" not in capsys.readouterr().out


def _chat_ids(path: Path) -> set[int]:
    conn = sqlite3.connect(path)
    try:
        return {row[0] for row in conn.execute("SELECT chat_id FROM users")}
    finally:
        conn.close()


def test_two_processes_keep_every_user(tmp_path):
    path = tmp_path / "bot_users.json"
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(2)
    groups = (list(range(1, 3)), list(range(3, 5)))
    procs = [
        ctx.Process(target=_touch_users_in_child, args=(str(path), ids, barrier))
        for ids in groups
    ]
    for proc in procs:
        proc.start()
    try:
        for proc in procs:
            proc.join(30)
        assert [proc.exitcode for proc in procs] == [0, 0]
        assert _chat_ids(tmp_path / "bot_users.sqlite") == {1, 2, 3, 4}
    finally:
        for proc in procs:
            if proc.is_alive():
                proc.terminate()
                proc.join(5)


def test_two_processes_do_not_lose_increments(tmp_path):
    path = tmp_path / "bot_users.json"
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(2)
    times = 8
    procs = [
        ctx.Process(target=_touch_same_user, args=(str(path), times, barrier))
        for _ in range(2)
    ]
    for proc in procs:
        proc.start()
    try:
        for proc in procs:
            proc.join(30)
        assert [proc.exitcode for proc in procs] == [0, 0]
        conn = sqlite3.connect(tmp_path / "bot_users.sqlite")
        try:
            row = conn.execute(
                "SELECT messages, starts FROM users WHERE chat_id=1"
            ).fetchone()
            total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        finally:
            conn.close()
        assert row == (times * 2, 0)
        assert total == 1
    finally:
        for proc in procs:
            if proc.is_alive():
                proc.terminate()
                proc.join(5)


def test_corrupt_journal_is_moved_once_and_rewritten(tmp_path, monkeypatch, capsys):
    path = tmp_path / "bot_users.json"
    monkeypatch.setattr(users_log, "USERS_FILE", path)
    path.write_text(
        json.dumps(
            {"users": {"5": {"chat_id": 5, "full_name": "Живой", "username": "ok"}}},
            ensure_ascii=False,
        )
        + "\nNOT JSON",
        encoding="utf-8",
    )
    assert touch_user(_message(9, first_name="Новый")) is True
    bad = list(tmp_path.glob("bot_users.json.bad-*"))
    assert len(bad) == 1
    assert bad[0].name[len("bot_users.json.bad-") :].count("-") == 1
    stamp = bad[0].name.removeprefix("bot_users.json.bad-")
    assert len(stamp) == len("YYYYmmdd-HHMMSS")
    assert stamp[8] == "-"
    assert "Живой" in bad[0].read_text(encoding="utf-8")
    assert not path.is_file()
    conn = sqlite3.connect(tmp_path / "bot_users.sqlite")
    try:
        saved = conn.execute(
            "SELECT full_name FROM users WHERE chat_id=9"
        ).fetchone()
    finally:
        conn.close()
    assert saved[0] == "Новый"
    assert touch_user(_message(9, first_name="Новый")) is False
    assert list(tmp_path.glob("bot_users.json.bad-*")) == bad
    logged = capsys.readouterr().out
    assert logged.count("повреждён") == 1
    assert "Живой" not in logged
    assert "Новый" not in logged


def test_oserror_on_read_does_not_quarantine(tmp_path, monkeypatch, capsys):
    """Нет прав на чтение — файл остаётся, запись пропускается, в логе нет имени."""
    path = tmp_path / "bot_users.json"
    monkeypatch.setattr(users_log, "USERS_FILE", path)
    payload = json.dumps(
        {"users": {"5": {"chat_id": 5, "full_name": "Живой", "username": "ok"}}},
        ensure_ascii=False,
    )
    path.write_text(payload, encoding="utf-8")
    before = path.read_bytes()
    real_read_text = Path.read_text

    def boom(self, *args, **kwargs):
        if Path(self) == path:
            raise PermissionError("Секретноеимя")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(users_log, "_read_error_logged_at", None)
    monkeypatch.setattr(Path, "read_text", boom)
    assert touch_user(_message(9, first_name="Новый")) is False
    assert list(tmp_path.glob("bot_users.json.bad-*")) == []
    assert path.read_bytes() == before
    logged = capsys.readouterr().out
    assert "пропускаю" in logged
    assert "Секретноеимя" not in logged
    assert "Живой" not in logged
    assert "Новый" not in logged


def test_read_error_log_is_throttled_until_success_or_interval(tmp_path, monkeypatch, capsys):
    """Постоянная ошибка чтения не печатается на каждое сообщение."""
    path = tmp_path / "bot_users.json"
    monkeypatch.setattr(users_log, "USERS_FILE", path)
    monkeypatch.setattr(users_log, "_read_error_logged_at", None)
    path.write_text('{"users": {}}', encoding="utf-8")
    clock = {"t": 1000.0}
    monkeypatch.setattr(users_log, "_monotonic", lambda: clock["t"])
    state = {"fail": True}
    real_read_text = Path.read_text

    def boom(self, *args, **kwargs):
        if Path(self) == path and state["fail"]:
            raise PermissionError("Секретноеимя")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", boom)
    assert touch_user(_message(3)) is False
    assert touch_user(_message(4)) is False
    assert capsys.readouterr().out.count("пропускаю") == 1

    clock["t"] += users_log.READ_ERROR_LOG_INTERVAL_SEC
    assert touch_user(_message(5)) is False
    assert capsys.readouterr().out.count("пропускаю") == 1

    state["fail"] = False
    assert touch_user(_message(6)) is True
    assert "пропускаю" not in capsys.readouterr().out

    # Журнал уже в sqlite: повторно JSON не читаем, битое чтение визит не блокирует.
    state["fail"] = True
    assert touch_user(_message(7)) is True
    logged = capsys.readouterr().out
    assert "пропускаю" not in logged
    assert "Секретноеимя" not in logged
    assert users_count() == 2


def test_visit_does_not_rewrite_json(tmp_path, monkeypatch):
    """Живой журнал — sqlite. Общий bot_users.json.tmp больше не пишется."""
    path = tmp_path / "bot_users.json"
    monkeypatch.setattr(users_log, "USERS_FILE", path)
    monkeypatch.setattr(users_log, "_ready_path", None)
    assert touch_user(_message(1)) is True
    assert touch_user(_message(2)) is True
    assert list(tmp_path.glob("bot_users.json*.tmp")) == []
    assert not path.is_file()
    assert (tmp_path / "bot_users.sqlite").is_file()
    assert users_count() == 2


def test_without_fcntl_journal_still_writes(monkeypatch):
    monkeypatch.setattr(users_log, "fcntl", None, raising=False)
    assert touch_user(_message(15)) is True
    assert users_count() == 1
    assert "15" in format_users_report()


def test_journal_is_wal_and_fully_synced(tmp_path, monkeypatch):
    path = tmp_path / "bot_users.json"
    monkeypatch.setattr(users_log, "USERS_FILE", path)
    monkeypatch.setattr(users_log, "_ready_path", None)
    touch_user(_message(4))
    conn = sqlite3.connect(tmp_path / "bot_users.sqlite")
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        sync = conn.execute("PRAGMA synchronous").fetchone()[0]
    finally:
        conn.close()
    assert str(mode).lower() == "wal"
    assert int(sync) == 2
    assert not (tmp_path / "bot_users.json.lock").exists()


def test_json_backup_is_kept_and_ids_get_legacy_platform(tmp_path, monkeypatch):
    path = tmp_path / "bot_users.json"
    payload = json.dumps(
        {
            "users": {
                "5": {
                    "chat_id": 5,
                    "full_name": "Живой",
                    "username": "ok",
                    "first_seen": "2024-01-01 00:00:00",
                    "last_seen": "2024-06-01 12:00:00",
                    "starts": 2,
                    "messages": 4,
                }
            }
        },
        ensure_ascii=False,
    )
    path.write_text(payload, encoding="utf-8")
    before = path.read_bytes()
    monkeypatch.setattr(users_log, "USERS_FILE", path)
    monkeypatch.setattr(users_log, "_ready_path", None)
    assert users_count() == 1
    assert path.read_bytes() == before
    legacy = list_users()
    assert legacy[0]["platform"] == "legacy"
    assert legacy[0]["full_name"] == "Живой"
    assert legacy[0]["starts"] == 2
    assert legacy[0]["messages"] == 4
    monkeypatch.setenv("BOT_PLATFORM", "tg")
    assert touch_user(_message(5, first_name="Снова")) is True
    assert path.read_bytes() == before
    assert users_count() == 2
    by_platform = {row["platform"]: row["full_name"] for row in list_users(limit=10)}
    assert by_platform["legacy"] == "Живой"
    assert by_platform["tg"] == "Снова"


def test_same_chat_id_on_two_platforms_stays_two_rows(monkeypatch):
    monkeypatch.setenv("BOT_PLATFORM", "tg")
    assert touch_user(_message(5, first_name="Телеграм")) is True
    monkeypatch.setenv("BOT_PLATFORM", "max")
    assert touch_user(_message(5, first_name="Макс")) is True
    assert users_count() == 2
    got = {(row["platform"], row["full_name"]) for row in list_users(limit=10)}
    assert got == {("tg", "Телеграм"), ("max", "Макс")}
    report = format_users_report()
    assert "Telegram" in report
    assert "MAX" in report


def test_failed_write_keeps_previous_rows(monkeypatch):
    real_save = users_log._save
    state = {"fail": False}

    def wrapped(*args, **kwargs):
        if state["fail"]:
            raise OSError("disk")
        return real_save(*args, **kwargs)

    monkeypatch.setattr(users_log, "_save", wrapped)
    assert touch_user(_message(1, first_name="Первый")) is True
    state["fail"] = True
    assert touch_user(_message(2, first_name="Второй")) is False
    state["fail"] = False
    assert users_count() == 1
    assert list_users()[0]["full_name"] == "Первый"


def test_update_touches_only_its_own_row(monkeypatch):
    monkeypatch.setenv("BOT_PLATFORM", "max")
    assert touch_user(_message(1, first_name="Первый")) is True
    assert touch_user(_message(2, first_name="Второй")) is True
    assert touch_user(_message(1, first_name="Первый-2")) is False
    got = {row["chat_id"]: (row["full_name"], row["starts"]) for row in list_users(limit=10)}
    assert got[1][0] == "Первый-2"
    assert got[2][0] == "Второй"
    assert users_count() == 2


def test_every_connection_is_wal_and_synchronous_full(monkeypatch):
    seen = []
    real = users_log._connect

    def spy():
        conn = real()
        seen.append(
            (
                str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower(),
                int(conn.execute("PRAGMA synchronous").fetchone()[0]),
            )
        )
        return conn

    monkeypatch.setattr(users_log, "_connect", spy)
    assert touch_user(_message(9)) is True
    users_count()
    assert seen
    assert all(item == ("wal", 2) for item in seen)


def test_json_is_imported_only_once(tmp_path, monkeypatch):
    path = tmp_path / "bot_users.json"
    path.write_text(
        json.dumps({"users": {"1": {"chat_id": 1, "full_name": "A", "starts": 1}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(users_log, "USERS_FILE", path)
    monkeypatch.setattr(users_log, "_ready_path", None)
    assert users_count() == 1
    path.write_text(
        json.dumps(
            {
                "users": {
                    "1": {"chat_id": 1, "full_name": "A", "starts": 1},
                    "2": {"chat_id": 2, "full_name": "B", "starts": 1},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(users_log, "_ready_path", None)
    assert users_count() == 1
