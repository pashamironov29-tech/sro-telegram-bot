# -*- coding: utf-8 -*-
"""Скачать действующих членов 15 СРО и специалистов из их карточек.

Реестры: POST https://reestr.nostroy.ru/api/ и https://reestr.nopriz.ru/api/
Тело JSON, Content-Type: application/json. GET эти адреса не принимают.

Список:  sro/{id}/member/list
          {"filters": {"member_status": 1}, "page": N, "pageCount": "20",
           "sortBy": {"inn": "ASC"}}
Карточка: member/{id}/info

Сколько страниц просить, решаем по полю count (сколько членов), а не только
по countPages: если страницы оборвались раньше, список считаем битым и
старых членов не удаляем. Пустой список и список меньше половины уже
записанных членов тоже не удаляет строки: в лог и админам уходит
предупреждение. Для выбранных СРО порог снимает ``--allow-prune CODE``
(можно несколько раз) или ``SPECIALIST_ALLOW_PRUNE=CODE1,CODE2``.
Пустой список при этом всё равно не стирает базу, если в ответе явная
ошибка или нет count. Пустой список, когда членов этой СРО в базе нет,
ошибкой не считается: админам не шлём и код 0, но в лог пишется warning.
``SPECIALIST_ALLOW_PRUNE`` в unit-файл насовсем не класть — для разового
удаления запускай ``--allow-prune CODE``. Сортировка по id реестр молча
игнорирует, страницы тогда повторяются и часть членов пропадает.
Сортировка по ИНН применяется
и даёт полный список без повторов.

НОСТРОЙ в списке отдаёт даты обновления — карточку с тем же отпечатком
повторно не качаем. Исключение: дата специалистов в списке есть, а в базе
у члена ни одной строки — карточку читаем снова.

С 16.10.2026 часть карточек НОСТРОЙ приходит с датой специалистов и пустыми
списками experts_by_category (regular/danger/other). Отдельного публичного
адреса нет: страница члена показывает «Нет данных о специалистах»,
те же корзины и те же поля fio/number, что у карточек со строками.
Такие пустые корзины не считаются сбоем, админам не пишем и в порог
не кладём. Уже записанных специалистов не стираем и отпечаток списка
не двигаем: следующий прогон прочитает карточку снова. Пока в базе
строк нет, карточку с датой тоже читаем снова.

Порог админам — только если блок специалистов не разобран: поля нет
или оно не пустые корзины, а строк мы не получили. Код выхода из‑за
этого остаётся 0. По одной СРО: SPECIALIST_EMPTY_RATIO (0.20) и
SPECIALIST_EMPTY_MIN (10) — таких карточек не меньше минимума и доля
строго больше порога. По всему прогону отдельно:
SPECIALIST_EMPTY_TOTAL_RATIO и SPECIALIST_EMPTY_TOTAL_MIN, те же числа
по умолчанию. Доля 0 или минимум 0 выключают свою проверку.

В конце прогона в лог и в текст админам пишется, сколько специалистов
добавлено и убрано относительно прошлого состояния, по каждой СРО и всего.

Перед записью делается согласованная копия specialists.sqlite
(метод backup у sqlite3) в каталог specialists_backups рядом с файлом.
SPECIALIST_BACKUP_KEEP — сколько копий оставить (7). SPECIALIST_BACKUP_DIR
— другой каталог. Копия не удалась: синк не начинается, админам
сообщение, код 1.

429, 403 или обрыв сети подряд SPECIALIST_BLOCK_STREAK раз (5) — реестр
больше не спрашиваем. Между попытками ждём Retry-After, но не дольше
120 секунд, иначе пауза 1, 2, 4… секунд. Админам сообщение, код 1.
Следующий запуск продолжает тот же проход.

У НОПРИЗ в списке даты
специалистов нет (specialists_update_date только в карточке), поэтому
карточки НОПРИЗ читаем заново каждый полный запуск. Оборванный запуск
продолжается сам: уже записанные в этом запуске члены пропускаются.

Запуск из каталога бота:
    python specialist_sync.py
    python specialist_sync.py --sro OGPS
    python specialist_sync.py --fresh
    python specialist_sync.py --allow-prune OGPS

База: specialists.sqlite рядом со скриптом (или SPECIALISTS_DB / --db).
На сервер это не выкладывает и ботов не останавливает.
"""

from __future__ import annotations

import argparse
import html
import logging
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

from log_redact import redact_secrets
from specialist_reestr import (
    CARD_ROWS_MARK,
    SroTarget,
    allow_prune_codes,
    card_has_substance,
    connect,
    db_path as specialists_db_path,
    ensure_schema,
    experts_published_empty,
    init_db,
    list_stamp,
    list_would_wipe_too_much,
    partner_targets,
    prune_members,
    save_member,
    stored_member,
    stored_specialist_count,
    touch_skipped_member,
)

PAGE_COUNT = "20"
# sortBy.id реестр не применяет: страницы пересекаются и теряют членов.
# sortBy.inn применяется, список сходится с полем count.
SORT_BY = {"inn": "ASC"}
MIN_INTERVAL_SEC = 0.4  # не быстрее ~2.5 запросов в секунду
REQUEST_TIMEOUT = 45
RETRY_TIMES = 4
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
# Мало карточек с ошибкой — не будим из‑за пары таймаутов.
# Доля как у ночного синка реестра: больше 20% и не меньше 10 попыток.
CARD_ERROR_RATIO = 0.20
CARD_ERROR_MIN_ATTEMPTS = 10
# Пустые корзины при дате специалистов: алерт, код выхода не меняют.
DEFAULT_EMPTY_RATIO = 0.20
DEFAULT_EMPTY_MIN = 10
DEFAULT_BACKUP_KEEP = 7
BACKUP_DIR_NAME = "specialists_backups"
# Подряд 429 / 403 / сеть — останавливаем прогон, чтобы не долбить реестр.
DEFAULT_BLOCK_STREAK = 5
RETRY_AFTER_CAP_SEC = 120.0

HEADERS = {
    "User-Agent": "SRO-Bot/1.0 (+specialist sync)",
    "Accept": "application/json",
    "Content-Type": "application/json",
}


class SyncRequestError(RuntimeError):
    pass


class SyncBlocked(RuntimeError):
    """Подряд 429, 403 или сеть. Дальше реестр не спрашиваем."""


class Retryable(RuntimeError):
    pass


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip().replace(",", ".")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _run_id_now() -> str:
    # Микросекунды: два запуска в одну секунду не должны столкнуться.
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _coerce_retry_after(value) -> float | None:
    """Секунды из Retry-After. Дату HTTP не разбираем: тогда обычная пауза."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    if number <= 0:
        return None
    return number


def _unpack_transport(result) -> tuple[int, dict, float | None]:
    """(status, payload) или (status, payload, retry_after). Тесты шлют пару."""
    if not isinstance(result, tuple) or len(result) not in (2, 3):
        raise SyncRequestError("транспорт вернул не пару статус/тело")
    retry_after = None
    if len(result) == 3:
        status, payload, retry_after = result
    else:
        status, payload = result
    if not isinstance(payload, dict):
        payload = {}
    return int(status), payload, _coerce_retry_after(retry_after)


class RegistryClient:
    """POST JSON с паузой, таймаутом и повторами. transport подменяется в тестах."""

    def __init__(
        self,
        transport=None,
        *,
        min_interval: float = MIN_INTERVAL_SEC,
        timeout: float = REQUEST_TIMEOUT,
        retries: int = RETRY_TIMES,
        sleep=time.sleep,
        monotonic=time.monotonic,
        stop_after: int | None = None,
    ):
        self.transport = transport or _requests_transport
        self.min_interval = min_interval
        self.timeout = timeout
        self.retries = max(1, retries)
        self.sleep = sleep
        self.monotonic = monotonic
        self._last = 0.0
        if stop_after is None:
            stop_after = _env_int("SPECIALIST_BLOCK_STREAK", DEFAULT_BLOCK_STREAK)
        # 0 выключает раннюю остановку.
        self.stop_after = max(0, int(stop_after))
        self.consecutive_blocks = 0

    def _pace(self) -> None:
        elapsed = self.monotonic() - self._last
        wait = self.min_interval - elapsed
        if wait > 0:
            self.sleep(wait)
        self._last = self.monotonic()

    def _backoff(self, attempt: int, retry_after: float | None) -> None:
        if retry_after is not None:
            self.sleep(min(RETRY_AFTER_CAP_SEC, retry_after))
            return
        self.sleep(min(8, 2**attempt))

    def _note_block(self, reason: str) -> None:
        if self.stop_after <= 0:
            return
        self.consecutive_blocks += 1
        if self.consecutive_blocks >= self.stop_after:
            raise SyncBlocked(
                f"реестр {self.consecutive_blocks} раз подряд ответил «{reason}». "
                "Дальше не спрашиваю"
            )

    def _clear_block(self) -> None:
        self.consecutive_blocks = 0

    def post(self, url: str, body: dict) -> dict:
        last: BaseException | None = None
        for attempt in range(self.retries):
            self._pace()
            retry_after: float | None = None
            try:
                status, payload, retry_after = _unpack_transport(
                    self.transport(url, body, self.timeout)
                )
                if status == 404:
                    self._clear_block()
                    raise SyncRequestError(f"HTTP 404 {url}")
                if status == 429:
                    # Счётчик раньше повтора: на K-м ответе нового запроса уже нет.
                    self._note_block(f"HTTP 429 {url}")
                    raise Retryable("HTTP 429")
                if status == 403:
                    self._note_block(f"HTTP 403 {url}")
                    raise SyncRequestError(f"HTTP 403 {url}")
                if status in RETRY_STATUSES or status >= 500:
                    # 500 между 429 рвёт серию: это уже не «подряд».
                    self._clear_block()
                    raise Retryable(f"HTTP {status}")
                if status >= 400:
                    self._clear_block()
                    raise SyncRequestError(f"HTTP {status} {url}")
                if payload.get("success") is not True:
                    self._clear_block()
                    raise Retryable("ответ без success")
                self._clear_block()
                return payload
            except SyncBlocked:
                raise
            except (requests.Timeout, requests.ConnectionError) as exc:
                last = exc
                self._note_block(f"сеть {url}")
                if attempt + 1 >= self.retries:
                    break
                self._backoff(attempt, None)
            except Retryable as exc:
                last = exc
                if attempt + 1 >= self.retries:
                    break
                delay = retry_after if "429" in str(exc) else None
                self._backoff(attempt, delay)
        raise SyncRequestError(f"{url}: {last}")


def _requests_transport(url: str, body: dict, timeout: float) -> tuple[int, dict, str | None]:
    response = requests.post(url, json=body, headers=HEADERS, timeout=timeout)
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return response.status_code, payload, response.headers.get("Retry-After")


def _as_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _expert_mark(row: dict) -> bool:
    """В строке списка есть отметка, что специалисты у члена публиковались."""
    if not isinstance(row, dict):
        return False
    for key in (
        "last_updated_experts_at_date_time_string",
        "specialists_update_date",
    ):
        if str(row.get(key) or "").strip():
            return True
    return False


@dataclass
class MemberList:
    rows: list[dict]
    api_count: int | None
    explicit_error: bool = False


def _response_has_explicit_error(payload: dict, data: dict) -> bool:
    """Поле error в ответе списка: такой пустой набор нельзя считать правдой."""
    for obj in (payload, data):
        if isinstance(obj, dict) and obj.get("error"):
            return True
    return False


def _empty_list_may_prune(fetched: MemberList) -> bool:
    """Пустой список стирает базу только при явном count и без ошибки в ответе."""
    return fetched.api_count is not None and not fetched.explicit_error


def fetch_member_rows(client: RegistryClient, target: SroTarget) -> MemberList:
    """Все действующие члены. Неполный список — ошибка, чтобы не стереть базу."""
    rows: list[dict] = []
    seen: set[int] = set()
    page = 1
    total_pages = 1
    api_count: int | None = None
    explicit_error = False
    empty_hits = 0
    while page <= 10000:
        payload = client.post(
            target.list_url,
            {
                "filters": {"member_status": 1},
                "page": page,
                "pageCount": PAGE_COUNT,
                "sortBy": SORT_BY,
            },
        )
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            raise SyncRequestError(f"{target.code}: список без data")
        chunk = data.get("data") or []
        if not isinstance(chunk, list):
            raise SyncRequestError(f"{target.code}: data.data не список")
        if page == 1:
            api_count = _as_int(data.get("count"))
            parsed_pages = _as_int(data.get("countPages"))
            total_pages = max(1, parsed_pages or 1)
            explicit_error = _response_has_explicit_error(payload, data)
        added = 0
        for item in chunk:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            member_id = int(item["id"])
            if member_id in seen:
                continue
            seen.add(member_id)
            rows.append(item)
            added += 1
        if api_count is not None and len(seen) >= api_count:
            break
        if not chunk:
            # Пустая страница в середине списка — один повтор, потом стоп.
            empty_hits += 1
            if empty_hits >= 2:
                break
            continue
        empty_hits = 0
        if added == 0:
            # Та же страница пришла ещё раз: дальше листать бессмысленно.
            break
        if page >= total_pages and (api_count is None or len(seen) >= (api_count or 0)):
            break
        page += 1
        if api_count is not None and page > api_count + 1:
            break
    if api_count is not None and len(seen) < api_count:
        raise SyncRequestError(
            f"{target.code}: список неполный, {len(seen)} из {api_count}"
        )
    if api_count is None and page < total_pages:
        raise SyncRequestError(
            f"{target.code}: список оборвался на странице {page} из {total_pages}"
        )
    return MemberList(rows=rows, api_count=api_count, explicit_error=explicit_error)


@dataclass
class SroStats:
    code: str
    listed: int = 0
    fetched: int = 0
    skipped: int = 0
    specialists: int = 0
    errors: int = 0
    removed: int = 0
    spec_added: int = 0
    spec_removed: int = 0
    api_count: int | None = None
    expert_dated: int = 0
    # Сколько скачанных карточек с датой специалистов и сколько из них без строк.
    expert_checked: int = 0
    # Пустые корзины, как их отдал реестр. В порог и админам не идут.
    published_empty: int = 0
    # Блок специалистов не разобран: поля нет или форма не та.
    empty_despite_date: int = 0
    list_failed: bool = False
    list_rejected: bool = False

    @property
    def too_many_card_errors(self) -> bool:
        if self.errors == 0:
            return False
        attempted = self.fetched + self.errors
        if attempted < CARD_ERROR_MIN_ATTEMPTS:
            return self.errors == attempted
        return (self.errors / attempted) > CARD_ERROR_RATIO


def _should_skip(
    stored,
    row: dict,
    *,
    run_id: str,
    resume: bool,
    specialist_count: int,
) -> bool:
    if stored is None:
        return False
    if resume and (stored["fetched_run"] or "") == run_id:
        return True
    stamp = list_stamp(row)
    if stamp and (stored["list_stamp"] or "") == stamp and stored["updated_at"]:
        # Дата специалистов в списке есть, а строк в базе нет — карточку
        # когда-то сохранили пустой. Читаем ещё раз.
        if _expert_mark(row) and specialist_count <= 0:
            return False
        # Отпечаток без |rows= — прошлый прогон мог записать дату, не разобрав
        # строки (пустые корзины). Такую карточку читаем снова.
        if _expert_mark(row) and CARD_ROWS_MARK not in (stored["card_stamp"] or ""):
            return False
        return True
    return False


def _admin_ids(raw) -> list[int]:
    if raw is None:
        return []
    if isinstance(raw, (int, str)):
        try:
            return [int(raw)]
        except (TypeError, ValueError):
            return []
    out: list[int] = []
    for item in raw:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


def _empty_over(empty: int, checked: int, ratio: float, minimum: int) -> bool:
    """Пустых не меньше минимума и доля строго больше порога.

    Доля 0 или минимум 0 выключают проверку.
    """
    if ratio <= 0 or minimum <= 0 or checked <= 0 or empty < minimum:
        return False
    return (empty / checked) > ratio


def _resolve_empty_limits(
    ratio: float | None,
    minimum: int | None,
    total_ratio: float | None,
    total_min: int | None,
) -> tuple[float, int, float, int]:
    if ratio is None:
        ratio = _env_float("SPECIALIST_EMPTY_RATIO", DEFAULT_EMPTY_RATIO)
    if minimum is None:
        minimum = _env_int("SPECIALIST_EMPTY_MIN", DEFAULT_EMPTY_MIN)
    if total_ratio is None:
        total_ratio = _env_float("SPECIALIST_EMPTY_TOTAL_RATIO", DEFAULT_EMPTY_RATIO)
    if total_min is None:
        total_min = _env_int("SPECIALIST_EMPTY_TOTAL_MIN", DEFAULT_EMPTY_MIN)
    return ratio, minimum, total_ratio, total_min


def empty_cards_alert(
    rows: list[SroStats],
    ratio: float,
    minimum: int,
    total_ratio: float,
    total_min: int,
) -> str | None:
    """Текст админам, если пустых карточек больше порога по СРО или всего."""
    breaches: list[SroStats] = []
    total_empty = 0
    total_checked = 0
    for stats in rows:
        total_empty += stats.empty_despite_date
        total_checked += stats.expert_checked
        if _empty_over(stats.empty_despite_date, stats.expert_checked, ratio, minimum):
            breaches.append(stats)
    total_hit = _empty_over(total_empty, total_checked, total_ratio, total_min)
    if not breaches and not total_hit:
        return None
    lines = ["Синк специалистов: пустых карточек больше порога."]
    for stats in breaches:
        share = stats.empty_despite_date / stats.expert_checked
        lines.append(
            f"{stats.code}: {stats.empty_despite_date} из {stats.expert_checked} "
            f"({share:.0%}) при пороге >{ratio:.0%} и не меньше {minimum}"
        )
    if total_checked:
        share = total_empty / total_checked
        if total_hit:
            lines.append(
                f"Всего: {total_empty} из {total_checked} ({share:.0%}) "
                f"при пороге >{total_ratio:.0%} и не меньше {total_min}"
            )
        else:
            lines.append(f"Всего: {total_empty} из {total_checked} ({share:.0%}).")
    lines.append("Уже записанных специалистов этот проход не удалял.")
    return "\n".join(lines)


def format_specialist_delta(rows: list[SroStats]) -> str:
    """Сколько специалистов добавлено и убрано к прошлому состоянию базы."""
    lines = ["Специалисты к прошлому состоянию:"]
    total_added = 0
    total_removed = 0
    for stats in rows:
        lines.append(
            f"{stats.code}: добавлено {stats.spec_added}, убрано {stats.spec_removed}"
        )
        total_added += stats.spec_added
        total_removed += stats.spec_removed
    lines.append(f"Всего: добавлено {total_added}, убрано {total_removed}")
    return "\n".join(lines)


_UNIT_TITLES = {
    "sro-specialist-sync": "Синк специалистов",
    "sro-reestr-sync": "Ночной синк реестра",
}


def failure_alert_text(unit: str, result: str = "", code: str = "") -> str:
    """Текст, когда systemd видит падение юнита синка или TimeoutStartSec."""
    name = (unit or "sync").strip() or "sync"
    title = _UNIT_TITLES.get(name, name)
    result_text = (result or "").strip() or "unknown"
    code_text = (code or "").strip() or "?"
    if result_text == "timeout":
        why = "истёк TimeoutStartSec, systemd остановил процесс"
    else:
        why = f"юнит завершился с ошибкой (result={result_text}, code={code_text})"
    return f"{title}: {why}.\nЮнит: {name}.service\nЛоги: /opt/sro-bot/logs/"


def send_unit_failure_alert(unit: str, result: str = "", code: str = "") -> None:
    """OnFailure-юнит зовёт это. Токен в текст и в argv не попадает."""
    text = failure_alert_text(unit, result, code)
    print(text, flush=True)
    notify_admins(text)


def backup_sqlite(
    db_path: Path,
    *,
    keep: int = DEFAULT_BACKUP_KEEP,
    backup_dir: Path | None = None,
) -> Path | None:
    """Согласованная копия через sqlite3 backup. Файла ещё нет — копировать нечего.

    Хранится keep последних specialists_*.sqlite. keep меньше 1 считается как 1.
    Ошибка копирования пробрасывается: вызывающий не начинает синк.
    """
    db_path = Path(db_path)
    if not db_path.is_file():
        return None
    directory = Path(backup_dir) if backup_dir else db_path.parent / BACKUP_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    stamp = _run_id_now()
    dest = directory / f"specialists_{stamp}.sqlite"
    if dest.exists():
        dest = directory / f"specialists_{stamp}_{time.time_ns()}.sqlite"
    src = sqlite3.connect(str(db_path), timeout=30)
    try:
        dst = sqlite3.connect(str(dest), timeout=30)
        try:
            src.backup(dst)
            dst.commit()
        finally:
            dst.close()
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    finally:
        src.close()
    _prune_backups(directory, max(1, int(keep)))
    print(f"Копия базы: {dest}", flush=True)
    return dest


def _prune_backups(directory: Path, keep: int) -> None:
    files = sorted(path for path in directory.glob("specialists_*.sqlite") if path.is_file())
    if keep < 1:
        keep = 1
    for old in files[:-keep]:
        try:
            old.unlink()
        except OSError as exc:
            print(f"старую копию не удалил: {old.name}: {exc}", flush=True)


def _backup_or_alert(
    path: Path,
    *,
    keep: int | None,
    directory: Path | None,
) -> bool:
    if keep is None:
        keep = _env_int("SPECIALIST_BACKUP_KEEP", DEFAULT_BACKUP_KEEP)
    if directory is None:
        raw = (os.environ.get("SPECIALIST_BACKUP_DIR") or "").strip()
        directory = Path(raw) if raw else None
    try:
        backup_sqlite(path, keep=keep, backup_dir=directory)
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        if len(detail) > 300:
            detail = detail[:300]
        reason = f"Синк специалистов не начат: копия {path.name} не сохранилась ({detail})"
        print(reason, flush=True)
        notify_admins(reason)
        return False
    return True


def _telegram_send_error(response) -> str:
    """Пустая строка — Telegram принял сообщение. Иначе код и description."""
    status = getattr(response, "status_code", None)
    payload = None
    try:
        payload = response.json()
    except Exception:
        payload = None
    if isinstance(payload, dict) and payload.get("ok") is True and (status is None or int(status) < 400):
        return ""
    description = ""
    if isinstance(payload, dict):
        description = str(payload.get("description") or "").strip()
        code = payload.get("error_code")
        if code:
            description = f"error_code={code} {description}".strip()
    if status is not None and not description.startswith("HTTP"):
        description = f"HTTP {status} {description}".strip()
    if not description:
        description = "ответ без ok"
    if len(description) > 300:
        description = description[:300]
    return description


def notify_admins(text: str) -> None:
    """Сообщение в Telegram админам. Сбой отправки синк не роняет.

    В лог пишется причина: тип исключения или description Telegram
    (чат не найден, бот заблокирован, разбор HTML). Токен из текста
    исключения вырезается. Сетевой обрыв пробуем ещё раз.
    """
    try:
        from config_keys import BOT_ADMIN_IDS, BOT_TOKEN
    except Exception:
        print("админам не отправил: нет config_keys", flush=True)
        return
    ids = _admin_ids(BOT_ADMIN_IDS)
    token = BOT_TOKEN.strip() if isinstance(BOT_TOKEN, str) else ""
    if not ids:
        print("админам не отправил: BOT_ADMIN_IDS пуст", flush=True)
        return
    if not token:
        print("админам не отправил: BOT_TOKEN пуст", flush=True)
        return
    api = f"https://api.telegram.org/bot{token}/sendMessage"
    safe = html.escape(text)[:3500]
    for admin_id in ids:
        for attempt in range(2):
            try:
                response = requests.post(
                    api,
                    json={
                        "chat_id": admin_id,
                        "text": safe,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                    timeout=20,
                )
            except Exception as exc:
                reason = redact_secrets(f"{type(exc).__name__}: {exc}")
                if attempt == 0:
                    continue
                print(
                    f"админам не отправил: telegram {admin_id}: {reason}",
                    flush=True,
                )
                break
            reason = redact_secrets(_telegram_send_error(response))
            if not reason:
                break
            print(
                f"админам не отправил: telegram {admin_id}: {reason}",
                flush=True,
            )
            break


def _stored_members(conn, target: SroTarget) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM members WHERE registry=? AND sro_code=?",
        (target.registry, target.code),
    ).fetchone()
    return int(row[0] if row else 0)


def _reject_member_list(stats: SroStats, reason: str) -> None:
    stats.list_rejected = True
    print(reason, flush=True)
    notify_admins(reason)


def sync_sro(
    conn,
    client: RegistryClient,
    target: SroTarget,
    *,
    run_id: str,
    resume: bool,
    allow_prune: bool = False,
) -> SroStats:
    stats = SroStats(code=target.code)
    try:
        fetched = fetch_member_rows(client, target)
    except SyncBlocked:
        raise
    except SyncRequestError as exc:
        stats.list_failed = True
        print(f"{target.code}: список не скачался: {exc}", flush=True)
        return stats

    rows = fetched.rows
    seen: set[int] = set()
    stats.listed = len(rows)
    stats.api_count = fetched.api_count
    stats.expert_dated = sum(1 for row in rows if _expert_mark(row))
    expected = stats.api_count if stats.api_count is not None else stats.listed
    print(
        f"{target.code} {target.registry} id={target.registry_id}: "
        f"в списке {stats.listed} из {expected}, "
        f"с датой специалистов {stats.expert_dated}",
        flush=True,
    )
    if not rows:
        stored_before = _stored_members(conn, target)
        if stored_before == 0:
            logging.getLogger(__name__).warning(
                "%s: реестр вернул пустой список, в базе членов нет. "
                "Если СРО не пустая, реестр сломан",
                target.code,
            )
            return stats
        if not (allow_prune and _empty_list_may_prune(fetched)):
            _reject_member_list(
                stats,
                f"{target.code}: реестр вернул пустой список членов, "
                "старых записей не удаляю",
            )
            return stats
        stats.removed, spec_removed = prune_members(conn, target, set(), allow_prune=True)
        stats.spec_removed += spec_removed
        conn.commit()
        print(
            f"{target.code}: пустой список с count={fetched.api_count}, "
            f"убрано членов {stats.removed}",
            flush=True,
        )
        return stats
    stored_before = _stored_members(conn, target)
    updated_at = _utc_now()
    for index, row in enumerate(rows, start=1):
        member_id = int(row["id"])
        seen.add(member_id)
        stored = stored_member(conn, target.registry, member_id)
        already = (
            stored_specialist_count(conn, target.registry, member_id) if stored else 0
        )
        if _should_skip(
            stored,
            row,
            run_id=run_id,
            resume=resume,
            specialist_count=already,
        ):
            touch_skipped_member(conn, target, row, run_id=run_id)
            conn.commit()
            stats.skipped += 1
            continue
        try:
            payload = client.post(target.info_url(member_id), {})
        except SyncBlocked:
            raise
        except SyncRequestError as exc:
            stats.errors += 1
            print(f"{target.code}: карточка {member_id} не скачалась: {exc}", flush=True)
            continue
        card = payload.get("data") or {}
        if not isinstance(card, dict):
            stats.errors += 1
            print(f"{target.code}: карточка {member_id} без объекта data", flush=True)
            continue
        if not card_has_substance(card):
            stats.errors += 1
            print(
                f"{target.code}: карточка {member_id} пустая, специалистов не трогаю",
                flush=True,
            )
            continue
        saved = save_member(
            conn,
            target,
            row,
            card,
            run_id=run_id,
            updated_at=updated_at,
            # Дата в списке есть, а строк в карточке нет — не затирать то,
            # что уже лежит. Иначе один пустой ответ стирает НРС навсегда.
            keep_specialists_if_empty=_expert_mark(row) and already > 0,
        )
        stats.specialists += saved.rows
        stats.spec_added += saved.added
        stats.spec_removed += saved.removed
        if _expert_mark(row):
            stats.expert_checked += 1
            if saved.rows == 0:
                if experts_published_empty(card):
                    stats.published_empty += 1
                else:
                    stats.empty_despite_date += 1
        conn.commit()
        stats.fetched += 1
        if index % 100 == 0 or index == stats.listed:
            print(
                f"  {target.code}: {index}/{stats.listed}, "
                f"карточек {stats.fetched}, пропуск {stats.skipped}, ошибок {stats.errors}",
                flush=True,
            )
    if list_would_wipe_too_much(len(seen), stored_before) and not allow_prune:
        stats.removed = 0
        _reject_member_list(
            stats,
            f"{target.code}: в списке {len(seen)} членов, в базе {stored_before}. "
            "Меньше половины — старых записей не удаляю",
        )
    else:
        members_removed, spec_removed = prune_members(
            conn, target, seen, allow_prune=allow_prune
        )
        stats.removed = members_removed
        stats.spec_removed += spec_removed
    conn.commit()
    if stats.published_empty:
        print(
            f"{target.code}: в реестре нет строк специалистов у "
            f"{stats.published_empty} карточек с датой. "
            "Пустые корзины — ответ реестра, не сбой разбора. Админам не шлю.",
            flush=True,
        )
    if stats.empty_despite_date:
        message = (
            f"{target.code}: карточек с датой специалистов, но блок не разобран: "
            f"{stats.empty_despite_date}. Старых строк специалистов не стираю"
        )
        print(message, flush=True)
        logging.getLogger(__name__).warning(message)
    print(
        f"{target.code}: готово, специалистов за этот проход {stats.specialists}, "
        f"добавлено {stats.spec_added}, убрано {stats.spec_removed}, "
        f"в реестре без строк {stats.published_empty}, "
        f"блок не разобран {stats.empty_despite_date}, "
        f"убрано членов {stats.removed}",
        flush=True,
    )
    return stats


def _last_run(conn):
    ensure_schema(conn)
    # started_at без микросекунд: два прогона в одну секунду различаем по rowid,
    # иначе оборванный запуск не находится и следующий стартует заново.
    return conn.execute(
        "SELECT run_id, status FROM sync_runs ORDER BY started_at DESC, rowid DESC LIMIT 1"
    ).fetchone()


def resolve_run(conn, *, fresh: bool) -> tuple[str, bool]:
    """(run_id, resume). Незаконченный запуск продолжаем, пока не передан --fresh."""
    ensure_schema(conn)
    last = _last_run(conn)
    if last is not None and last["status"] == "running" and not fresh:
        print(f"Продолжаю запуск {last['run_id']}", flush=True)
        return last["run_id"], True
    run_id = _run_id_now()
    conn.execute(
        "INSERT INTO sync_runs (run_id, started_at, finished_at, status) VALUES (?, ?, '', 'running')",
        (run_id, _utc_now()),
    )
    conn.commit()
    return run_id, False


def finish_run(conn, run_id: str, *, ok: bool) -> None:
    conn.execute(
        "UPDATE sync_runs SET finished_at=?, status=? WHERE run_id=?",
        (_utc_now(), "ok" if ok else "failed", run_id),
    )
    conn.commit()


def sync_all(
    *,
    db_path=None,
    codes: list[str] | None = None,
    fresh: bool = False,
    client: RegistryClient | None = None,
    allow_prune: list[str] | None = None,
    empty_ratio: float | None = None,
    empty_min: int | None = None,
    empty_total_ratio: float | None = None,
    empty_total_min: int | None = None,
    backup_keep: int | None = None,
    backup_dir: Path | None = None,
    stop_after: int | None = None,
) -> int:
    path = Path(db_path) if db_path else specialists_db_path()
    if not _backup_or_alert(path, keep=backup_keep, directory=backup_dir):
        return 1
    path = init_db(path)
    if client is None:
        client = RegistryClient(stop_after=stop_after)
    targets = partner_targets(codes)
    allowed = allow_prune_codes(allow_prune)
    ratio, minimum, total_ratio, total_min = _resolve_empty_limits(
        empty_ratio, empty_min, empty_total_ratio, empty_total_min
    )
    conn = connect(path, write=True)
    try:
        run_id, resume = resolve_run(conn, fresh=fresh)
        # --sro не должен выкидывать чужих членов: prune только по переданным СРО.
        failed: list[str] = []
        collected: list[SroStats] = []
        try:
            for target in targets:
                stats = sync_sro(
                    conn,
                    client,
                    target,
                    run_id=run_id,
                    resume=resume,
                    allow_prune=target.code.upper() in allowed,
                )
                collected.append(stats)
                if stats.list_failed or stats.list_rejected or stats.too_many_card_errors:
                    failed.append(target.code)
            text = empty_cards_alert(collected, ratio, minimum, total_ratio, total_min)
            delta = format_specialist_delta(collected)
            if text:
                print(text, flush=True)
                notify_admins(f"{text}\n\n{delta}")
            print(delta, flush=True)
        except SyncBlocked as exc:
            # Прогон остаётся running: ночной запуск продолжит с того же места.
            delta = format_specialist_delta(collected)
            text = (
                "Синк специалистов остановлен: "
                f"{exc}. Следующий запуск продолжит этот же проход.\n\n{delta}"
            )
            print(text, flush=True)
            notify_admins(text)
            return 1
        except Exception:
            # Запуск остаётся running — следующий старт его продолжит.
            if collected:
                print(format_specialist_delta(collected), flush=True)
            print("Синк оборвался, следующий запуск продолжит этот же проход.", flush=True)
            raise
        finish_run(conn, run_id, ok=not failed)
    finally:
        conn.close()
    if failed:
        print(f"С ошибкой: {', '.join(failed)}", flush=True)
        return 1
    print("Синк специалистов завершён.", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Синк специалистов НРС 15 партнёрских СРО")
    parser.add_argument("--db", default="", help="путь к SQLite (иначе specialists.sqlite)")
    parser.add_argument(
        "--sro",
        action="append",
        default=None,
        help="только эти коды, можно несколько раз: --sro OGPS --sro OGPP",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="не продолжать оборванный запуск, начать новый",
    )
    parser.add_argument(
        "--allow-prune",
        action="append",
        default=None,
        metavar="CODE",
        help=(
            "удалять членов этой СРО, даже если в списке меньше половины базы. "
            "Можно несколько раз, разовый запуск. "
            "SPECIALIST_ALLOW_PRUNE в unit-файл насовсем не класть"
        ),
    )
    args = parser.parse_args(argv)
    from specialist_reestr import set_db_path

    if args.db:
        set_db_path(args.db)
    return sync_all(codes=args.sro, fresh=args.fresh, allow_prune=args.allow_prune)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("Остановлено.", flush=True)
        sys.exit(130)
