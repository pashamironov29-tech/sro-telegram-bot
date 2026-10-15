# -*- coding: utf-8 -*-
"""Специалисты НРС членов 15 СРО: локальная база и поиск по ФИО.

Источник — открытые реестры членов (не сайты nrs.*):
  https://reestr.nostroy.ru  и  https://reestr.nopriz.ru

Карточка члена:
  НОСТРОЙ — поле experts_by_category;
  НОПРИЗ — поля experts_by_category нет, специалисты в specialists_data
  (те же корзины regular / danger / other, номер в registration_number).

Синхронизацию делает specialist_sync.py. Этот модуль только читает SQLite
и отвечает на запрос. Файл базы в git не кладётся.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from html import escape as html_escape
from pathlib import Path

# Код СРО -> (реестр, id в URL /api/sro/{id}, рег. номер для сверки).
# В запрос уходит только id. Рег. номер сверяли с POST /api/sro/{id}
# (registration_number), 15.10.2026. ОГПС = СРО-С-020-22072009 в задаче
# было помечено как догадка: карточка id 87 этот номер подтверждает.
# Если id или номер разъедутся — править эту таблицу, больше нигде.
PARTNER_REGISTRY: dict[str, tuple[str, int, str]] = {
    "OGPS": ("nostroy", 87, "СРО-С-020-22072009"),
    "MOTS": ("nostroy", 179, "СРО-С-112-14122009"),
    "OSO": ("nostroy", 162, "СРО-С-095-02122009"),
    "NOSO": ("nostroy", 126, "СРО-С-059-05112009"),
    "OSOES": ("nostroy", 176, "СРО-С-109-11122009"),
    "OSOT": ("nostroy", 272, "СРО-С-206-09032010"),
    "SOVS": ("nostroy", 164, "СРО-С-097-04122009"),
    "GPS": ("nostroy", 655, "СРО-С-325-25062025"),
    "OGPO": ("nopriz", 372, "СРО-П-196-14022018"),
    "OGPP": ("nopriz", 85, "СРО-П-021-28082009"),
    "SPROF": ("nopriz", 375, "СРО-П-198-25042018"),
    "OPP": ("nopriz", 274, "СРО-П-150-12032010"),
    "PRIIS": ("nopriz", 382, "СРО-И-045-09082018"),
    "MGEO": ("nopriz", 373, "СРО-И-042-14022018"),
    "GEOIND": ("nopriz", 352, "СРО-И-034-01102012"),
}

REGISTRY_HOST = {
    "nostroy": "https://reestr.nostroy.ru",
    "nopriz": "https://reestr.nopriz.ru",
}

RESULT_LIMIT = 10
MIN_QUERY_LEN = 2

SPECIALIST_BUTTON = "🔎 Поиск специалиста по ФИО"

_ROLE_WORDS = frozenset(
    {
        "генеральный",
        "генерального",
        "исполнительный",
        "исполнительного",
        "коммерческий",
        "технический",
        "финансовый",
        "директор",
        "директора",
        "президент",
        "президента",
        "председатель",
        "председателя",
        "управляющий",
        "управляющего",
        "руководитель",
        "руководителя",
        "заместитель",
        "заместителя",
        "временно",
        "исполняющий",
        "исполняющего",
        "обязанности",
        "правления",
        "совета",
        "ген",
        "ио",
    }
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
    registry TEXT NOT NULL,
    member_id INTEGER NOT NULL,
    sro_code TEXT NOT NULL,
    sro_name TEXT NOT NULL,
    org_name TEXT,
    inn TEXT,
    member_status TEXT,
    director TEXT,
    director_norm TEXT,
    list_stamp TEXT,
    card_stamp TEXT,
    fetched_run TEXT,
    updated_at TEXT,
    PRIMARY KEY (registry, member_id)
);

CREATE TABLE IF NOT EXISTS specialists (
    registry TEXT NOT NULL,
    member_id INTEGER NOT NULL,
    fio TEXT NOT NULL,
    fio_norm TEXT NOT NULL,
    nrs_number TEXT NOT NULL DEFAULT '',
    category TEXT,
    org_id INTEGER NOT NULL,
    org_name TEXT,
    inn TEXT,
    sro_code TEXT NOT NULL,
    sro_name TEXT,
    member_status TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (registry, member_id, fio_norm, nrs_number)
);

CREATE TABLE IF NOT EXISTS sync_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT,
    finished_at TEXT,
    status TEXT
);

CREATE INDEX IF NOT EXISTS idx_spec_fio ON specialists(fio_norm);
CREATE INDEX IF NOT EXISTS idx_members_director ON members(director_norm);
CREATE INDEX IF NOT EXISTS idx_members_sro ON members(registry, sro_code);
"""


def normalize_person(value: str) -> str:
    """Нижний регистр, ё->е, точки в пробелы, лишние пробелы схлопнуть."""
    text = (value or "").replace("ё", "е").replace("Ё", "е").lower()
    text = text.replace(".", " ")
    text = re.sub(r"[^0-9a-zа-я\-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_nrs_number(value: str) -> str:
    """Как в реестре, но латинская C в начале номера — кириллическая С."""
    number = re.sub(r"\s+", "", (value or "").strip())
    if number[:1] in ("C", "c"):
        number = "С" + number[1:]
    return number


def director_fio_norm(raw: str) -> str:
    """ФИО из строки «Генеральный директор Иванов Иван Иванович»."""
    words = [
        word
        for word in normalize_person(raw).split()
        if word not in _ROLE_WORDS and len(word) > 1
    ]
    return " ".join(words)


def member_public_url(registry: str, member_id: int) -> str:
    host = REGISTRY_HOST.get(registry) or REGISTRY_HOST["nostroy"]
    return f"{host}/member/{int(member_id)}"


def api_base(registry: str) -> str:
    host = REGISTRY_HOST[registry]
    return f"{host}/api"


@dataclass(frozen=True)
class SroTarget:
    code: str
    name: str
    registry: str
    registry_id: int
    reg_number: str

    @property
    def list_url(self) -> str:
        return f"{api_base(self.registry)}/sro/{self.registry_id}/member/list"

    def info_url(self, member_id: int) -> str:
        return f"{api_base(self.registry)}/member/{int(member_id)}/info"


def partner_targets(codes: list[str] | None = None) -> list[SroTarget]:
    """Цели синка в порядке SRO_ACTIVITY. Неизвестный код — ошибка."""
    from sro_profiles import get_sro_profile, list_known_sro_ids

    wanted = [c.strip().upper() for c in codes] if codes else list_known_sro_ids()
    out: list[SroTarget] = []
    for code in wanted:
        if code not in PARTNER_REGISTRY:
            raise KeyError(f"нет id реестра для {code} — допишите PARTNER_REGISTRY")
        registry, registry_id, reg_number = PARTNER_REGISTRY[code]
        profile = get_sro_profile(code) or {}
        out.append(
            SroTarget(
                code=code,
                name=(profile.get("name") or code),
                registry=registry,
                registry_id=registry_id,
                reg_number=reg_number,
            )
        )
    return out


def _status_title(obj: dict) -> str:
    status = obj.get("member_status") if isinstance(obj, dict) else None
    if isinstance(status, dict):
        return (status.get("title") or "").strip()
    if isinstance(status, str):
        return status.strip()
    return ""


def _org_name(obj: dict) -> str:
    if not isinstance(obj, dict):
        return ""
    short = (obj.get("short_description") or "").strip()
    full = (obj.get("full_description") or "").strip()
    return short or full


def list_stamp(row: dict) -> str:
    """Отпечаток списка. Пустой — в списке нет даты специалистов (так у НОПРИЗ)."""
    if not isinstance(row, dict):
        return ""
    parts = [
        str(row.get("last_updated_at_date_time_string") or ""),
        str(row.get("last_updated_experts_at_date_time_string") or ""),
        str(row.get("specialists_update_date") or ""),
    ]
    return "|".join(part for part in parts if part)


def card_stamp(card: dict) -> str:
    if not isinstance(card, dict):
        return ""
    parts = [
        str(card.get("last_updated_at_date_time_string") or card.get("last_updated_at") or ""),
        str(
            card.get("last_updated_experts_at_date_time_string")
            or card.get("last_updated_experts_at")
            or ""
        ),
        str(card.get("specialists_update_date") or ""),
    ]
    return "|".join(part for part in parts if part)


def _category_of(item: dict, bucket: str) -> str:
    typed = item.get("expert_type") or item.get("spec_type") or {}
    title = ""
    if isinstance(typed, dict):
        title = (typed.get("title") or typed.get("code") or "").strip()
    return title or (bucket or "").strip()


def extract_specialists(card: dict) -> list[dict]:
    """Специалисты из карточки. Нет поля — пустой список, не ошибка.

    НОСТРОЙ: experts_by_category, номер в number.
    НОПРИЗ: specialists_data, номер в registration_number.
    """
    if not isinstance(card, dict):
        return []
    block = card.get("experts_by_category")
    if not isinstance(block, dict):
        block = card.get("specialists_data")
    if not isinstance(block, dict):
        return []
    merged: dict[tuple[str, str], dict] = {}
    for bucket, items in block.items():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            fio = (item.get("fio") or "").strip()
            if not fio:
                continue
            number = item.get("number")
            if not number:
                number = item.get("registration_number")
            number = normalize_nrs_number(str(number or ""))
            fio_norm = normalize_person(fio)
            if not fio_norm:
                continue
            category = _category_of(item, str(bucket))
            key = (fio_norm, number)
            prev = merged.get(key)
            if prev is None:
                merged[key] = {
                    "fio": fio,
                    "fio_norm": fio_norm,
                    "nrs_number": number,
                    "category": category,
                }
                continue
            if category and category not in (prev.get("category") or ""):
                prev["category"] = (
                    f"{prev['category']} · {category}" if prev.get("category") else category
                )
    return list(merged.values())


_db_path_override: str | None = None


def db_path() -> Path:
    if _db_path_override:
        return Path(_db_path_override)
    env = (os.environ.get("SPECIALISTS_DB") or "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parent / "specialists.sqlite"


def set_db_path(path: str | Path | None) -> None:
    global _db_path_override
    _db_path_override = str(path) if path else None


def connect(path: Path | None = None, *, write: bool = False) -> sqlite3.Connection:
    target = path or db_path()
    if write:
        target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=8000")
    if write:
        conn.execute("PRAGMA journal_mode=WAL")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)


def init_db(path: Path | None = None) -> Path:
    target = path or db_path()
    conn = connect(target, write=True)
    try:
        ensure_schema(conn)
        conn.commit()
    finally:
        conn.close()
    return target


def save_member(
    conn: sqlite3.Connection,
    target: SroTarget,
    list_row: dict,
    card: dict,
    *,
    run_id: str,
    updated_at: str,
) -> int:
    """Перезаписать члена и его специалистов. Вернуть, сколько строк специалистов."""
    member_id = int(list_row.get("id") or card.get("id"))
    org_name = _org_name(card) or _org_name(list_row)
    inn = str(card.get("inn") or list_row.get("inn") or "").strip()
    status = _status_title(card) or _status_title(list_row)
    director = (card.get("director") or "")
    if not isinstance(director, str):
        director = str(director or "")
    director = director.strip()
    specs = extract_specialists(card)
    conn.execute(
        """
        INSERT INTO members (
            registry, member_id, sro_code, sro_name, org_name, inn, member_status,
            director, director_norm, list_stamp, card_stamp, fetched_run, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(registry, member_id) DO UPDATE SET
            sro_code=excluded.sro_code,
            sro_name=excluded.sro_name,
            org_name=excluded.org_name,
            inn=excluded.inn,
            member_status=excluded.member_status,
            director=excluded.director,
            director_norm=excluded.director_norm,
            list_stamp=excluded.list_stamp,
            card_stamp=excluded.card_stamp,
            fetched_run=excluded.fetched_run,
            updated_at=excluded.updated_at
        """,
        (
            target.registry,
            member_id,
            target.code,
            target.name,
            org_name,
            inn,
            status,
            director,
            director_fio_norm(director),
            list_stamp(list_row),
            card_stamp(card),
            run_id,
            updated_at,
        ),
    )
    conn.execute(
        "DELETE FROM specialists WHERE registry=? AND member_id=?",
        (target.registry, member_id),
    )
    for spec in specs:
        conn.execute(
            """
            INSERT INTO specialists (
                registry, member_id, fio, fio_norm, nrs_number, category,
                org_id, org_name, inn, sro_code, sro_name, member_status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                target.registry,
                member_id,
                spec["fio"],
                spec["fio_norm"],
                spec["nrs_number"],
                spec["category"],
                member_id,
                org_name,
                inn,
                target.code,
                target.name,
                status,
                updated_at,
            ),
        )
    return len(specs)


def touch_skipped_member(
    conn: sqlite3.Connection,
    target: SroTarget,
    list_row: dict,
    *,
    run_id: str,
) -> None:
    """Карточку не качали: обновить название из списка и отметить запуск."""
    member_id = int(list_row["id"])
    org_name = _org_name(list_row)
    inn = str(list_row.get("inn") or "").strip()
    status = _status_title(list_row)
    conn.execute(
        """
        UPDATE members
        SET fetched_run=?, list_stamp=?,
            org_name=CASE WHEN ? != '' THEN ? ELSE org_name END,
            inn=CASE WHEN ? != '' THEN ? ELSE inn END,
            member_status=CASE WHEN ? != '' THEN ? ELSE member_status END
        WHERE registry=? AND member_id=?
        """,
        (
            run_id,
            list_stamp(list_row),
            org_name,
            org_name,
            inn,
            inn,
            status,
            status,
            target.registry,
            member_id,
        ),
    )
    conn.execute(
        """
        UPDATE specialists
        SET org_name=CASE WHEN ? != '' THEN ? ELSE org_name END,
            inn=CASE WHEN ? != '' THEN ? ELSE inn END,
            member_status=CASE WHEN ? != '' THEN ? ELSE member_status END
        WHERE registry=? AND member_id=?
        """,
        (org_name, org_name, inn, inn, status, status, target.registry, member_id),
    )


def prune_members(
    conn: sqlite3.Connection,
    target: SroTarget,
    seen_ids: set[int],
) -> int:
    """Убрать членов СРО, которых больше нет среди действующих. Вернуть, сколько членов."""
    conn.execute("DROP TABLE IF EXISTS seen_members")
    conn.execute("CREATE TEMP TABLE seen_members (id INTEGER PRIMARY KEY)")
    if seen_ids:
        conn.executemany(
            "INSERT INTO seen_members(id) VALUES (?)",
            [(int(mid),) for mid in seen_ids],
        )
    before = conn.execute(
        "SELECT COUNT(*) FROM members WHERE registry=? AND sro_code=?",
        (target.registry, target.code),
    ).fetchone()[0]
    conn.execute(
        """
        DELETE FROM specialists
        WHERE registry=? AND sro_code=?
          AND member_id NOT IN (SELECT id FROM seen_members)
        """,
        (target.registry, target.code),
    )
    conn.execute(
        """
        DELETE FROM members
        WHERE registry=? AND sro_code=?
          AND member_id NOT IN (SELECT id FROM seen_members)
        """,
        (target.registry, target.code),
    )
    after = conn.execute(
        "SELECT COUNT(*) FROM members WHERE registry=? AND sro_code=?",
        (target.registry, target.code),
    ).fetchone()[0]
    conn.execute("DROP TABLE IF EXISTS seen_members")
    return int(before) - int(after)


def stored_member(conn: sqlite3.Connection, registry: str, member_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM members WHERE registry=? AND member_id=?",
        (registry, int(member_id)),
    ).fetchone()


def db_has_rows(path: Path | None = None) -> bool:
    target = path or db_path()
    if not target.is_file():
        return False
    try:
        conn = connect(target, write=False)
    except sqlite3.Error:
        return False
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='members'"
        ).fetchone()
        if row is None:
            return False
        count = conn.execute(
            "SELECT (SELECT COUNT(*) FROM members) + (SELECT COUNT(*) FROM specialists)"
        ).fetchone()[0]
        return int(count) > 0
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def _like_prefix(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return escaped + "%"


@dataclass
class PersonHit:
    fio: str
    nrs_number: str
    category: str
    org_id: int
    org_name: str
    inn: str
    sro_code: str
    sro_name: str
    member_status: str
    registry: str
    member_id: int
    via: str  # specialist | director


@dataclass
class SearchOutcome:
    status: str  # ok | short | empty | none
    hits: list[PersonHit] = field(default_factory=list)
    total: int = 0
    director_only: bool = False


def _row_hit(row: sqlite3.Row, *, via: str, fio: str | None = None) -> PersonHit:
    return PersonHit(
        fio=fio if fio is not None else (row["fio"] or ""),
        nrs_number=(row["nrs_number"] or "") if via == "specialist" else "",
        category=(row["category"] or "") if via == "specialist" else "",
        org_id=int(row["org_id"] if via == "specialist" else row["member_id"]),
        org_name=row["org_name"] or "",
        inn=row["inn"] or "",
        sro_code=row["sro_code"] or "",
        sro_name=row["sro_name"] or "",
        member_status=row["member_status"] or "",
        registry=row["registry"],
        member_id=int(row["member_id"]),
        via=via,
    )


def search_people(query: str, *, db: Path | None = None, limit: int = RESULT_LIMIT) -> SearchOutcome:
    normalized = normalize_person(query)
    if len(normalized) < MIN_QUERY_LEN:
        return SearchOutcome(status="short")
    if not db_has_rows(db):
        return SearchOutcome(status="empty")
    path = db or db_path()
    prefix = _like_prefix(normalized)
    word_prefix = _like_prefix(normalized + " ")
    conn = connect(path, write=False)
    try:
        spec_total = conn.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT 1 FROM specialists
                WHERE fio_norm = ? OR fio_norm LIKE ? ESCAPE '\\'
                GROUP BY registry, member_id, fio_norm, nrs_number
            )
            """,
            (normalized, prefix),
        ).fetchone()[0]
        spec_rows = conn.execute(
            """
            SELECT registry, member_id, fio, fio_norm, nrs_number,
                   group_concat(category, ' · ') AS category,
                   org_id, org_name, inn, sro_code, sro_name, member_status
            FROM specialists
            WHERE fio_norm = ? OR fio_norm LIKE ? ESCAPE '\\'
            GROUP BY registry, member_id, fio_norm, nrs_number
            ORDER BY
                CASE
                    WHEN fio_norm = ? THEN 0
                    WHEN fio_norm LIKE ? ESCAPE '\\' THEN 1
                    ELSE 2
                END,
                length(fio_norm),
                fio_norm
            LIMIT ?
            """,
            (normalized, prefix, normalized, word_prefix, max(1, limit)),
        ).fetchall()
        hits = [_row_hit(row, via="specialist") for row in spec_rows]
        # Руководитель, который уже есть как специалист с тем же ФИО в той же
        # организации, в выдачу не попадает.
        director_extra = conn.execute(
            """
            SELECT COUNT(*) FROM members AS m
            WHERE (m.director_norm = ? OR m.director_norm LIKE ? ESCAPE '\\')
              AND NOT EXISTS (
                  SELECT 1 FROM specialists AS s
                  WHERE s.registry = m.registry
                    AND s.member_id = m.member_id
                    AND s.fio_norm = m.director_norm
              )
            """,
            (normalized, prefix),
        ).fetchone()[0]
        directors: list[PersonHit] = []
        if len(hits) < limit and int(director_extra):
            director_rows = conn.execute(
                """
                SELECT m.registry, m.member_id, m.director, m.director_norm, m.org_name,
                       m.inn, m.sro_code, m.sro_name, m.member_status
                FROM members AS m
                WHERE (m.director_norm = ? OR m.director_norm LIKE ? ESCAPE '\\')
                  AND NOT EXISTS (
                      SELECT 1 FROM specialists AS s
                      WHERE s.registry = m.registry
                        AND s.member_id = m.member_id
                        AND s.fio_norm = m.director_norm
                  )
                ORDER BY
                    CASE
                        WHEN m.director_norm = ? THEN 0
                        WHEN m.director_norm LIKE ? ESCAPE '\\' THEN 1
                        ELSE 2
                    END,
                    length(m.director_norm),
                    m.director_norm
                LIMIT ?
                """,
                (
                    normalized,
                    prefix,
                    normalized,
                    word_prefix,
                    max(1, limit - len(hits)),
                ),
            ).fetchall()
            for row in director_rows:
                directors.append(
                    PersonHit(
                        fio=(row["director"] or "").strip(),
                        nrs_number="",
                        category="",
                        org_id=int(row["member_id"]),
                        org_name=row["org_name"] or "",
                        inn=row["inn"] or "",
                        sro_code=row["sro_code"] or "",
                        sro_name=row["sro_name"] or "",
                        member_status=row["member_status"] or "",
                        registry=row["registry"],
                        member_id=int(row["member_id"]),
                        via="director",
                    )
                )
        if int(spec_total) >= limit:
            shown = hits[:limit]
            total = int(spec_total)
            director_only = False
        else:
            shown = hits + directors
            total = int(spec_total) + int(director_extra)
            director_only = not hits and bool(shown)
        if not shown:
            return SearchOutcome(status="none")
        return SearchOutcome(
            status="ok",
            hits=shown[:limit],
            total=max(total, len(shown)),
            director_only=director_only,
        )
    finally:
        conn.close()


def _h(text: str) -> str:
    return html_escape(str(text or ""), quote=False)


def format_specialist_intro() -> str:
    return (
        "🔎 <b>Поиск специалиста по ФИО</b>\n\n"
        "Введите <b>фамилию</b>, <b>фамилию и имя</b> или полное ФИО.\n"
        "Покажу, в какой организации человек указан как специалист НРС "
        "у членов 15 партнёрских СРО (реестры НОСТРОЙ и НОПРИЗ).\n\n"
        "Примеры:\n"
        "• <code>Иванов</code>\n"
        "• <code>Иванов Иван</code>\n"
        "• <code>Иванов Иван Иванович</code>\n\n"
        "<i>В базе только специалисты НРС из карточек членов. "
        "Остальных сотрудников организации реестр не содержит. "
        "Если специалиста нет, проверяю поле «руководитель».</i>"
    )


def _format_hit(hit: PersonHit) -> str:
    lines = [f"👤 <b>{_h(hit.fio)}</b>"]
    if hit.via == "director":
        lines.append(
            "Руководитель в карточке члена СРО "
            "(отдельной записи специалиста НРС по этому ФИО нет)"
        )
    elif hit.nrs_number:
        lines.append(f"НРС: <code>{_h(hit.nrs_number)}</code>")
    else:
        lines.append("НРС: номер в карточке не указан")
    if hit.category and hit.via == "specialist":
        lines.append(f"Категория: {_h(hit.category)}")
    if hit.org_name:
        lines.append(f"Организация: {_h(hit.org_name)}")
    if hit.inn:
        lines.append(f"ИНН: <code>{_h(hit.inn)}</code>")
    sro = hit.sro_name or hit.sro_code
    if hit.sro_code and hit.sro_name:
        sro = f"{hit.sro_name} ({hit.sro_code})"
    if sro:
        lines.append(f"СРО: {_h(sro)}")
    if hit.member_status:
        lines.append(f"Статус: {_h(hit.member_status)}")
    url = member_public_url(hit.registry, hit.member_id)
    safe_url = html_escape(url, quote=True)
    lines.append(f'<a href="{safe_url}">Карточка в реестре</a>')
    return "\n".join(lines)


_EMPTY_DB = (
    "Список специалистов ещё не загружен.\n\n"
    "Поиск заработает после синхронизации реестров НОСТРОЙ и НОПРИЗ. "
    "Пока можно проверить человека по кнопке «Проверить в НРС» — "
    "она открывает официальные сайты."
)

_NOT_FOUND = (
    "Никого не нашёл по этому ФИО.\n\n"
    "В базе только <b>специалисты НРС</b>, которых члены 15 партнёрских СРО "
    "указали в реестрах НОСТРОЙ и НОПРИЗ, и руководители из тех же карточек. "
    "Остальных сотрудников организации там нет.\n\n"
    "Проверьте написание или добавьте имя."
)

_TOO_SHORT = (
    "Введите фамилию — хотя бы две буквы.\n"
    "Можно сразу «Фамилия Имя» или полное ФИО."
)


def format_search_reply(query: str, *, db: Path | None = None) -> str:
    outcome = search_people(query, db=db)
    if outcome.status == "short":
        return _TOO_SHORT
    if outcome.status == "empty":
        return _EMPTY_DB
    if outcome.status == "none":
        return _NOT_FOUND
    chunks = [_format_hit(hit) for hit in outcome.hits]
    text = "\n\n".join(chunks)
    if outcome.director_only:
        text = (
            "В списке специалистов НРС такого ФИО нет. "
            "Ниже — совпадение по полю «руководитель» в карточке члена СРО.\n\n"
            + text
        )
    if outcome.total > len(outcome.hits):
        text += (
            f"\n\nПоказаны первые {len(outcome.hits)} из {outcome.total}. "
            "Уточните имя или отчество."
        )
    return text


# --- режим ввода, как у НРС: отдельно для Telegram и MAX ---

_plat = (os.getenv("BOT_PLATFORM") or "tg").strip().lower()
_plat = "max" if _plat == "max" else "tg"
_MODE_FILE = str(Path(__file__).resolve().parent / f"specialist_mode_{_plat}.json")
_mode_lock = threading.Lock()
_await_specialist: set[int] = set()


def _load_mode_users() -> set[int]:
    try:
        with open(_MODE_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return {int(item) for item in data}
    except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError, OSError):
        return set()
    return set()


def _save_mode_users() -> None:
    with _mode_lock:
        try:
            snap = sorted(_await_specialist)
            tmp = _MODE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(snap, fh)
            os.replace(tmp, _MODE_FILE)
        except OSError:
            pass


_await_specialist = _load_mode_users()


def enter_specialist_mode(chat_id: int) -> None:
    try:
        _await_specialist.add(int(chat_id))
    except (TypeError, ValueError):
        return
    _save_mode_users()


def exit_specialist_mode(chat_id: int) -> None:
    try:
        _await_specialist.discard(int(chat_id))
    except (TypeError, ValueError):
        return
    _save_mode_users()


def is_specialist_mode(chat_id: int) -> bool:
    try:
        return int(chat_id) in _await_specialist
    except (TypeError, ValueError):
        return False
