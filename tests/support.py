"""Общие заглушки для тестов: конфиг без настоящих ключей и запрет сети.

Импортируется из conftest.py и из подпроцесса tests/tg_search_probe.py.
"""

from __future__ import annotations

import socket
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Строки нарочно не похожи на настоящие: так их легко найти в выводе.
FAKE_TG_TOKEN = "000000000:TEST_FAKE_TOKEN_not_a_real_one_xx"
FAKE_MAX_TOKEN = "test-fake-max-token-not-real"


def ensure_root_on_path() -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))


def install_config_stub(sro_files_dir: str) -> types.ModuleType:
    """Подложить config_keys в sys.modules раньше настоящего файла."""
    stub = types.ModuleType("config_keys")
    stub.__file__ = "<tests config_keys stub>"
    stub.BOT_TOKEN = FAKE_TG_TOKEN
    stub.MAX_BOT_TOKEN = FAKE_MAX_TOKEN
    stub.SRO_FILES_DIR = sro_files_dir
    stub.BOT_ADMIN_IDS = []
    stub.CONTROLLER_CHAT_IDS = []
    stub.MAX_CONTROLLER_IDS = []
    stub.CHECKO_API_KEY = ""
    sys.modules["config_keys"] = stub
    return stub


class NetworkBlocked(RuntimeError):
    pass


def _refuse(*_args, **_kwargs):
    raise NetworkBlocked("тесты не ходят в сеть")


def block_network() -> None:
    """Любая попытка открыть сокет наружу — исключение, а не тихий запрос."""
    socket.socket.connect = _refuse  # type: ignore[method-assign]
    socket.socket.connect_ex = _refuse  # type: ignore[method-assign]
    socket.create_connection = _refuse  # type: ignore[assignment]
    socket.getaddrinfo = _refuse  # type: ignore[assignment]


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeResponse:
    """Минимум того, что reestr_sync._fetch берёт у requests.Response."""

    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}")


def keyboard_buttons(atts) -> list[tuple[str, str, str]]:
    """(kind, text, payload_or_url) из inline-клавиатуры MAX."""
    out: list[tuple[str, str, str]] = []
    for att in atts or []:
        if not isinstance(att, dict) or att.get("type") != "inline_keyboard":
            continue
        for row in (att.get("payload") or {}).get("buttons") or []:
            for btn in row or []:
                kind = btn.get("type") or ""
                if kind == "callback":
                    out.append(("callback", btn.get("text") or "", btn.get("payload") or ""))
                elif kind == "link":
                    out.append(("link", btn.get("text") or "", btn.get("url") or ""))
    return out


# Выдуманный user_id / chat_id тестового пользователя.
TEST_UID = 900000001

INN_SINGLE = "7700000001"
INN_MULTI = "7700000002"
INN_EXCLUDED = "7700000003"
INN_IP = "770000000004"
INN_ABSENT = "7799999999"


def membership(
    sro_id: str,
    sro_name: str,
    *,
    title: str,
    status: str = "Член СРО",
    with_details: bool = True,
    uuid: str = "00000000-0000-0000-0000-000000000001",
) -> dict:
    row = {
        "inn": None,
        "sro_id": sro_id,
        "sro_name": sro_name,
        "short_name": title,
        "title": title,
        "status": status,
        "reg_date": "01.02.2015",
        "uuid": uuid,
        "url": f"https://sro.example.test/reestr/{uuid}/",
    }
    if with_details:
        row.update(
            {
                "reg_number": f"{sro_id}-001",
                "director": "Тестов Тест Тестович",
                "location": "г. Тестоград, ул. Примерная, д. 1",
                "kf_level_vv": 1,
                "kf_level_odo": None,
                "kf_sum_vv": "100000",
                "inspections": [{"year": "2025", "result": "Нарушений не выявлено"}],
                "inspections_by_year": {"2025": "Нарушений не выявлено"},
            }
        )
    return row


def sample_reestr() -> dict[str, dict]:
    """Маленький реестр: одна СРО, две СРО, исключённый, ИП с 12-значным ИНН."""
    orgs: dict[str, dict] = {}

    def add(inn: str, title: str, *mems: dict) -> None:
        memberships = {}
        for mem in mems:
            mem["inn"] = inn
            memberships[mem["sro_id"]] = mem
        orgs[inn] = {"inn": inn, "title": title, "memberships": memberships}

    add(
        INN_SINGLE,
        "ООО «Тестстрой»",
        membership("OGPS", "ОГПС", title="ООО «Тестстрой»"),
    )
    add(
        INN_MULTI,
        "ООО «Двойной Тест»",
        membership(
            "OGPS",
            "ОГПС",
            title="ООО «Двойной Тест»",
            uuid="00000000-0000-0000-0000-000000000002",
        ),
        membership(
            "MOTS",
            "МОТС",
            title="ООО «Двойной Тест»",
            uuid="00000000-0000-0000-0000-000000000003",
        ),
    )
    add(
        INN_EXCLUDED,
        "ООО «Бывший Тест»",
        membership(
            "OGPS",
            "ОГПС",
            title="ООО «Бывший Тест»",
            status="Исключен",
            uuid="00000000-0000-0000-0000-000000000004",
        ),
    )
    add(
        INN_IP,
        "ИП Пробный П.П.",
        membership(
            "OSO",
            "ОСО",
            title="ИП Пробный П.П.",
            uuid="00000000-0000-0000-0000-000000000005",
        ),
    )
    return orgs
