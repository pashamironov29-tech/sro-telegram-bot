"""Общая обвязка pytest.

До импорта модулей бота: заглушка config_keys (без настоящих ключей),
BOT_PLATFORM=max (bot_MAX.py всё равно ставит его при импорте) и запрет сети.
Telegram-оболочка проверяется отдельным подпроцессом с BOT_PLATFORM=tg,
см. tests/test_inn_search_telegram.py.
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests import support  # noqa: E402

os.environ["BOT_PLATFORM"] = "max"
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

_SESSION_DIR = tempfile.mkdtemp(prefix="sro-tests-")
atexit.register(shutil.rmtree, _SESSION_DIR, ignore_errors=True)
SRO_FILES_DIR = os.path.join(_SESSION_DIR, "sro files")
os.makedirs(SRO_FILES_DIR, exist_ok=True)

CONFIG_STUB = support.install_config_stub(SRO_FILES_DIR)
support.block_network()

import pytest  # noqa: E402

import controller_access  # noqa: E402
import feedback_log  # noqa: E402
import local_answers  # noqa: E402
import nrs_search_links  # noqa: E402
import reestr_sync  # noqa: E402
import sro_context  # noqa: E402
import users_log  # noqa: E402

_STATE_CONTAINERS = (
    local_answers.faq_mode_users,
    local_answers.search_mode_users,
    controller_access._controller_work_mode,
    nrs_search_links._await_nrs_query,
    sro_context._user_context,
    sro_context._pending_sro_pick,
    sro_context._pickable_sro_cache,
    sro_context._await_inn,
    sro_context._open_main_after_sro,
    sro_context._await_joiner_activity,
    sro_context._joiner_activity_by_chat,
    feedback_log._last_ai,
    feedback_log._await_expected,
)


def _reset_state() -> None:
    for container in _STATE_CONTAINERS:
        container.clear()


@pytest.fixture(autouse=True)
def isolated_files(tmp_path, monkeypatch):
    """Ничего не пишем в рабочий каталог: журналы, контексты и кэш — во временную папку."""
    monkeypatch.setattr(users_log, "USERS_FILE", tmp_path / "bot_users.json")
    monkeypatch.setattr(sro_context, "_CONTEXT_FILE", tmp_path / "user_sro_context_max.json")
    monkeypatch.setattr(nrs_search_links, "_MODE_FILE", str(tmp_path / "nrs_link_mode_max.json"))
    monkeypatch.setattr(feedback_log, "FEEDBACK_FILE", tmp_path / "feedback_questions.jsonl")
    monkeypatch.setattr(reestr_sync, "CACHE_FILE", str(tmp_path / "reestr_cache.json"))
    monkeypatch.setattr(reestr_sync, "DETAIL_DELAY", 0)
    _reset_state()
    yield tmp_path
    _reset_state()


@pytest.fixture
def config_stub():
    return CONFIG_STUB


@pytest.fixture
def sample_reestr():
    return support.sample_reestr()


@pytest.fixture(scope="session")
def max_module():
    """bot_MAX без установки логгера: иначе при импорте появится bot_max_errors.log в cwd
    и обёртка поверх sys.stdout pytest. Сам log_redact проверяется в test_log_redact.py."""
    import log_redact

    original = log_redact.install_secret_log_redaction
    log_redact.install_secret_log_redaction = lambda *a, **k: None
    try:
        import bot_MAX
    finally:
        log_redact.install_secret_log_redaction = original
    return bot_MAX


class FakeMaxApi:
    """Вместо MaxApi: запоминает вызовы, в сеть не ходит."""

    def __init__(self):
        self.sent: list[dict] = []
        self.edits: list[dict] = []
        self.callbacks: list[dict] = []

    def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return {"message": {"body": {"mid": f"mid-{len(self.sent)}"}}}

    def edit_message(self, message_id, *, text=None, attachments=None, format="html"):
        self.edits.append({"message_id": message_id, "text": text, "attachments": attachments})
        return {}

    def answer_callback(self, callback_id, *, notification=None, message=None):
        self.callbacks.append({"callback_id": callback_id, "notification": notification})
        return {}


class MaxHarness:
    def __init__(self, module, api):
        self.m = module
        self.api = api
        self.sent: list[tuple[str, list | None]] = []

    def capture(self, user_id, text, attachments=None):
        self.sent.append((text or "", attachments))

    def texts(self) -> list[str]:
        out = [t for t, _ in self.sent]
        out += [s.get("text") or "" for s in self.api.sent]
        out += [e.get("text") or "" for e in self.api.edits]
        return out

    def blob(self) -> str:
        return "\n".join(self.texts())

    def attachments(self) -> list:
        atts = [a for _, a in self.sent if a]
        atts += [e["attachments"] for e in self.api.edits if e.get("attachments")]
        return atts

    def callback_payloads(self) -> list[str]:
        return [p for kind, _t, p in self.buttons() if kind == "callback"]

    def buttons(self) -> list[tuple[str, str, str]]:
        out = []
        for atts in self.attachments():
            out.extend(support.keyboard_buttons(atts))
        return out

    def clear(self) -> None:
        self.sent.clear()
        self.api.sent.clear()
        self.api.edits.clear()


@pytest.fixture
def max_bot(max_module, monkeypatch, sample_reestr):
    api = FakeMaxApi()
    harness = MaxHarness(max_module, api)
    monkeypatch.setattr(max_module, "api", api)
    monkeypatch.setattr(max_module, "send", harness.capture)
    monkeypatch.setattr(max_module, "reestr_database", sample_reestr)
    monkeypatch.setattr(max_module, "sro_database", {})
    return harness


@pytest.fixture
def max_controller(config_stub, monkeypatch):
    """Включить тестового пользователя в контролёры MAX подменой конфига в памяти."""
    monkeypatch.setattr(config_stub, "MAX_CONTROLLER_IDS", [support.TEST_UID])
    return support.TEST_UID
