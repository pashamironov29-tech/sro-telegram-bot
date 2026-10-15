"""Синк и поиск специалистов: HTTP только через подставленный transport."""

from __future__ import annotations

import pytest
import requests

from sro_profiles import SRO_ACTIVITY
from specialist_reestr import (
    PARTNER_REGISTRY,
    SroTarget,
    connect,
    director_fio_norm,
    ensure_schema,
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
    assert any("Поиск специалиста по ФИО" in label for label in labels)

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
