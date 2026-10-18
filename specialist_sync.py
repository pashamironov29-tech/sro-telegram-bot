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
у члена ни одной строки — карточку читаем снова. У НОПРИЗ в списке даты
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
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

from specialist_reestr import (
    SroTarget,
    card_has_substance,
    connect,
    ensure_schema,
    allow_prune_codes,
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

HEADERS = {
    "User-Agent": "SRO-Bot/1.0 (+specialist sync)",
    "Accept": "application/json",
    "Content-Type": "application/json",
}


class SyncRequestError(RuntimeError):
    pass


class Retryable(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _run_id_now() -> str:
    # Микросекунды: два запуска в одну секунду не должны столкнуться.
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


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
    ):
        self.transport = transport or _requests_transport
        self.min_interval = min_interval
        self.timeout = timeout
        self.retries = max(1, retries)
        self.sleep = sleep
        self.monotonic = monotonic
        self._last = 0.0

    def _pace(self) -> None:
        elapsed = self.monotonic() - self._last
        wait = self.min_interval - elapsed
        if wait > 0:
            self.sleep(wait)
        self._last = self.monotonic()

    def post(self, url: str, body: dict) -> dict:
        last: BaseException | None = None
        for attempt in range(self.retries):
            self._pace()
            try:
                status, payload = self.transport(url, body, self.timeout)
                if status == 404:
                    raise SyncRequestError(f"HTTP 404 {url}")
                if status in RETRY_STATUSES or status >= 500:
                    raise Retryable(f"HTTP {status}")
                if status >= 400:
                    raise SyncRequestError(f"HTTP {status} {url}")
                if not isinstance(payload, dict) or payload.get("success") is not True:
                    raise Retryable("ответ без success")
                return payload
            except (requests.Timeout, requests.ConnectionError, Retryable) as exc:
                last = exc
                if attempt + 1 >= self.retries:
                    break
                self.sleep(min(8, 2**attempt))
        raise SyncRequestError(f"{url}: {last}")


def _requests_transport(url: str, body: dict, timeout: float) -> tuple[int, dict]:
    response = requests.post(url, json=body, headers=HEADERS, timeout=timeout)
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    return response.status_code, payload


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
    api_count: int | None = None
    expert_dated: int = 0
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


def notify_admins(text: str) -> None:
    """Сообщение в Telegram админам. Сбой отправки синк не роняет и токен не печатает."""
    try:
        from config_keys import BOT_ADMIN_IDS, BOT_TOKEN
    except Exception:
        print("админам не отправил: нет config_keys", flush=True)
        return
    ids = _admin_ids(BOT_ADMIN_IDS)
    token = BOT_TOKEN.strip() if isinstance(BOT_TOKEN, str) else ""
    if not ids or not token:
        print("админам не отправил: BOT_ADMIN_IDS пуст", flush=True)
        return
    api = f"https://api.telegram.org/bot{token}/sendMessage"
    safe = html.escape(text)[:3500]
    for admin_id in ids:
        try:
            requests.post(
                api,
                json={
                    "chat_id": admin_id,
                    "text": safe,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=20,
            )
        except Exception:
            print(f"админам не отправил: telegram {admin_id}", flush=True)


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
        stats.removed = prune_members(conn, target, set(), allow_prune=True)
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
        )
        stats.specialists += saved
        if _expert_mark(row) and saved == 0:
            stats.empty_despite_date += 1
            print(
                f"{target.code}: член {member_id} с датой специалистов, "
                "в карточке строк нет",
                flush=True,
            )
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
        stats.removed = prune_members(conn, target, seen, allow_prune=allow_prune)
    conn.commit()
    print(
        f"{target.code}: готово, специалистов за этот проход {stats.specialists}, "
        f"пустых при дате специалистов {stats.empty_despite_date}, "
        f"убрано членов {stats.removed}",
        flush=True,
    )
    return stats


def _last_run(conn):
    ensure_schema(conn)
    return conn.execute(
        "SELECT run_id, status FROM sync_runs ORDER BY started_at DESC LIMIT 1"
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
) -> int:
    path = init_db(db_path)
    client = client or RegistryClient()
    targets = partner_targets(codes)
    allowed = allow_prune_codes(allow_prune)
    conn = connect(path, write=True)
    try:
        run_id, resume = resolve_run(conn, fresh=fresh)
        # --sro не должен выкидывать чужих членов: prune только по переданным СРО.
        failed: list[str] = []
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
                if (
                    stats.list_failed
                    or stats.list_rejected
                    or stats.too_many_card_errors
                    or stats.empty_despite_date
                ):
                    failed.append(target.code)
        except Exception:
            # Запуск остаётся running — следующий старт его продолжит.
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
