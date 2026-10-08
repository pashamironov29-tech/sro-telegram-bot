"""Убирает токены из логов, stdout и stderr.

Файл лога пишется обработчиком logging, journald забирает stdout/stderr
процесса. Оба пути проходят через redact_secrets.
"""

from __future__ import annotations

import logging
import re
import sys

_BOT_TOKEN_IN_PATH = re.compile(r"/bot\d+:[A-Za-z0-9_-]+")
_BOT_TOKEN_BARE = re.compile(r"\bbot\d+:[A-Za-z0-9_-]{20,}")
# Имя заголовка может быть в кавычках: repr словаря {'Authorization': '...'}.
_AUTH_HEADER = re.compile(
    r"(?i)((?:[\"']authorization[\"']|authorization)\s*[:=]\s*[\"']?)([^\s,;\"']+)"
)
_QUERY_TOKEN = re.compile(r"([?&]token=)[^&\s]+")

_STDIO_WRAPPED = False
_FORMATTER_PATCHED = False
_INSTALLED = False


def redact_secrets(text: str) -> str:
    """Токен Telegram в URL и значение заголовка Authorization."""
    if not text:
        return text
    text = _BOT_TOKEN_IN_PATH.sub("/bot***REDACTED***", text)
    text = _BOT_TOKEN_BARE.sub("bot***REDACTED***", text)
    text = _AUTH_HEADER.sub(r"\1***REDACTED***", text)
    text = _QUERY_TOKEN.sub(r"\1***REDACTED***", text)
    return text


class _RedactingStream:
    def __init__(self, stream):
        self._stream = stream

    def write(self, data):
        if isinstance(data, str):
            data = redact_secrets(data)
        return self._stream.write(data)

    def flush(self):
        return self._stream.flush()

    def fileno(self):
        return self._stream.fileno()

    def isatty(self):
        return self._stream.isatty()

    def __getattr__(self, name):
        return getattr(self._stream, name)


class SecretRedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        record.msg = redact_secrets(message)
        record.args = ()
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact_secrets(record.exc_text)
        if record.stack_info:
            record.stack_info = redact_secrets(record.stack_info)
        return True


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_secrets(super().format(record))


def _patch_all_formatters() -> None:
    """Чужой handler (добавленный библиотекой позже) тоже не пишет токен."""
    global _FORMATTER_PATCHED
    if _FORMATTER_PATCHED:
        return
    original = logging.Formatter.format

    def format_redacted(self, record):
        rendered = original(self, record)
        if isinstance(rendered, str):
            return redact_secrets(rendered)
        return rendered

    logging.Formatter.format = format_redacted
    _FORMATTER_PATCHED = True


def _wrap_stdio() -> None:
    global _STDIO_WRAPPED
    if _STDIO_WRAPPED:
        return
    sys.stdout = _RedactingStream(sys.stdout)
    sys.stderr = _RedactingStream(sys.stderr)
    _STDIO_WRAPPED = True


def install_secret_log_redaction(
    log_path: str | None = None,
    *,
    level: int = logging.ERROR,
    fmt: str = "%(asctime)s %(levelname)s %(message)s",
) -> None:
    """Файл (если задан путь) или stderr. stdout/stderr процесса тоже режутся."""
    global _INSTALLED
    _wrap_stdio()
    _patch_all_formatters()
    if _INSTALLED:
        return
    root = logging.getLogger()
    root.setLevel(level)
    if log_path:
        handler: logging.Handler = logging.FileHandler(log_path, encoding="utf-8")
    else:
        handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(RedactingFormatter(fmt))
    handler.addFilter(SecretRedactFilter())
    root.handlers.clear()
    root.addHandler(handler)
    _INSTALLED = True
