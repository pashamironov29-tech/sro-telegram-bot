"""Порог пустых карточек, копия базы, стоп по 429/403/сети, OnFailure."""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import pytest
import requests

from specialist_reestr import connect, search_people
from specialist_sync import (
    RegistryClient,
    SyncBlocked,
    SyncRequestError,
    _empty_over,
    _env_int,
    backup_sqlite,
    failure_alert_text,
    sync_all,
)
from tests.test_specialist_sync import _ListApi, _client, _nostroy_row

_VPS = Path(__file__).resolve().parents[1] / "vps"
_INFO = "https://reestr.nostroy.ru/api/member/1/info"


def test_empty_over_needs_both_share_and_count():
    assert _empty_over(10, 40, 0.20, 10) is True
    assert _empty_over(10, 100, 0.20, 10) is False
    assert _empty_over(9, 10, 0.20, 10) is False
    assert _empty_over(100, 100, 0, 1) is False
    assert _empty_over(100, 100, 0.20, 0) is False
    assert _empty_over(0, 10, 0.20, 1) is False


def test_env_int_falls_back(monkeypatch):
    monkeypatch.setenv("SPECIALIST_EMPTY_MIN", "нет")
    assert _env_int("SPECIALIST_EMPTY_MIN", 10) == 10
    monkeypatch.setenv("SPECIALIST_EMPTY_MIN", "4")
    assert _env_int("SPECIALIST_EMPTY_MIN", 10) == 4


def _empty_card(member_id: int) -> dict:
    """Карточка без блока специалистов: это не пустые корзины реестра."""
    return {
        "id": member_id,
        "inn": f"770000000{member_id}",
        "short_description": f"ООО Номер {member_id}",
        "member_status": {"title": "Является членом"},
    }


def _published_empty_card(member_id: int) -> dict:
    return {
        "id": member_id,
        "inn": f"770000000{member_id}",
        "short_description": f"ООО Номер {member_id}",
        "member_status": {"title": "Является членом"},
        "experts_by_category": {"regular": [], "danger": [], "other": []},
    }


def _list_ok(member_ids, stamp):
    rows = [_nostroy_row(member_id, stamp=stamp) for member_id in member_ids]
    return 200, {
        "success": True,
        "data": {"count": len(rows), "countPages": 1, "data": rows},
    }


class _ByRegistry:
    """Списки по id реестра. Карточки — пустые корзины. fail_registry отвечает 503."""

    def __init__(self, ids_by_registry, stamp, fail_registry=None):
        self.ids_by_registry = ids_by_registry
        self.stamp = stamp
        self.fail_registry = fail_registry
        self.calls: list[str] = []

    def __call__(self, url, body, timeout):
        self.calls.append(url)
        if url.endswith("/member/list"):
            for registry_id, member_ids in self.ids_by_registry.items():
                if f"/sro/{registry_id}/" not in url:
                    continue
                if self.fail_registry == registry_id:
                    return 503, {}
                return _list_ok(member_ids, self.stamp)
            raise AssertionError(url)
        if "/member/" in url and url.endswith("/info"):
            member_id = int(url.rstrip("/").split("/")[-2])
            return 200, {"success": True, "data": _empty_card(member_id)}
        raise AssertionError(url)


def _sync_empty(tmp_path, api, monkeypatch, **kwargs):
    import specialist_sync

    alerts: list[str] = []
    monkeypatch.setattr(specialist_sync, "notify_admins", alerts.append, raising=False)
    db = tmp_path / "spec.sqlite"
    rc = sync_all(
        db_path=db,
        fresh=True,
        client=_client(api),
        **kwargs,
    )
    return rc, alerts, db


def test_empty_cards_over_sro_threshold_alert_and_exit_zero(tmp_path, monkeypatch):
    """12 пустых из 12: алерт, код 0, уже лежавшие ФИО на месте."""
    db = tmp_path / "spec.sqlite"
    ids = list(range(1, 13))
    assert sync_all(
        db_path=db, codes=["OGPS"], fresh=True, client=_client(_ListApi(ids))
    ) == 0
    assert search_people("сидоров", db=db).status == "ok"

    rc, alerts, _db = _sync_empty(
        tmp_path,
        _ByRegistry({87: ids}, stamp="05.05.2026 00:00:00"),
        monkeypatch,
        codes=["OGPS"],
        empty_ratio=0.20,
        empty_min=10,
        empty_total_ratio=0.20,
        empty_total_min=10,
    )
    assert rc == 0
    assert len(alerts) == 1
    assert "OGPS: 12 из 12" in alerts[0]
    assert "Всего: 12 из 12" in alerts[0]
    assert "Всего: добавлено 0, убрано 0" in alerts[0]
    assert search_people("сидоров", db=db).status == "ok"
    assert search_people("иванова", db=db).status == "ok"


def test_published_empty_buckets_do_not_alert(tmp_path, monkeypatch, capsys):
    """Явные пустые корзины выше порога — не авария и не сообщение админам."""
    ids = list(range(1, 13))
    db = tmp_path / "spec.sqlite"
    assert sync_all(
        db_path=db, codes=["OGPS"], fresh=True, client=_client(_ListApi(ids))
    ) == 0

    class _Published(_ByRegistry):
        def __call__(self, url, body, timeout):
            self.calls.append(url)
            if url.endswith("/member/list"):
                return _ByRegistry.__call__(self, url, body, timeout)
            if "/member/" in url and url.endswith("/info"):
                member_id = int(url.rstrip("/").split("/")[-2])
                return 200, {"success": True, "data": _published_empty_card(member_id)}
            return _ByRegistry.__call__(self, url, body, timeout)

    rc, alerts, _db = _sync_empty(
        tmp_path,
        _Published({87: ids}, stamp="05.05.2026 00:00:00"),
        monkeypatch,
        codes=["OGPS"],
        empty_ratio=0.20,
        empty_min=10,
        empty_total_ratio=0.20,
        empty_total_min=10,
    )
    assert rc == 0
    assert alerts == []
    assert "Админам не шлю" in capsys.readouterr().out
    assert search_people("сидоров", db=db).status == "ok"


def test_empty_cards_below_threshold_stay_quiet(tmp_path, monkeypatch):
    rc, alerts, _db = _sync_empty(
        tmp_path,
        _ByRegistry({87: [1, 2, 3, 4]}, stamp="05.05.2026 00:00:00"),
        monkeypatch,
        codes=["OGPS"],
    )
    assert rc == 0
    assert alerts == []


def test_empty_ratio_zero_disables_alert(tmp_path, monkeypatch):
    ids = list(range(1, 13))
    rc, alerts, _db = _sync_empty(
        tmp_path,
        _ByRegistry({87: ids}, stamp="05.05.2026 00:00:00"),
        monkeypatch,
        codes=["OGPS"],
        empty_ratio=0,
        empty_min=1,
        empty_total_ratio=0,
        empty_total_min=1,
    )
    assert rc == 0
    assert alerts == []


def test_empty_threshold_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SPECIALIST_EMPTY_RATIO", "0.2")
    monkeypatch.setenv("SPECIALIST_EMPTY_MIN", "3")
    monkeypatch.setenv("SPECIALIST_EMPTY_TOTAL_RATIO", "0.2")
    monkeypatch.setenv("SPECIALIST_EMPTY_TOTAL_MIN", "3")
    rc, alerts, _db = _sync_empty(
        tmp_path,
        _ByRegistry({87: [1, 2, 3, 4]}, stamp="05.05.2026 00:00:00"),
        monkeypatch,
        codes=["OGPS"],
    )
    assert rc == 0
    assert alerts
    assert "OGPS: 4 из 4" in alerts[0]


def test_total_threshold_alerts_when_each_sro_is_under(tmp_path, monkeypatch):
    """По 6 пустых на СРО меньше минимума 10, вместе 12 — общее сообщение."""
    ids_ogps = list(range(1, 7))
    ids_mots = list(range(7, 13))
    rc, alerts, _db = _sync_empty(
        tmp_path,
        _ByRegistry({87: ids_ogps, 179: ids_mots}, stamp="05.05.2026 00:00:00"),
        monkeypatch,
        codes=["OGPS", "MOTS"],
        empty_ratio=0.20,
        empty_min=10,
        empty_total_ratio=0.20,
        empty_total_min=10,
    )
    assert rc == 0
    assert len(alerts) == 1
    assert "OGPS: 6 из 6" not in alerts[0]
    assert "MOTS: 6 из 6" not in alerts[0]
    assert "Всего: 12 из 12" in alerts[0]
    assert "OGPS: добавлено 0, убрано 0" in alerts[0]
    assert "MOTS: добавлено 0, убрано 0" in alerts[0]


def test_empty_alert_does_not_hide_other_failure(tmp_path, monkeypatch):
    """Порог шлёт сообщение, но сломанный список другой СРО по-прежнему даёт код 1."""
    ids = list(range(1, 13))
    rc, alerts, _db = _sync_empty(
        tmp_path,
        _ByRegistry(
            {87: ids, 179: [20]},
            stamp="05.05.2026 00:00:00",
            fail_registry=179,
        ),
        monkeypatch,
        codes=["OGPS", "MOTS"],
        empty_ratio=0.20,
        empty_min=10,
        empty_total_ratio=1,
        empty_total_min=100,
    )
    assert rc == 1
    assert any("OGPS: 12 из 12" in item for item in alerts)


def test_backup_is_consistent_and_keeps_last_n(tmp_path):
    db = tmp_path / "specialists.sqlite"
    folder = tmp_path / "bak"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.execute("INSERT INTO t VALUES (0)")
    conn.commit()
    made = []
    for value in range(5):
        conn.execute("UPDATE t SET id=?", (value,))
        conn.commit()
        made.append(backup_sqlite(db, keep=3, backup_dir=folder))
    conn.execute("UPDATE t SET id=99")
    conn.commit()
    conn.close()

    files = sorted(folder.glob("specialists_*.sqlite"))
    assert len(files) == 3
    assert not made[0].exists()
    assert not made[1].exists()
    assert files[-1] == made[-1]
    saved = sqlite3.connect(made[-1])
    try:
        assert saved.execute("SELECT id FROM t").fetchone()[0] == 4
    finally:
        saved.close()
    assert backup_sqlite(tmp_path / "missing.sqlite", backup_dir=folder) is None


def test_sync_writes_backup_before_second_run(tmp_path, monkeypatch):
    import specialist_sync

    monkeypatch.setattr(specialist_sync, "notify_admins", lambda _text: None, raising=False)
    monkeypatch.setenv("SPECIALIST_BACKUP_KEEP", "2")
    db = tmp_path / "spec.sqlite"
    for _ in range(4):
        assert sync_all(
            db_path=db, codes=["OGPS"], fresh=True, client=_client(_ListApi([1, 2]))
        ) == 0
    files = sorted((tmp_path / "specialists_backups").glob("specialists_*.sqlite"))
    assert len(files) == 2
    saved = sqlite3.connect(files[-1])
    try:
        count = saved.execute("SELECT COUNT(*) FROM members").fetchone()[0]
    finally:
        saved.close()
    assert count == 2


def test_backup_failure_aborts_before_requests(tmp_path, monkeypatch):
    import specialist_sync

    alerts: list[str] = []
    monkeypatch.setattr(specialist_sync, "notify_admins", alerts.append, raising=False)
    db = tmp_path / "spec.sqlite"
    assert sync_all(
        db_path=db, codes=["OGPS"], fresh=True, client=_client(_ListApi([1, 2]))
    ) == 0
    assert search_people("сидоров", db=db).status == "ok"

    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    api = _ListApi([])
    alerts.clear()
    rc = sync_all(
        db_path=db,
        codes=["OGPS"],
        fresh=True,
        client=_client(api),
        backup_dir=blocker,
    )
    assert rc == 1
    assert api.calls == []
    assert alerts
    assert "копия" in alerts[0].lower()
    assert "spec.sqlite" in alerts[0]
    assert search_people("сидоров", db=db).status == "ok"
    assert search_people("иванова", db=db).status == "ok"


def _fast(api, **kwargs):
    retries = kwargs.pop("retries", 1)
    stop_after = kwargs.pop("stop_after", 3)
    sleep = kwargs.pop("sleep", lambda _s: None)
    return RegistryClient(
        api,
        min_interval=0,
        sleep=sleep,
        retries=retries,
        stop_after=stop_after,
        **kwargs,
    )


class _BlockApi:
    def __init__(self, status):
        self.status = status
        self.info_calls = 0
        self.calls: list[str] = []

    def __call__(self, url, body, timeout):
        self.calls.append(url)
        if url.endswith("/member/list"):
            return _list_ok(list(range(1, 7)), "04.04.2026 00:00:00")
        if url.endswith("/info"):
            self.info_calls += 1
            if self.status == "network":
                raise requests.ConnectionError("reset")
            return self.status, {}
        raise AssertionError(url)


@pytest.mark.parametrize("status", [429, 403, "network"])
def test_consecutive_blocks_stop_sync(tmp_path, monkeypatch, status):
    import specialist_sync

    alerts: list[str] = []
    monkeypatch.setattr(specialist_sync, "notify_admins", alerts.append, raising=False)
    db = tmp_path / "spec.sqlite"
    assert sync_all(
        db_path=db,
        codes=["OGPS"],
        fresh=True,
        client=_client(_ListApi([1, 2, 3, 4, 5, 6])),
    ) == 0

    api = _BlockApi(status)
    rc = sync_all(
        db_path=db,
        codes=["OGPS"],
        fresh=True,
        client=_fast(api),
    )
    assert rc == 1
    assert api.info_calls == 3
    assert len(api.calls) == 4  # список и три карточки, остальных не спрашиваем
    assert alerts
    assert "остановлен" in alerts[0].lower()
    assert search_people("сидоров", db=db).status == "ok"

    conn = connect(db)
    try:
        running = conn.execute(
            "SELECT run_id FROM sync_runs WHERE status='running'"
        ).fetchall()
        assert len(running) == 1
        run_id = running[0]["run_id"]
    finally:
        conn.close()

    alerts.clear()

    class _Recover:
        def __init__(self):
            self.info = 0

        def __call__(self, url, body, timeout):
            if url.endswith("/member/list"):
                return _list_ok(list(range(1, 7)), "04.04.2026 00:00:00")
            if url.endswith("/info"):
                self.info += 1
                member_id = int(url.rstrip("/").split("/")[-2])
                from tests.test_specialist_sync import _nostroy_card

                fios = {1: "Сидоров Пётр Сергеевич", 2: "Иванова Мария"}
                fio = fios.get(member_id, f"Специалист {member_id}")
                return 200, {"success": True, "data": _nostroy_card(member_id, fio)}
            raise AssertionError(url)

    recover = _Recover()
    assert sync_all(
        db_path=db,
        codes=["OGPS"],
        fresh=False,
        client=_client(recover),
    ) == 0
    # Оборванные карточки не записаны — следующий проход читает их снова.
    assert recover.info == 6
    conn = connect(db)
    try:
        row = conn.execute(
            "SELECT status FROM sync_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        assert row["status"] == "ok"
        assert conn.execute(
            "SELECT COUNT(*) FROM sync_runs WHERE status='running'"
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_429_honors_retry_after_and_stops_without_extra_request():
    slept: list[float] = []
    calls = {"n": 0}

    def transport(url, body, timeout):
        calls["n"] += 1
        return 429, {}, "15"

    client = _fast(transport, retries=8, stop_after=3, sleep=slept.append)
    with pytest.raises(SyncBlocked):
        client.post(_INFO, {})
    assert calls["n"] == 3
    assert slept == [15, 15]


def test_retry_after_is_capped():
    slept: list[float] = []

    def transport(url, body, timeout):
        return 429, {}, 10_000

    client = _fast(transport, retries=8, stop_after=3, sleep=slept.append)
    with pytest.raises(SyncBlocked):
        client.post(_INFO, {})
    assert slept == [120, 120]


def test_403_is_not_retried_on_the_same_call():
    calls = {"n": 0}

    def transport(url, body, timeout):
        calls["n"] += 1
        return 403, {}

    client = _fast(transport, retries=5, stop_after=3)
    with pytest.raises(SyncRequestError):
        client.post(_INFO, {})
    assert calls["n"] == 1
    with pytest.raises(SyncRequestError):
        client.post(_INFO, {})
    with pytest.raises(SyncBlocked):
        client.post(_INFO, {})
    assert calls["n"] == 3


def test_success_and_500_reset_block_streak():
    slept: list[float] = []
    steps = [
        (429, {}),
        (429, {}),
        (200, {"success": True, "data": {"ok": True}}),
        (429, {}),
        (429, {}),
        (429, {}),
    ]

    def transport(url, body, timeout):
        return steps.pop(0)

    client = _fast(transport, retries=6, stop_after=3, sleep=slept.append)
    assert client.post(_INFO, {})["success"] is True
    with pytest.raises(SyncBlocked):
        client.post(_INFO, {})
    assert steps == []
    assert slept == [1, 2, 1, 2]

    steps500 = [
        (429, {}),
        (500, {}),
        (429, {}),
        (429, {}),
        (200, {"success": True, "data": {"ok": True}}),
    ]

    def flaky(url, body, timeout):
        return steps500.pop(0)

    slept.clear()
    client = _fast(flaky, retries=6, stop_after=3, sleep=slept.append)
    assert client.post(_INFO, {})["success"] is True
    assert steps500 == []
    assert slept == [1, 2, 4, 8]


def test_failure_alert_text_timeout_and_exit():
    timeout = failure_alert_text("sro-specialist-sync", "timeout", "0")
    assert "TimeoutStartSec" in timeout
    assert "sro-specialist-sync.service" in timeout
    failed = failure_alert_text("sro-reestr-sync", "exit-code", "1")
    assert "Ночной синк реестра" in failed
    assert "result=exit-code" in failed
    assert "code=1" in failed


def test_send_unit_failure_alert_uses_notify_admins(monkeypatch):
    import specialist_sync

    alerts: list[str] = []
    monkeypatch.setattr(specialist_sync, "notify_admins", alerts.append, raising=False)
    specialist_sync.send_unit_failure_alert("sro-reestr-sync", "timeout", "")
    assert len(alerts) == 1
    assert "TimeoutStartSec" in alerts[0]
    assert "реестра" in alerts[0]


def test_systemd_on_failure_units_and_script():
    for name in ("sro-specialist-sync.service", "sro-reestr-sync.service"):
        text = (_VPS / name).read_text(encoding="utf-8")
        assert "OnFailure=sro-sync-alert@%p.service" in text
        assert "\r" not in text
    alert = (_VPS / "sro-sync-alert@.service").read_text(encoding="utf-8")
    assert "sync_failure_alert.sh %i" in alert
    assert not any(line.startswith("OnFailure=") for line in alert.splitlines())
    script = (_VPS / "sync_failure_alert.sh").read_text(encoding="utf-8")
    assert "\r" not in script
    assert "send_unit_failure_alert" in script
    assert "BOT_TOKEN" not in script
    assert "api.telegram.org" not in script
    install = (_VPS / "install.sh").read_text(encoding="utf-8")
    assert "sro-sync-alert@.service" in install
    subprocess.run(["bash", "-n", str(_VPS / "sync_failure_alert.sh")], check=True)


def _admin_config(monkeypatch, *, token: str, ids):
    import config_keys

    monkeypatch.setattr(config_keys, "BOT_TOKEN", token, raising=False)
    monkeypatch.setattr(config_keys, "BOT_ADMIN_IDS", ids, raising=False)


def test_notify_admins_logs_transport_error_without_token(monkeypatch, capsys):
    import specialist_sync
    from tests.support import FAKE_TG_TOKEN

    _admin_config(monkeypatch, token=FAKE_TG_TOKEN, ids=[101])

    def boom(*_args, **_kwargs):
        raise requests.ConnectionError(
            "Max retries exceeded with url: "
            f"https://api.telegram.org/bot{FAKE_TG_TOKEN}/sendMessage"
        )

    monkeypatch.setattr(specialist_sync.requests, "post", boom)
    specialist_sync.notify_admins("проверка")
    out = capsys.readouterr().out
    assert "админам не отправил: telegram 101:" in out
    assert "ConnectionError" in out
    assert FAKE_TG_TOKEN not in out
    assert "TEST_FAKE_TOKEN" not in out


def test_notify_admins_logs_telegram_description(monkeypatch, capsys):
    import specialist_sync
    from tests.support import FAKE_TG_TOKEN

    _admin_config(monkeypatch, token=FAKE_TG_TOKEN, ids=[101])

    class _Resp:
        status_code = 403

        def json(self):
            return {
                "ok": False,
                "error_code": 403,
                "description": "Forbidden: bot was blocked by the user",
            }

    monkeypatch.setattr(specialist_sync.requests, "post", lambda *_a, **_k: _Resp())
    specialist_sync.notify_admins("проверка")
    out = capsys.readouterr().out
    assert "telegram 101:" in out
    assert "bot was blocked by the user" in out
    assert "403" in out
    assert FAKE_TG_TOKEN not in out


def test_notify_admins_retries_transport_then_ok(monkeypatch, capsys):
    import specialist_sync
    from tests.support import FAKE_TG_TOKEN

    _admin_config(monkeypatch, token=FAKE_TG_TOKEN, ids=[101])
    calls = {"n": 0}

    class _Resp:
        status_code = 200

        def json(self):
            return {"ok": True}

    def post(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise requests.Timeout("timed out")
        return _Resp()

    monkeypatch.setattr(specialist_sync.requests, "post", post)
    specialist_sync.notify_admins("проверка")
    assert calls["n"] == 2
    assert "не отправил" not in capsys.readouterr().out


def test_notify_admins_names_empty_token(monkeypatch, capsys):
    import specialist_sync

    _admin_config(monkeypatch, token="   ", ids=[101])
    specialist_sync.notify_admins("проверка")
    out = capsys.readouterr().out
    assert "BOT_TOKEN пуст" in out
    assert "BOT_ADMIN_IDS пуст" not in out
