"""Журнал bot_users.json: сбой записи, два процесса, битый файл."""

from __future__ import annotations

import json
import multiprocessing
import os
import time
import types
from pathlib import Path

import pytest

import users_log
from users_log import format_users_report, touch_user, users_count


def _message(chat_id: int, first_name: str = "U"):
    return types.SimpleNamespace(
        chat=types.SimpleNamespace(id=chat_id),
        from_user=types.SimpleNamespace(
            id=chat_id, first_name=first_name, last_name="", username="u"
        ),
    )


def _touch_users_in_child(path: str, chat_ids: list[int], delay: float, start) -> None:
    """Пишет своих пользователей. replace намеренно медленный, чтобы процессы столкнулись."""
    import sys

    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    import users_log as journal

    journal.USERS_FILE = Path(path)
    real_replace = os.replace

    def slow_replace(src, dst):
        time.sleep(delay)
        return real_replace(src, dst)

    os.replace = slow_replace
    start.wait(15)
    for chat_id in chat_ids:
        journal.touch_user(_message(chat_id))


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


def test_two_processes_keep_every_user(tmp_path):
    path = tmp_path / "bot_users.json"
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(2)
    groups = (list(range(1, 3)), list(range(3, 5)))
    procs = [
        ctx.Process(
            target=_touch_users_in_child,
            args=(str(path), ids, 0.2, barrier),
        )
        for ids in groups
    ]
    for proc in procs:
        proc.start()
    try:
        for proc in procs:
            proc.join(30)
        assert [proc.exitcode for proc in procs] == [0, 0]
        data = json.loads(path.read_text(encoding="utf-8"))
        assert set(data["users"]) == {"1", "2", "3", "4"}
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
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "9" in saved["users"]
    assert touch_user(_message(9, first_name="Новый")) is False
    assert list(tmp_path.glob("bot_users.json.bad-*")) == bad
    logged = capsys.readouterr().out
    assert logged.count("повреждён") == 1
    assert "Живой" not in logged
    assert "Новый" not in logged


def test_without_fcntl_journal_still_writes(monkeypatch):
    monkeypatch.setattr(users_log, "fcntl", None, raising=False)
    assert touch_user(_message(15)) is True
    assert users_count() == 1
    assert "15" in format_users_report()


@pytest.mark.skipif(os.name == "nt", reason="на Windows fcntl нет, это и есть запасной путь")
def test_lock_file_sits_next_to_journal(tmp_path, monkeypatch):
    path = tmp_path / "bot_users.json"
    monkeypatch.setattr(users_log, "USERS_FILE", path)
    touch_user(_message(4))
    assert (tmp_path / "bot_users.json.lock").is_file()
