"""reestr_sync: разбор реестра, слияние карточек, запись кэша, итог ночного синка."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

import pytest
import requests

import reestr_sync as rs
from tests.support import FIXTURES, ROOT, FakeResponse, read_fixture

LIST_URL = "https://sro.example.test/reestr/"


# --- разбор страниц ---------------------------------------------------------


def test_parse_list_page_rows():
    entries = rs._parse_list_page(read_fixture("reestr_list_page1.html"), LIST_URL)
    by_inn = {e["inn"]: e for e in entries}

    assert set(by_inn) == {"7700000001", "7700000003", "770000000004"}
    first = by_inn["7700000001"]
    assert first["status"] == "Член СРО"
    assert first["short_name"] == "ООО «Тестстрой»"
    assert first["reg_date"] == "01.02.2015"
    assert first["uuid"] == "11111111-1111-1111-1111-111111111111"
    assert first["url"] == "https://sro.example.test/reestr/11111111-1111-1111-1111-111111111111/"
    assert by_inn["7700000003"]["status"] == "Исключен"


def test_list_page_pagination():
    assert rs._max_list_page(read_fixture("reestr_list_page1.html")) == 2
    assert rs._max_list_page("<html>без пагинации</html>") == 1


def test_sync_one_sro_list_reads_all_pages(monkeypatch):
    pages = {
        "https://www.srogen.ru/reestr/": read_fixture("reestr_list_page1.html"),
        "https://www.srogen.ru/reestr/?PAGEN_1=2": read_fixture("reestr_list_page2.html"),
    }
    monkeypatch.setattr(rs, "_fetch", lambda url: pages[url])
    by_inn: dict = {}

    added = rs.sync_one_sro_list("OGPS", by_inn, show_progress=False)

    assert added == 4
    assert set(by_inn) == {"7700000001", "7700000002", "7700000003", "770000000004"}
    mem = by_inn["7700000002"]["memberships"]["OGPS"]
    assert mem["sro_name"] == "ОГПС"
    assert mem["status"] == "Член СРО"


def test_parse_detail_page_full_card():
    detail = rs._parse_detail_page(read_fixture("reestr_detail_full.html"))

    assert detail["title"] == "ООО «Тестстрой»"
    assert detail["full_name"] == "Общество с ограниченной ответственностью «Тестстрой»"
    assert detail["reg_number"] == "ТЕСТ-0042"
    assert detail["location"] == "г. Тестоград, ул. Образцовая, д. 7"
    assert detail["director"] == "Генеральный директор Образцов Олег Олегович"
    assert detail["insurance_company"] == "АО «Тест-Страхование»"
    assert detail["insurance_sum"] == "5 000 000 руб."
    assert detail["ogrn"] == "1000000000001"
    assert detail["kf_level_vv"] == 2
    assert detail["kf_level_odo"] == 1
    assert detail["kf_sum_vv"] == "500 000 руб."
    assert detail["kf_sum_odo"] == "2 500 000 руб."
    assert detail["inspections_by_year"] == {
        "2025": "Нарушений не выявлено",
        "2024": "Выявлены нарушения, устранены",
    }
    assert detail["latest_disciplinary"] == {"date": "12.03.2024 г.", "measure": "Предупреждение"}
    assert "status" not in detail


def test_parse_detail_page_exclusion_sets_status():
    html = read_fixture("reestr_detail_full.html").replace(
        "<td>Предупреждение</td>", "<td>Исключение из членов СРО</td>"
    )
    assert rs._parse_detail_page(html)["status"] == "Исключен"


@pytest.mark.parametrize(
    "fixture_name",
    [
        "reestr_detail_antibot.html",
        "reestr_detail_truncated.html",
        "reestr_detail_new_layout.html",
    ],
)
def test_non_card_pages_are_empty(fixture_name):
    detail = rs._parse_detail_page(read_fixture(fixture_name))
    assert rs._detail_is_empty(detail)


def test_full_card_is_not_empty():
    assert not rs._detail_is_empty(rs._parse_detail_page(read_fixture("reestr_detail_full.html")))


# --- слияние карточки с сохранёнными данными --------------------------------


def _stored_membership() -> dict:
    return {
        "inn": "7700000001",
        "sro_id": "OGPS",
        "sro_name": "ОГПС",
        "url": "https://sro.example.test/reestr/11111111-1111-1111-1111-111111111111/",
        "status": "Член СРО",
        "short_name": "ООО «Тестстрой»",
        "full_name": "ООО «Тестстрой» (старое)",
        "reg_number": "ТЕСТ-0001",
        "director": "Старый Директор",
        "location": "г. Тестоград, старый адрес",
        "kf_level_vv": 3,
        "kf_sum_vv": "300 000 руб.",
        "inspections": [{"year": "2023", "result": "Нарушений не выявлено"}],
        "inspections_by_year": {"2023": "Нарушений не выявлено"},
        "disciplinary_measures": [{"date": "01.01.2023", "measure": "Замечание"}],
        "latest_disciplinary": {"date": "01.01.2023", "measure": "Замечание"},
    }


@pytest.mark.parametrize(
    "fixture_name",
    [
        "reestr_detail_antibot.html",
        "reestr_detail_truncated.html",
        "reestr_detail_new_layout.html",
    ],
)
def test_empty_card_raises_and_keeps_stored(monkeypatch, fixture_name):
    stored = _stored_membership()
    snapshot = json.loads(json.dumps(stored))
    monkeypatch.setattr(rs, "_fetch", lambda _url: read_fixture(fixture_name))

    with pytest.raises(ValueError, match="пустая карточка"):
        rs.fetch_reestr_detail(stored)

    assert stored == snapshot


def test_partial_card_updates_only_filled_fields(monkeypatch):
    stored = _stored_membership()
    monkeypatch.setattr(rs, "_fetch", lambda _url: read_fixture("reestr_detail_partial.html"))

    merged = rs.fetch_reestr_detail(stored)

    assert merged["reg_number"] == "ТЕСТ-0099"
    assert merged["full_name"] == "Общество с ограниченной ответственностью «Тестстрой» (новое)"
    assert merged["director"] == "Старый Директор"
    assert merged["location"] == "г. Тестоград, старый адрес"
    assert merged["kf_level_vv"] == 3
    assert merged["kf_sum_vv"] == "300 000 руб."
    assert merged["inspections_by_year"] == {"2023": "Нарушений не выявлено"}
    assert merged["latest_disciplinary"] == {"date": "01.01.2023", "measure": "Замечание"}
    assert merged["status"] == "Член СРО"


def test_full_card_overwrites_stored(monkeypatch):
    stored = _stored_membership()
    stored["sync_error"] = "прошлая ошибка"
    monkeypatch.setattr(rs, "_fetch", lambda _url: read_fixture("reestr_detail_full.html"))

    merged = rs.fetch_reestr_detail(stored)

    assert merged["director"] == "Генеральный директор Образцов Олег Олегович"
    assert merged["kf_level_vv"] == 2
    assert merged["inspections_by_year"]["2025"] == "Нарушений не выявлено"
    assert "sync_error" not in merged


def test_apply_fetched_detail_ignores_blank_values():
    stored = _stored_membership()
    by_inn = {"7700000001": {"inn": "7700000001", "memberships": {"OGPS": stored}}}
    incoming = {
        "director": None,
        "location": "",
        "kf_level_vv": None,
        "inspections": [],
        "inspections_by_year": {},
        "reg_number": "ТЕСТ-0500",
    }

    rs._apply_fetched_detail(by_inn, stored, incoming)

    saved = by_inn["7700000001"]["memberships"]["OGPS"]
    assert saved["director"] == "Старый Директор"
    assert saved["location"] == "г. Тестоград, старый адрес"
    assert saved["kf_level_vv"] == 3
    assert saved["inspections_by_year"] == {"2023": "Нарушений не выявлено"}
    assert saved["reg_number"] == "ТЕСТ-0500"


def test_enrich_entry_keeps_cache_on_empty_page(monkeypatch):
    stored = _stored_membership()
    del stored["inspections_by_year"]
    cache = {"7700000001": {"inn": "7700000001", "title": "T", "memberships": {"OGPS": stored}}}
    monkeypatch.setattr(rs, "_fetch", lambda _url: read_fixture("reestr_detail_antibot.html"))

    rs.enrich_reestr_entry("7700000001", cache, timeout=5)

    saved = cache["7700000001"]["memberships"]["OGPS"]
    assert saved["director"] == "Старый Директор"
    assert saved["kf_level_vv"] == 3


def test_refresh_inspections_counts_errors_and_keeps_data(monkeypatch, isolated_files):
    def mem(uuid_tail: str, inn: str) -> dict:
        row = _stored_membership()
        row["inn"] = inn
        row["url"] = f"https://sro.example.test/reestr/{uuid_tail}/"
        return row

    by_inn = {
        inn: {"inn": inn, "title": inn, "memberships": {"OGPS": mem(tail, inn)}}
        for inn, tail in (("7700000001", "ok"), ("7700000002", "stub"), ("7700000003", "down"))
    }
    rs._save_cache(by_inn)

    def fake_fetch(url: str) -> str:
        if url.endswith("/ok/"):
            return read_fixture("reestr_detail_full.html")
        if url.endswith("/stub/"):
            return read_fixture("reestr_detail_antibot.html")
        raise requests.ConnectionError("сайт не ответил")

    monkeypatch.setattr(rs, "_fetch", fake_fetch)

    result = rs.sync_all_sro_refresh_inspections(show_progress=False)

    assert result["refreshed"] == 3
    assert result["errors"] == 2
    saved = rs.load_reestr_cache()
    assert saved["7700000001"]["memberships"]["OGPS"]["kf_level_vv"] == 2
    for inn in ("7700000002", "7700000003"):
        kept = saved[inn]["memberships"]["OGPS"]
        assert kept["director"] == "Старый Директор"
        assert kept["inspections_by_year"] == {"2023": "Нарушений не выявлено"}
        assert kept["sync_error"]


# --- запись и чтение кэша ---------------------------------------------------


def _org(title: str) -> dict:
    return {"inn": "1", "title": title, "memberships": {}}


def test_save_cache_keeps_previous_as_backup(isolated_files):
    path = rs.CACHE_FILE
    rs._save_cache({"1": _org("A")})
    rs._save_cache({"1": _org("B"), "2": _org("C")})

    with open(path, encoding="utf-8") as fh:
        main = json.load(fh)
    with open(path + ".bak", encoding="utf-8") as fh:
        backup = json.load(fh)
    assert main["organizations"]["1"]["title"] == "B"
    assert main["count"] == 2
    assert backup["organizations"]["1"]["title"] == "A"
    assert "2" not in backup["organizations"]
    leftovers = [p for p in os.listdir(isolated_files) if p.endswith(".tmp")]
    assert leftovers == []


def test_save_cache_readable_by_others(isolated_files):
    rs._save_cache({"1": _org("A")})
    mode = os.stat(rs.CACHE_FILE).st_mode & 0o777
    assert mode & 0o044 == 0o044


def test_interrupted_save_keeps_main_file(monkeypatch, isolated_files):
    rs._save_cache({"1": _org("A")})
    with open(rs.CACHE_FILE, encoding="utf-8") as fh:
        before = fh.read()

    def broken_dump(_payload, file, **_kwargs):
        file.write('{"organizations": {')
        raise OSError("диск переполнен")

    monkeypatch.setattr(rs.json, "dump", broken_dump)
    with pytest.raises(OSError):
        rs._save_cache({"9": _org("Z")})

    with open(rs.CACHE_FILE, encoding="utf-8") as fh:
        assert fh.read() == before
    leftovers = [p for p in os.listdir(isolated_files) if p.endswith(".tmp")]
    assert leftovers == []


def test_load_reads_backup_when_main_broken(isolated_files, capsys):
    rs._save_cache({"1": _org("A")})
    rs._save_cache({"1": _org("B")})
    with open(rs.CACHE_FILE, "w", encoding="utf-8") as fh:
        fh.write('{"organizations": {"1": ')

    loaded = rs.load_reestr_cache()

    assert loaded["1"]["title"] == "A"
    out = capsys.readouterr().out
    assert "повреждён" in out
    assert "резерв" in out


def test_load_reads_backup_when_main_missing(isolated_files, capsys):
    rs._save_cache({"1": _org("A")})
    rs._save_cache({"1": _org("B")})
    os.unlink(rs.CACHE_FILE)

    assert rs.load_reestr_cache()["1"]["title"] == "A"
    assert "резерв" in capsys.readouterr().out


def test_load_both_broken_returns_empty_with_warning(isolated_files, capsys):
    for path in (rs.CACHE_FILE, rs.CACHE_FILE + ".bak"):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{broken")

    assert rs.load_reestr_cache() == {}
    assert "повреждён" in capsys.readouterr().out


def test_load_without_any_file_is_silent(isolated_files, capsys):
    assert rs.load_reestr_cache() == {}
    assert capsys.readouterr().out == ""


def test_load_rejects_json_without_organizations(isolated_files, capsys):
    rs._save_cache({"1": _org("A")})
    rs._save_cache({"1": _org("B")})
    with open(rs.CACHE_FILE, "w", encoding="utf-8") as fh:
        json.dump(["не", "объект"], fh)

    assert rs.load_reestr_cache()["1"]["title"] == "A"


# --- итог ночного синка -----------------------------------------------------


@pytest.mark.parametrize(
    ("result", "fails"),
    [
        pytest.param({"sro_total": 15, "sro_updated": 0, "refreshed": 100, "errors": 0}, True, id="0-sro"),
        pytest.param({"sro_total": 15, "sro_updated": 1, "refreshed": 100, "errors": 0}, False, id="1-sro"),
        pytest.param({"sro_total": 15, "sro_updated": 15, "refreshed": 100, "errors": 20}, False, id="ровно-20"),
        pytest.param({"sro_total": 15, "sro_updated": 15, "refreshed": 100, "errors": 21}, True, id="21-процент"),
        pytest.param({"sro_total": 15, "sro_updated": 15, "refreshed": 8, "errors": 8}, True, id="все-карточки"),
        pytest.param({"sro_total": 15, "sro_updated": 15, "refreshed": 0, "errors": 0}, False, id="нет-карточек"),
        pytest.param({"sro_total": 0, "sro_updated": 0, "refreshed": 0, "errors": 0}, False, id="пустой-список"),
    ],
)
def test_daily_sync_failure_reason(result, fails):
    reason = rs.daily_sync_failure_reason(result)
    assert (reason is not None) is fails


def test_daily_reason_mentions_counts():
    reason = rs.daily_sync_failure_reason(
        {"sro_total": 15, "sro_updated": 15, "refreshed": 100, "errors": 21}
    )
    assert "21/100" in reason


def test_list_only_counts_failed_and_empty_sro(monkeypatch, isolated_files):
    def fake_fetch(url: str) -> str:
        if "srogen.ru" in url:
            return read_fixture("reestr_list_page2.html").replace("PAGEN_1=2", "PAGEN_1=1")
        if "sro-mots.ru" in url:
            return "<html><body>Реестр временно недоступен</body></html>"
        raise requests.ConnectionError("нет связи")

    monkeypatch.setattr(rs, "_fetch", fake_fetch)

    res = rs.sync_all_sro_list_only(show_progress=False)

    assert res["sro_total"] == len(rs.SRO_SOURCES)
    assert res["sro_updated"] == 1
    assert res["sro_failed"] == len(rs.SRO_SOURCES) - 1


# --- код выхода reestr_sync.py --daily ---------------------------------------

_DAILY_RUNNER = textwrap.dedent(
    """
    import runpy, sys
    sys.path.insert(0, {root!r})
    from tests import support
    support.block_network()
    import requests

    mode = {mode!r}
    full = support.read_fixture("reestr_detail_full.html")
    listing = support.read_fixture("reestr_list_page2.html").replace("PAGEN_1=2", "PAGEN_1=1")

    def fake_get(url, **_kw):
        if mode == "down":
            raise requests.ConnectionError("нет связи")
        if url.rstrip("/").endswith("/reestr"):
            return support.FakeResponse(listing)
        return support.FakeResponse(full)

    requests.get = fake_get
    sys.argv = ["reestr_sync.py", "--daily"]
    runpy.run_path({script!r}, run_name="__main__")
    """
)


def _run_daily(tmp_path, mode: str) -> subprocess.CompletedProcess:
    script = tmp_path / "reestr_sync.py"
    script.write_text((ROOT / "reestr_sync.py").read_text(encoding="utf-8"), encoding="utf-8")
    runner = _DAILY_RUNNER.format(root=str(ROOT), mode=mode, script=str(script))
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, "-c", runner],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )


def test_daily_cli_exits_1_when_no_sro_updated(tmp_path):
    proc = _run_daily(tmp_path, "down")

    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "FAIL: ни одна СРО не обновила список" in proc.stdout


def test_daily_cli_exits_0_on_success(tmp_path):
    proc = _run_daily(tmp_path, "ok")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "FAIL" not in proc.stdout
    with open(tmp_path / "reestr_cache.json", encoding="utf-8") as fh:
        saved = json.load(fh)["organizations"]
    mem = saved["7700000002"]["memberships"]["OGPS"]
    assert mem["kf_level_vv"] == 2


def test_fixtures_have_no_real_looking_tokens():
    for path in FIXTURES.iterdir():
        text = path.read_text(encoding="utf-8")
        assert "/bot" not in text
        assert "Authorization" not in text
