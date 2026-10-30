"""Синк и поиск специалистов: HTTP только через подставленный transport."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
import requests

from sro_profiles import SRO_ACTIVITY
from specialist_reestr import (
    PARTNER_REGISTRY,
    SroTarget,
    connect,
    director_fio_norm,
    ensure_schema,
    experts_published_empty,
    extract_specialists,
    format_search_reply,
    normalize_person,
    save_member,
    search_people,
)
from tests.support import TEST_UID, keyboard_buttons
from specialist_sync import RegistryClient, SyncRequestError, sync_all


def test_partner_registry_covers_fifteen_sros():
    assert set(PARTNER_REGISTRY) == set(SRO_ACTIVITY)
    ids = [(registry, rid) for registry, rid, _reg in PARTNER_REGISTRY.values()]
    assert len(ids) == len(set(ids))
    assert PARTNER_REGISTRY["OGPS"] == ("nostroy", 87, "СРО-С-020-22072009")


def test_normalize_yo_and_spaces():
    assert normalize_person("  Пётр   Иванов  ") == "петр иванов"
    assert director_fio_norm("Генеральный директор Кузнецов Олег Иванович") == (
        "кузнецов олег иванович"
    )


def test_nostroy_experts_and_nopriz_specialists_data():
    nostroy = {
        "experts_by_category": {
            "regular": [
                {
                    "fio": "Сидоров Пётр Сергеевич",
                    "number": "C-77-100001",
                    "expert_type": {"title": "Специалист"},
                }
            ],
            "danger": [
                {
                    "fio": "Сидоров Пётр Сергеевич",
                    "number": "C-77-100001",
                    "expert_type": {"title": "Особо-опасные работы"},
                }
            ],
        }
    }
    rows = extract_specialists(nostroy)
    assert len(rows) == 1
    assert rows[0]["fio_norm"] == "сидоров петр сергеевич"
    assert rows[0]["nrs_number"] == "С-77-100001"
    assert "Специалист" in rows[0]["category"]
    assert "Особо-опасные" in rows[0]["category"]

    # Живая карточка НОПРИЗ: ключа experts_by_category нет, список в specialists_data.
    nopriz = {
        "director": "Генеральный директор Кашаев Алексей Сергеевич",
        "specialists_data": {
            "regular": [
                {
                    "fio": "Тюрина  Елена  Александровна",
                    "registration_number": "П-006497",
                    "spec_type": {"code": "regular", "title": "Специалист"},
                }
            ],
            "danger": [],
            "other": [],
        },
    }
    assert "experts_by_category" not in nopriz
    parsed = extract_specialists(nopriz)
    assert parsed == [
        {
            "fio": "Тюрина  Елена  Александровна",
            "fio_norm": "тюрина елена александровна",
            "nrs_number": "П-006497",
            "category": "Специалист",
        }
    ]
    assert extract_specialists({"director": "Иванов"}) == []


def _list_payload(rows, pages):
    return {
        "success": True,
        "data": {"count": len(rows) if pages == 1 else 2, "countPages": pages, "data": rows},
    }


def _nostroy_row(member_id, stamp="01.01.2026 00:00:00"):
    return {
        "id": member_id,
        "inn": f"770000000{member_id}",
        "short_description": f"ООО Номер {member_id}",
        "member_status": {"id": 1, "title": "Является членом"},
        "last_updated_at_date_time_string": stamp,
        "last_updated_experts_at_date_time_string": stamp,
        "sro": {"id": 87},
    }


def _nostroy_card(member_id, fio):
    return {
        "id": member_id,
        "inn": f"770000000{member_id}",
        "short_description": f"ООО Номер {member_id}",
        "member_status": {"title": "Является членом"},
        "director": f"Генеральный директор {fio}",
        "experts_by_category": {
            "regular": [
                {
                    "fio": fio,
                    "number": f"C-77-10000{member_id}",
                    "expert_type": {"title": "Специалист"},
                }
            ]
        },
    }


def _nopriz_row():
    return {
        "id": 50,
        "inn": "7700000050",
        "short_description": "ООО Проект",
        "member_status": {"title": "Является членом"},
        "sro": {"id": 85},
    }


def _nopriz_card():
    return {
        "id": 50,
        "inn": "7700000050",
        "short_description": "ООО Проект",
        "member_status": {"title": "Является членом"},
        "director": "",
        "specialists_data": {
            "regular": [
                {
                    "fio": "Орлова Анна",
                    "registration_number": "П-006497",
                    "spec_type": {"title": "Специалист"},
                }
            ]
        },
    }


class ScriptedApi:
    def __init__(self, *, drop_second=False, fail_info_id=None):
        self.calls: list[tuple[str, dict]] = []
        self.drop_second = drop_second
        self.fail_info_id = fail_info_id

    def __call__(self, url: str, body: dict, timeout: float):
        self.calls.append((url, body))
        if url.endswith("/member/list"):
            assert body["filters"] == {"member_status": 1}
            assert body["pageCount"] == "20"
            assert body["sortBy"] == {"inn": "ASC"}
            page = body["page"]
            if "/sro/87/" in url:
                if self.drop_second:
                    return 200, _list_payload([_nostroy_row(1)], 1)
                if page == 1:
                    return 200, _list_payload([_nostroy_row(1)], 2)
                if page == 2:
                    return 200, _list_payload([_nostroy_row(2)], 2)
            if "/sro/85/" in url:
                return 200, _list_payload([_nopriz_row()], 1)
            raise AssertionError(url)
        if url.endswith("/member/1/info"):
            return 200, {"success": True, "data": _nostroy_card(1, "Сидоров Пётр Сергеевич")}
        if url.endswith("/member/2/info"):
            if self.fail_info_id == 2:
                raise RuntimeError("обрыв")
            return 200, {"success": True, "data": _nostroy_card(2, "Иванова Мария")}
        if url.endswith("/member/50/info"):
            card = _nopriz_card()
            assert "experts_by_category" not in card
            return 200, {"success": True, "data": card}
        raise AssertionError(url)


def _client(api: ScriptedApi) -> RegistryClient:
    return RegistryClient(api, min_interval=0, sleep=lambda _s: None, retries=2)


def _info_calls(api: ScriptedApi, suffix: str) -> int:
    return sum(1 for url, _body in api.calls if url.endswith(suffix))


def test_sync_both_registries_then_skip_unchanged_nostroy(tmp_path):
    db = tmp_path / "spec.sqlite"
    api = ScriptedApi()
    assert sync_all(db_path=db, codes=["OGPS", "OGPP"], fresh=True, client=_client(api)) == 0
    assert _info_calls(api, "/member/1/info") == 1
    assert _info_calls(api, "/member/2/info") == 1
    assert _info_calls(api, "/member/50/info") == 1
    assert any(body.get("page") == 2 for _url, body in api.calls if body.get("pageCount") == "20")

    reply = format_search_reply("Сидоров Пётр", db=db)
    assert "Сидоров Пётр Сергеевич" in reply
    assert "С-77-100001" in reply
    assert "ООО Номер 1" in reply
    assert "7700000001" in reply
    assert "ОГПС" in reply
    assert "reestr.nostroy.ru/member/1" in reply

    nopriz = format_search_reply("орлова", db=db)
    assert "П-006497" in nopriz
    assert "reestr.nopriz.ru/member/50" in nopriz
    assert "ООО Проект" in nopriz

    api.calls.clear()
    assert sync_all(db_path=db, codes=["OGPS", "OGPP"], fresh=True, client=_client(api)) == 0
    # НОСТРОЙ: отпечаток списка тот же — карточки не качаем.
    assert _info_calls(api, "/member/1/info") == 0
    assert _info_calls(api, "/member/2/info") == 0
    # НОПРИЗ: в списке нет даты специалистов — карточку читаем снова.
    assert _info_calls(api, "/member/50/info") == 1


def test_sync_drops_member_missing_from_list(tmp_path):
    db = tmp_path / "spec.sqlite"
    assert sync_all(
        db_path=db, codes=["OGPS"], fresh=True, client=_client(ScriptedApi())
    ) == 0
    assert search_people("иванова", db=db).status == "ok"
    api = ScriptedApi(drop_second=True)
    assert sync_all(db_path=db, codes=["OGPS"], fresh=True, client=_client(api)) == 0
    assert search_people("иванова", db=db).status == "none"
    assert search_people("сидоров", db=db).status == "ok"


def _payload(rows, *, count, pages):
    return {
        "success": True,
        "data": {"count": count, "countPages": pages, "data": rows},
    }


class _TwoPageDespiteCountPages:
    """countPages врёт «1 страница», но count больше и вторая страница есть."""

    def __init__(self):
        self.calls = []

    def __call__(self, url, body, timeout):
        self.calls.append((url, body))
        if url.endswith("/member/list"):
            page = body["page"]
            if page == 1:
                return 200, _payload([_nostroy_row(1)], count=2, pages=1)
            if page == 2:
                return 200, _payload([_nostroy_row(2)], count=2, pages=1)
            return 200, _payload([], count=2, pages=1)
        if url.endswith("/member/1/info"):
            return 200, {"success": True, "data": _nostroy_card(1, "Сидоров Пётр Сергеевич")}
        if url.endswith("/member/2/info"):
            return 200, {"success": True, "data": _nostroy_card(2, "Иванова Мария")}
        raise AssertionError(url)


def test_list_follows_count_when_count_pages_is_short(tmp_path):
    db = tmp_path / "spec.sqlite"
    api = _TwoPageDespiteCountPages()
    assert sync_all(db_path=db, codes=["OGPS"], fresh=True, client=_client(api)) == 0
    assert search_people("сидоров", db=db).status == "ok"
    assert search_people("иванова", db=db).status == "ok"
    assert any(body.get("page") == 2 for _url, body in api.calls)


class _ShortListApi:
    """Вторая страница пустая, хотя count обещает двух членов."""

    def __call__(self, url, body, timeout):
        if url.endswith("/member/list"):
            page = body["page"]
            if page == 1:
                return 200, _payload([_nostroy_row(1)], count=2, pages=2)
            return 200, _payload([], count=2, pages=2)
        if url.endswith("/member/1/info"):
            return 200, {"success": True, "data": _nostroy_card(1, "Сидоров Пётр Сергеевич")}
        raise AssertionError(url)


def test_short_list_does_not_drop_members_already_stored(tmp_path):
    db = tmp_path / "spec.sqlite"
    assert sync_all(
        db_path=db, codes=["OGPS"], fresh=True, client=_client(ScriptedApi())
    ) == 0
    assert search_people("иванова", db=db).status == "ok"
    assert sync_all(
        db_path=db, codes=["OGPS"], fresh=True, client=_client(_ShortListApi())
    ) == 1
    # Список битый — Иванову из базы не стираем.
    assert search_people("иванова", db=db).status == "ok"
    assert search_people("сидоров", db=db).status == "ok"


def test_refetch_card_when_expert_date_has_no_specialist_rows(tmp_path):
    db = tmp_path / "spec.sqlite"
    api = ScriptedApi()
    assert sync_all(db_path=db, codes=["OGPS"], fresh=True, client=_client(api)) == 0
    from specialist_reestr import connect

    conn = connect(db, write=True)
    try:
        conn.execute("DELETE FROM specialists")
        conn.commit()
    finally:
        conn.close()
    api.calls.clear()
    assert sync_all(db_path=db, codes=["OGPS"], fresh=True, client=_client(api)) == 0
    assert _info_calls(api, "/member/1/info") == 1
    assert _info_calls(api, "/member/2/info") == 1
    assert search_people("иванова", db=db).status == "ok"


def test_resume_skips_cards_already_stored_in_this_run(tmp_path):
    db = tmp_path / "spec.sqlite"
    api = ScriptedApi(fail_info_id=2)
    with pytest.raises(RuntimeError):
        sync_all(db_path=db, codes=["OGPS"], fresh=True, client=_client(api))
    assert _info_calls(api, "/member/1/info") == 1
    api.fail_info_id = None
    api.calls.clear()
    assert sync_all(db_path=db, codes=["OGPS"], fresh=False, client=_client(api)) == 0
    assert _info_calls(api, "/member/1/info") == 0
    assert _info_calls(api, "/member/2/info") == 1


def test_search_limit_director_fallback_and_empty(tmp_path):
    db = tmp_path / "spec.sqlite"
    assert sync_all(
        db_path=db, codes=["OGPS", "OGPP"], fresh=True, client=_client(ScriptedApi())
    ) == 0

    # Тот же человек в специалистах и в поле руководителя — одна строка, не «только руководитель».
    same = format_search_reply("Сидоров Пётр Сергеевич", db=db)
    assert "С-77-100001" in same
    assert "В списке специалистов НРС такого ФИО нет" not in same

    from specialist_reestr import SroTarget, connect, ensure_schema, save_member

    conn = connect(db, write=True)
    try:
        ensure_schema(conn)
        target = SroTarget("OSO", "ОСО", "nostroy", 162, "СРО-С-095-02122009")
        for index in range(11):
            save_member(
                conn,
                target,
                {"id": 1000 + index, "inn": "1000000000", "short_description": "ООО Люди"},
                {
                    "id": 1000 + index,
                    "short_description": "ООО Люди",
                    "inn": "1000000000",
                    "director": "",
                    "experts_by_category": {
                        "regular": [
                            {
                                "fio": f"Фролов Иван {index}",
                                "number": f"С-1-{index}",
                                "expert_type": {"title": "Специалист"},
                            }
                        ]
                    },
                },
                run_id="t",
                updated_at="2026-10-15T00:00:00+00:00",
            )
        save_member(
            conn,
            target,
            {"id": 2000, "inn": "2000000000", "short_description": "ООО Шеф"},
            {
                "id": 2000,
                "short_description": "ООО Шеф",
                "inn": "2000000000",
                "director": "Генеральный директор Кузнецов Олег",
                "experts_by_category": {},
            },
            run_id="t",
            updated_at="2026-10-15T00:00:00+00:00",
        )
        conn.commit()
    finally:
        conn.close()

    many = format_search_reply("Фролов", db=db)
    assert many.count("👤") == 10
    assert "из 11" in many
    assert "Уточните" in many

    boss = format_search_reply("Кузнецов", db=db)
    assert "руководитель" in boss.lower()
    assert "ООО Шеф" in boss
    assert "В списке специалистов НРС такого ФИО нет" in boss

    missing = format_search_reply("Зюзюкин", db=db)
    assert "Никого не нашёл" in missing
    assert "специалисты НРС" in missing

    assert "хотя бы две" in format_search_reply("я", db=db)
    assert "не загружен" in format_search_reply("Иванов", db=tmp_path / "missing.sqlite")


def test_client_retries_503_and_does_not_retry_404():
    state = {"n": 0}

    def flaky(url, body, timeout):
        state["n"] += 1
        if state["n"] < 3:
            return 503, {}
        return 200, {"success": True, "data": {"ok": True}}

    slept: list[float] = []
    client = RegistryClient(flaky, min_interval=0, sleep=slept.append, retries=4)
    assert client.post("https://reestr.nostroy.ru/api/member/1/info", {})["data"]["ok"] is True
    assert state["n"] == 3
    assert slept  # пауза между повторами

    calls = {"n": 0}

    def missing(url, body, timeout):
        calls["n"] += 1
        return 404, {}

    client = RegistryClient(missing, min_interval=0, sleep=lambda _s: None, retries=4)
    with pytest.raises(SyncRequestError):
        client.post("https://reestr.nopriz.ru/api/member/1/info", {})
    assert calls["n"] == 1


def test_client_paces_requests():
    clock = {"t": 0.0}

    def monotonic():
        return clock["t"]

    slept: list[float] = []

    def sleep(seconds):
        slept.append(seconds)
        clock["t"] += seconds

    def transport(url, body, timeout):
        clock["t"] += 0.1
        return 200, {"success": True, "data": {}}

    client = RegistryClient(
        transport,
        min_interval=0.4,
        timeout=5,
        retries=1,
        sleep=sleep,
        monotonic=monotonic,
    )
    client.post("https://reestr.nostroy.ru/api/sro/87/member/list", {})
    client.post("https://reestr.nostroy.ru/api/sro/87/member/list", {})
    assert slept[0] == pytest.approx(0.4)
    assert slept[1] == pytest.approx(0.3)


def _seed_one(path, *, member_id=10, fio="Сидоров Пётр Сергеевич"):
    target = SroTarget("OGPS", "ОГПС", "nostroy", 87, "СРО-С-020-22072009")
    conn = connect(path, write=True)
    try:
        ensure_schema(conn)
        save_member(
            conn,
            target,
            {
                "id": member_id,
                "inn": "7700000099",
                "short_description": "ООО Проба",
                "member_status": {"title": "Является членом"},
            },
            {
                "id": member_id,
                "inn": "7700000099",
                "short_description": "ООО Проба",
                "director": f"Генеральный директор {fio}",
                "member_status": {"title": "Является членом"},
                "experts_by_category": {
                    "regular": [
                        {
                            "fio": fio,
                            "number": "C-77-100001",
                            "expert_type": {"title": "Специалист"},
                        }
                    ]
                },
            },
            run_id="t",
            updated_at="2026-10-15T00:00:00+00:00",
        )
        conn.commit()
    finally:
        conn.close()


def test_max_member_searches_by_fio(max_bot):
    """Кнопка доступна обычному пользователю, не только контролёру."""
    from specialist_reestr import db_path

    _seed_one(db_path())
    labels = [text for _kind, text, _payload in keyboard_buttons(max_bot.m.main_keyboard(TEST_UID))]
    assert "👤 Где работает специалист (НОСТРОЙ/НОПРИЗ)" in labels

    max_bot.m.handle_callback(TEST_UID, "menu:spec", {})
    assert "ФИО" in max_bot.blob()
    max_bot.clear()
    max_bot.m.handle_text(TEST_UID, "Сидоров", {})
    blob = max_bot.blob()
    assert "Сидоров Пётр Сергеевич" in blob
    assert "С-77-100001" in blob
    assert "reestr.nostroy.ru/member/10" in blob
    assert "ООО Проба" in blob

    max_bot.clear()
    max_bot.m.handle_text(TEST_UID, "/fio", {})
    assert "Поиск специалиста по ФИО" in max_bot.blob()


def test_max_fio_outside_mode_does_not_open_local_registry(max_bot):
    from specialist_reestr import db_path

    _seed_one(db_path())
    max_bot.m.handle_text(TEST_UID, "Сидоров Пётр", {})
    assert "С-77-100001" not in max_bot.blob()


class _ListApi:
    """Список членов с заданными id и своим count. Карточки — обычные."""

    def __init__(self, member_ids, *, count=None, omit_count=False):
        self.member_ids = list(member_ids)
        self.count = len(self.member_ids) if count is None else count
        self.omit_count = omit_count
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url, body, timeout):
        self.calls.append((url, body))
        if url.endswith("/member/list"):
            rows = [_nostroy_row(member_id) for member_id in self.member_ids]
            data = {"countPages": 1, "data": rows}
            if not self.omit_count:
                data["count"] = self.count
            return 200, {"success": True, "data": data}
        prefix = "/member/"
        if "/member/" in url and url.endswith("/info"):
            member_id = int(url.rstrip("/").split("/")[-2])
            fios = {
                1: "Сидоров Пётр Сергеевич",
                2: "Иванова Мария",
                3: "Кузнецов Олег",
                4: "Орлова Анна",
            }
            fio = fios.get(member_id, f"Специалист {member_id}")
            return 200, {"success": True, "data": _nostroy_card(member_id, fio)}
        raise AssertionError(url)


class _EmptyCardApi(_ListApi):
    """Тот же состав, но отпечаток списка новый и карточка члена 1 пустая.

    Новый отпечаток не даёт _should_skip пропустить загрузку: иначе пустой
    ответ просто не дошёл бы до save_member.
    """

    def __init__(self, member_ids, card_for_1, stamp="02.02.2026 00:00:00"):
        super().__init__(member_ids)
        self.card_for_1 = card_for_1
        self.stamp = stamp

    def __call__(self, url, body, timeout):
        self.calls.append((url, body))
        if url.endswith("/member/list"):
            rows = [_nostroy_row(member_id, stamp=self.stamp) for member_id in self.member_ids]
            return 200, {
                "success": True,
                "data": {"count": len(rows), "countPages": 1, "data": rows},
            }
        if url.endswith("/member/1/info"):
            return 200, {"success": True, "data": self.card_for_1}
        return _ListApi.__call__(self, url, body, timeout)


def test_empty_member_list_does_not_wipe_sro(tmp_path, monkeypatch):
    """Пустой успешный список (count 0 и без count) не удаляет членов СРО."""
    import specialist_sync

    alerts: list[str] = []
    monkeypatch.setattr(specialist_sync, "notify_admins", alerts.append, raising=False)
    db = tmp_path / "spec.sqlite"
    assert sync_all(
        db_path=db, codes=["OGPS"], fresh=True, client=_client(_ListApi([1, 2]))
    ) == 0
    assert search_people("иванова", db=db).status == "ok"
    assert search_people("сидоров", db=db).status == "ok"

    alerts.clear()
    rc = sync_all(
        db_path=db,
        codes=["OGPS"],
        fresh=True,
        client=_client(_ListApi([], count=0)),
    )
    assert search_people("иванова", db=db).status == "ok"
    assert search_people("сидоров", db=db).status == "ok"
    assert rc == 1
    assert alerts
    assert "OGPS" in alerts[0]

    alerts.clear()
    rc = sync_all(
        db_path=db,
        codes=["OGPS"],
        fresh=True,
        client=_client(_ListApi([], omit_count=True)),
    )
    assert search_people("иванова", db=db).status == "ok"
    assert search_people("сидоров", db=db).status == "ok"
    assert rc == 1
    assert alerts


def test_shrunk_member_list_does_not_wipe_sro(tmp_path, monkeypatch):
    """Список меньше половины уже лежащих в базе не вычищает остальных."""
    import specialist_sync

    alerts: list[str] = []
    monkeypatch.setattr(specialist_sync, "notify_admins", alerts.append, raising=False)
    db = tmp_path / "spec.sqlite"
    assert sync_all(
        db_path=db, codes=["OGPS"], fresh=True, client=_client(_ListApi([1, 2, 3, 4]))
    ) == 0
    for fio in ("сидоров", "иванова", "кузнецов", "орлова"):
        assert search_people(fio, db=db).status == "ok"

    rc = sync_all(
        db_path=db, codes=["OGPS"], fresh=True, client=_client(_ListApi([1]))
    )
    for fio in ("сидоров", "иванова", "кузнецов", "орлова"):
        assert search_people(fio, db=db).status == "ok", fio
    assert rc == 1
    assert alerts
    assert "OGPS" in alerts[0]


def test_empty_card_does_not_wipe_specialists(tmp_path):
    """Пустая и невалидная карточка не стирает уже сохранённых специалистов."""
    from specialist_reestr import connect, stored_specialist_count

    db = tmp_path / "spec.sqlite"
    assert sync_all(
        db_path=db, codes=["OGPS"], fresh=True, client=_client(_ListApi([1, 2]))
    ) == 0
    assert search_people("сидоров", db=db).status == "ok"

    rc = sync_all(
        db_path=db,
        codes=["OGPS"],
        fresh=True,
        client=_client(_EmptyCardApi([1, 2], {})),
    )
    # Пустой data:{} не должен стереть уже лежащего специалиста.
    assert search_people("сидоров", db=db).status == "ok"
    assert search_people("иванова", db=db).status == "ok"
    assert rc == 0

    target = SroTarget("OGPS", "ОГПС", "nostroy", 87, "СРО-С-020-22072009")
    conn = connect(db, write=True)
    try:
        before = stored_specialist_count(conn, "nostroy", 1)
        assert before >= 1
        row = _nostroy_row(1)
        for bad_card in ({}, {"id": 1}, {"unexpected": True}):
            save_member(
                conn,
                target,
                row,
                bad_card,
                run_id="bad",
                updated_at="2026-10-18T00:00:00+00:00",
            )
            assert stored_specialist_count(conn, "nostroy", 1) == before
        conn.commit()
    finally:
        conn.close()
    assert search_people("сидоров", db=db).status == "ok"


def _member_ids(db):
    conn = connect(db)
    try:
        rows = conn.execute(
            "SELECT member_id FROM members ORDER BY member_id"
        ).fetchall()
        return [int(row[0]) for row in rows]
    finally:
        conn.close()


def _run_main(monkeypatch, db, api, argv):
    """CLI specialist_sync.main с подставленным transport, без сети и пауз."""
    import specialist_sync

    original = specialist_sync.RegistryClient

    def factory(*_args, **_kwargs):
        return original(api, min_interval=0, sleep=lambda _s: None, retries=1)

    monkeypatch.setattr(specialist_sync, "RegistryClient", factory)
    return specialist_sync.main(
        ["--db", str(db), "--sro", "OGPS", "--fresh", *argv]
    )


def test_allow_prune_flag_removes_members_below_half(tmp_path, monkeypatch):
    """--allow-prune снимает порог <50%. Без флага тот же список по-прежнему блокируется."""
    import specialist_sync

    alerts: list[str] = []
    monkeypatch.setattr(specialist_sync, "notify_admins", alerts.append, raising=False)
    db = tmp_path / "spec.sqlite"
    assert sync_all(
        db_path=db,
        codes=["OGPS"],
        fresh=True,
        client=_client(_ListApi([1, 2, 3, 4])),
    ) == 0
    assert _member_ids(db) == [1, 2, 3, 4]

    alerts.clear()
    assert _run_main(monkeypatch, db, _ListApi([1]), []) == 1
    assert _member_ids(db) == [1, 2, 3, 4]
    assert alerts
    assert "OGPS" in alerts[0]

    alerts.clear()
    assert _run_main(
        monkeypatch,
        db,
        _ListApi([1]),
        ["--allow-prune", "OGPP", "--allow-prune", "ogps"],
    ) == 0
    assert _member_ids(db) == [1]
    assert alerts == []
    assert search_people("сидоров", db=db).status == "ok"
    assert search_people("иванова", db=db).status != "ok"


def test_allow_prune_env_removes_members_below_half(tmp_path, monkeypatch):
    import specialist_sync

    alerts: list[str] = []
    monkeypatch.setattr(specialist_sync, "notify_admins", alerts.append, raising=False)
    monkeypatch.setenv("SPECIALIST_ALLOW_PRUNE", "OGPP, ogps")
    db = tmp_path / "spec.sqlite"
    assert sync_all(
        db_path=db,
        codes=["OGPS"],
        fresh=True,
        client=_client(_ListApi([1, 2, 3, 4])),
    ) == 0
    assert _run_main(monkeypatch, db, _ListApi([1]), []) == 0
    assert _member_ids(db) == [1]
    assert alerts == []


def test_allow_prune_does_not_wipe_empty_list_without_count(tmp_path, monkeypatch):
    """Пустой список без count или с явной ошибкой не стирает базу даже с --allow-prune."""
    import specialist_sync

    alerts: list[str] = []
    monkeypatch.setattr(specialist_sync, "notify_admins", alerts.append, raising=False)
    db = tmp_path / "spec.sqlite"
    assert sync_all(
        db_path=db,
        codes=["OGPS"],
        fresh=True,
        client=_client(_ListApi([1, 2, 3, 4])),
    ) == 0

    alerts.clear()
    assert _run_main(
        monkeypatch, db, _ListApi([], omit_count=True), ["--allow-prune", "OGPS"]
    ) == 1
    assert _member_ids(db) == [1, 2, 3, 4]
    assert alerts

    alerts.clear()

    def error_list(url, body, timeout):
        if url.endswith("/member/list"):
            return 200, {
                "success": True,
                "error": "registry down",
                "data": {"count": 0, "countPages": 1, "data": []},
            }
        raise AssertionError(url)

    assert _run_main(
        monkeypatch, db, error_list, ["--allow-prune", "OGPS"]
    ) == 1
    assert _member_ids(db) == [1, 2, 3, 4]
    assert alerts


def test_allow_prune_trustworthy_empty_list_removes_members(tmp_path, monkeypatch):
    """Явный count 0 и --allow-prune снимают членов. Без count выше — нет."""
    import specialist_sync

    alerts: list[str] = []
    monkeypatch.setattr(specialist_sync, "notify_admins", alerts.append, raising=False)
    db = tmp_path / "spec.sqlite"
    assert sync_all(
        db_path=db,
        codes=["OGPS"],
        fresh=True,
        client=_client(_ListApi([1, 2])),
    ) == 0
    assert _run_main(
        monkeypatch, db, _ListApi([], count=0), ["--allow-prune", "OGPS"]
    ) == 0
    assert _member_ids(db) == []
    assert alerts == []


def _empty_db_warnings(caplog):
    return [
        record
        for record in caplog.records
        if record.levelno == logging.WARNING and "OGPS" in record.getMessage() and "пуст" in record.getMessage()
    ]


def test_empty_list_on_empty_database_is_not_an_alert(tmp_path, monkeypatch, caplog):
    """Пустой список при пустой базе — не авария и код 0, но warning в логе."""
    import specialist_sync

    alerts: list[str] = []
    monkeypatch.setattr(specialist_sync, "notify_admins", alerts.append, raising=False)
    db = tmp_path / "spec.sqlite"
    with caplog.at_level(logging.WARNING, logger="specialist_sync"):
        assert sync_all(
            db_path=db,
            codes=["OGPS"],
            fresh=True,
            client=_client(_ListApi([], count=0)),
        ) == 0
    assert alerts == []
    assert _member_ids(db) == []
    assert _empty_db_warnings(caplog)

    alerts.clear()
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="specialist_sync"):
        assert sync_all(
            db_path=db,
            codes=["OGPS"],
            fresh=True,
            client=_client(_ListApi([], omit_count=True)),
        ) == 0
    assert alerts == []
    assert _empty_db_warnings(caplog)


def _fixture(name: str) -> dict:
    path = Path(__file__).resolve().parent / "fixtures" / name
    return json.loads(path.read_text(encoding="utf-8"))


def test_nostroy_live_expert_shape_and_empty_buckets():
    """Форма карточки НОСТРОЙ на 22.10.2026: id и is_highlighted, номер в number.

    Пустые корзины при заполненной дате — тот же объект, без строк.
    Отдельного поля под специалистов в таком ответе нет.
    """
    filled = _fixture("nostroy_member_experts.json")
    rows = extract_specialists(filled)
    assert rows == [
        {
            "fio": "Сидоров Пётр Сергеевич",
            "fio_norm": "сидоров петр сергеевич",
            "nrs_number": "С-77-100001",
            "category": "Специалист · Особо-опасные работы",
        }
    ]

    empty = _fixture("nostroy_member_experts_empty.json")
    assert empty["experts_by_category"] == {"regular": [], "danger": [], "other": []}
    assert empty["last_updated_experts_at_date_time_string"]
    assert extract_specialists(empty) == []
    assert experts_published_empty(empty) is True
    assert experts_published_empty(filled) is False
    assert experts_published_empty({"inn": "1", "short_description": "ООО"}) is False
    assert experts_published_empty({"experts_by_category": {}}) is False
    assert experts_published_empty({"experts_by_category": {"regular": None}}) is False
    assert experts_published_empty(
        {"experts_by_category": {"regular": [{"id": 1}]}}
    ) is False
    assert experts_published_empty(
        {"specialists_data": {"regular": [], "danger": []}}
    ) is True


def test_empty_published_experts_keep_rows_and_exit_zero(tmp_path, monkeypatch, caplog, capsys):
    """Дата специалистов есть, корзины пустые: старые ФИО остаются, код 0, без алерта.

    Отпечаток списка при этом не двигается: тот же штамп на следующем прогоне
    снова читает карточку, если реестр вернул строки.
    """
    import specialist_sync

    alerts: list[str] = []
    monkeypatch.setattr(specialist_sync, "notify_admins", alerts.append, raising=False)
    db = tmp_path / "spec.sqlite"
    assert sync_all(
        db_path=db, codes=["OGPS"], fresh=True, client=_client(_ListApi([1, 2]))
    ) == 0
    assert search_people("сидоров", db=db).status == "ok"

    empty = _fixture("nostroy_member_experts_empty.json")

    class _EmptyExperts(_ListApi):
        def __call__(self, url, body, timeout):
            self.calls.append((url, body))
            if url.endswith("/member/list"):
                rows = [
                    _nostroy_row(member_id, stamp="16.10.2026 00:00:00")
                    for member_id in self.member_ids
                ]
                return 200, {
                    "success": True,
                    "data": {"count": len(rows), "countPages": 1, "data": rows},
                }
            if url.endswith("/member/1/info"):
                card = dict(empty)
                card["id"] = 1
                return 200, {"success": True, "data": card}
            return _ListApi.__call__(self, url, body, timeout)

    alerts.clear()
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="specialist_sync"):
        rc = sync_all(
            db_path=db,
            codes=["OGPS"],
            fresh=True,
            client=_client(_EmptyExperts([1, 2])),
        )
    assert rc == 0
    assert alerts == []
    assert search_people("сидоров", db=db).status == "ok"
    assert search_people("иванова", db=db).status == "ok"
    warnings = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING and "не стираю" in record.getMessage()
    ]
    assert warnings == []
    assert "Админам не шлю" in capsys.readouterr().out

    filled = _fixture("nostroy_member_experts.json")
    filled["experts_by_category"]["regular"][0]["fio"] = "Орлова Анна Сергеевна"
    filled["experts_by_category"]["danger"] = []

    class _Restored(_EmptyExperts):
        def __call__(self, url, body, timeout):
            self.calls.append((url, body))
            if url.endswith("/member/1/info"):
                card = dict(filled)
                card["id"] = 1
                card["experts_by_category"] = filled["experts_by_category"]
                return 200, {"success": True, "data": card}
            return _EmptyExperts.__call__(self, url, body, timeout)

    # Штамп списка тот же, но пустые корзины его не подтвердили — карточку читаем
    # снова и записываем вернувшиеся строки.
    assert sync_all(
        db_path=db,
        codes=["OGPS"],
        fresh=True,
        client=_client(_Restored([1, 2])),
    ) == 0
    assert search_people("сидоров", db=db).status == "none"
    restored = search_people("орлова", db=db)
    assert restored.status == "ok"
    assert "С-77-100001" in format_search_reply("орлова", db=db)


def test_specialist_delta_counts_added_removed_and_pruned(tmp_path, capsys):
    """Конец лога: по СРО и всего, сколько специалистов прибавилось и ушло."""
    db = tmp_path / "spec.sqlite"
    assert sync_all(
        db_path=db, codes=["OGPS"], fresh=True, client=_client(_ListApi([1, 2]))
    ) == 0
    first = capsys.readouterr().out
    assert "OGPS: добавлено 2, убрано 0" in first
    assert "Всего: добавлено 2, убрано 0" in first

    class _ReplaceAndDrop(_ListApi):
        def __call__(self, url, body, timeout):
            self.calls.append((url, body))
            if url.endswith("/member/list"):
                rows = [_nostroy_row(1, stamp="03.03.2026 00:00:00")]
                return 200, {
                    "success": True,
                    "data": {"count": 1, "countPages": 1, "data": rows},
                }
            if url.endswith("/member/1/info"):
                return 200, {
                    "success": True,
                    "data": _nostroy_card(1, "Новикова Ольга Сергеевна"),
                }
            raise AssertionError(url)

    assert sync_all(
        db_path=db, codes=["OGPS"], fresh=True, client=_client(_ReplaceAndDrop([1]))
    ) == 0
    second = capsys.readouterr().out
    assert "OGPS: добавлено 1, убрано 2" in second
    assert "Всего: добавлено 1, убрано 2" in second
    assert search_people("новикова", db=db).status == "ok"
    assert search_people("сидоров", db=db).status == "none"
    assert search_people("иванова", db=db).status == "none"


def test_stamp_without_rows_mark_is_read_again(tmp_path):
    """Старая база без |rows= не пропускает карточку: пустой прогон мог затереть штамп."""
    db = tmp_path / "spec.sqlite"
    assert sync_all(
        db_path=db, codes=["OGPS"], fresh=True, client=_client(_ListApi([1]))
    ) == 0
    conn = connect(db, write=True)
    try:
        stored = conn.execute("SELECT card_stamp FROM members WHERE member_id=1").fetchone()
        assert "|rows=" in (stored["card_stamp"] or "")
        conn.execute(
            "UPDATE members SET card_stamp=? WHERE member_id=1",
            (stored["card_stamp"].split("|rows=")[0],),
        )
        conn.commit()
    finally:
        conn.close()

    class _NewFio(_ListApi):
        def __call__(self, url, body, timeout):
            if "/member/" in url and url.endswith("/info"):
                self.calls.append((url, body))
                return 200, {
                    "success": True,
                    "data": _nostroy_card(1, "Новикова Ольга Сергеевна"),
                }
            return _ListApi.__call__(self, url, body, timeout)

    api = _NewFio([1])
    assert sync_all(db_path=db, codes=["OGPS"], fresh=True, client=_client(api)) == 0
    assert _info_calls(api, "/member/1/info") == 1
    assert search_people("новикова", db=db).status == "ok"
    assert search_people("сидоров", db=db).status == "none"


def test_timeout_is_retried():
    state = {"n": 0}

    def transport(url, body, timeout):
        state["n"] += 1
        if state["n"] == 1:
            raise requests.Timeout("timeout")
        return 200, {"success": True, "data": {"ok": 1}}

    client = RegistryClient(transport, min_interval=0, sleep=lambda _s: None, retries=3)
    assert client.post("https://reestr.nostroy.ru/api/member/1/info", {})["success"] is True
    assert state["n"] == 2
