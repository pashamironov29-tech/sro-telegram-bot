"""log_redact: токены не попадают ни в файл лога, ни в stdout/stderr."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import textwrap

import pytest

import log_redact
from tests.support import FAKE_MAX_TOKEN, FAKE_TG_TOKEN, ROOT

TG_URL = f"https://api.telegram.org/bot{FAKE_TG_TOKEN}/sendMessage"
TG_SECRET = FAKE_TG_TOKEN.split(":", 1)[1]


@pytest.fixture
def redaction(tmp_path):
    """Поставить вырезание в лог-файл и после теста вернуть всё как было."""
    root = logging.getLogger()
    saved = {
        "handlers": list(root.handlers),
        "level": root.level,
        "stdout": sys.stdout,
        "stderr": sys.stderr,
        "format": logging.Formatter.format,
        "flags": (
            log_redact._INSTALLED,
            log_redact._STDIO_WRAPPED,
            log_redact._FORMATTER_PATCHED,
        ),
    }
    log_redact._INSTALLED = False
    log_redact._STDIO_WRAPPED = False
    log_redact._FORMATTER_PATCHED = False
    log_path = tmp_path / "bot_errors.log"
    log_redact.install_secret_log_redaction(str(log_path))
    try:
        yield log_path
    finally:
        for handler in root.handlers:
            if handler not in saved["handlers"]:
                handler.close()
        root.handlers[:] = saved["handlers"]
        root.setLevel(saved["level"])
        sys.stdout = saved["stdout"]
        sys.stderr = saved["stderr"]
        logging.Formatter.format = saved["format"]
        (
            log_redact._INSTALLED,
            log_redact._STDIO_WRAPPED,
            log_redact._FORMATTER_PATCHED,
        ) = saved["flags"]


def _log_text(path) -> str:
    for handler in logging.getLogger().handlers:
        handler.flush()
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("raw", "secret"),
    [
        pytest.param(f"POST {TG_URL} failed", TG_SECRET, id="tg-url"),
        pytest.param(f"token bot{FAKE_TG_TOKEN} leaked", TG_SECRET, id="tg-bare"),
        pytest.param(f"Authorization: {FAKE_MAX_TOKEN}", FAKE_MAX_TOKEN, id="auth-colon"),
        pytest.param(f"authorization={FAKE_MAX_TOKEN}", FAKE_MAX_TOKEN, id="auth-equals"),
        pytest.param(
            f"GET https://cdn.example.test/file?id=1&token={FAKE_MAX_TOKEN}&x=2",
            FAKE_MAX_TOKEN,
            id="query-token",
        ),
    ],
)
def test_redact_secrets_strings(raw, secret):
    cleaned = log_redact.redact_secrets(raw)
    assert secret not in cleaned
    assert "REDACTED" in cleaned


def test_redact_keeps_ordinary_text():
    text = "ИНН 7700000001 не найден, https://www.srogen.ru/reestr/"
    assert log_redact.redact_secrets(text) == text


def test_traceback_with_token_url_not_in_log_file(redaction):
    try:
        raise ConnectionError(f"Max retries exceeded with url: /bot{FAKE_TG_TOKEN}/sendMessage")
    except ConnectionError:
        logging.error("Polling упал, перезапуск через 5 сек...", exc_info=True)

    text = _log_text(redaction)
    assert TG_SECRET not in text
    assert "REDACTED" in text
    assert "Traceback" in text
    assert "Polling упал" in text


def test_log_args_are_redacted(redaction):
    logging.error("hdr Authorization: %s url %s", FAKE_MAX_TOKEN, TG_URL)

    text = _log_text(redaction)
    assert FAKE_MAX_TOKEN not in text
    assert TG_SECRET not in text


def test_query_token_in_log_file(redaction):
    logging.error("download https://cdn.example.test/f?token=%s", FAKE_MAX_TOKEN)
    assert FAKE_MAX_TOKEN not in _log_text(redaction)


def test_handler_added_later_is_redacted(redaction, tmp_path):
    late_path = tmp_path / "late.log"
    late = logging.FileHandler(late_path, encoding="utf-8")
    late.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger().addHandler(late)
    try:
        logging.getLogger("third.party").error("call %s", TG_URL)
    finally:
        late.flush()
    assert TG_SECRET not in late_path.read_text(encoding="utf-8")


_STDIO_SCRIPT = textwrap.dedent(
    """
    import logging, sys
    sys.path.insert(0, {root!r})
    import log_redact
    log_redact.install_secret_log_redaction({log_path!r})
    print("⚠️ Сбой связи с Telegram: " + {url!r}, flush=True)
    print("Authorization: " + {max_token!r}, file=sys.stderr, flush=True)
    try:
        raise ConnectionError("url: " + {url!r})
    except ConnectionError:
        logging.error("Polling упал", exc_info=True)
    raise RuntimeError("необработанное: " + {url!r})
    """
)


def test_process_stdout_stderr_redacted(tmp_path):
    """journald видит stdout/stderr процесса — проверяем их, а не перехват pytest."""
    log_path = tmp_path / "bot_errors.log"
    script = _STDIO_SCRIPT.format(
        root=str(ROOT), log_path=str(log_path), url=TG_URL, max_token=FAKE_MAX_TOKEN
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=dict(os.environ, PYTHONIOENCODING="utf-8"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )

    assert proc.returncode == 1
    assert "Сбой связи с Telegram" in proc.stdout
    assert "REDACTED" in proc.stdout
    assert TG_SECRET not in proc.stdout
    assert FAKE_MAX_TOKEN not in proc.stderr
    assert "RuntimeError" in proc.stderr
    assert TG_SECRET not in proc.stderr
    log_text = log_path.read_text(encoding="utf-8")
    assert "Polling упал" in log_text
    assert TG_SECRET not in log_text


def test_below_error_level_not_written(redaction):
    logging.warning("предупреждение %s", TG_URL)
    assert _log_text(redaction) == ""


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Известный пробел log_redact: заголовок в виде repr словаря "
        "{'Authorization': '...'} не вырезается — после имени заголовка идёт кавычка, "
        "а не ':' или '='. Код бота в этой задаче не меняем."
    ),
)
def test_authorization_in_dict_repr():
    raw = str({"Authorization": FAKE_MAX_TOKEN})
    assert FAKE_MAX_TOKEN not in log_redact.redact_secrets(raw)
