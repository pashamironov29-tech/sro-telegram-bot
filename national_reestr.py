# -*- coding: utf-8 -*-
"""Поиск организации в единых реестрах членов всех СРО.

Те же открытые эндпоинты, что у синка специалистов (specialist_sync.RegistryClient).
Ключ не нужен: POST JSON, как на сайтах реестров.

  POST https://reestr.nostroy.ru/api/sro/all/member/list
  POST https://reestr.nopriz.ru/api/sro/all/member/list
       {"filters": {"inn"|"ogrnip": "..."} | {}, "page": 1,
        "pageCount": "20", "sortBy": {}, "searchString": "<название или пусто>"}
  POST https://reestr.{nostroy|nopriz}.ru/api/member/{id}/info
       в ответе и специалисты НРС организации: НОСТРОЙ — experts_by_category,
       НОПРИЗ — specialists_data (корзины regular / danger / other)
  POST https://reestr.{nostroy|nopriz}.ru/api/sro/{id}
       рег. номер, если его не было в списке, и короткое имя СРО для кнопок

НОСТРОЙ — строители, НОПРИЗ — изыскатели и проектировщики.
Список — не только 15 партнёров.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path

import requests

from specialist_reestr import api_base, member_public_url
from specialist_sync import RegistryClient, SyncRequestError

log = logging.getLogger(__name__)

NATIONAL_BUTTON = "🏛 Поиск в НОСТРОЙ / НОПРИЗ"

REGISTRY_TITLE = {"nostroy": "НОСТРОЙ", "nopriz": "НОПРИЗ"}
REGISTRIES = ("nostroy", "nopriz")

LIST_CAP = 8
TOO_MANY = 20
NAME_MIN = 3
REQUEST_TIMEOUT = 12

CARD_FAIL = (
    "Не удалось открыть карточку в реестре. "
    "Попробуйте ещё раз через минуту."
)
SEARCH_FAIL = (
    "Не удалось выполнить поиск в реестрах НОСТРОЙ и НОПРИЗ. "
    "Попробуйте ещё раз через минуту."
)

_CB_RE = re.compile(r"^nat:(nostroy|nopriz):(\d{1,12})$")
_PAGE_CB_RE = re.compile(r"^natp:(nostroy|nopriz):(\d{1,12}):(\d{1,4})$")
PEOPLE_PAGE = 10
MESSAGE_LIMIT = 3900  # Telegram и MAX режут около 4000; запас под HTML
PEOPLE_FAIL = (
    "Список специалистов сейчас не загрузился: реестр не ответил. "
    "Попробуйте позже или откройте карточку в реестре."
)


@dataclass
class PickButton:
    label: str
    payload: str


@dataclass
class SearchResult:
    text: str
    buttons: list[PickButton] = field(default_factory=list)


@dataclass
class MemberHit:
    registry: str
    member_id: int
    name: str = ""
    inn: str = ""
    ogrn: str = ""
    sro_name: str = ""
    sro_short: str = ""
    sro_reg: str = ""
    sro_id: int | None = None
    sro_note: str = ""
    status_title: str = ""
    status_code: str = ""
    registry_date: str = ""
    suspension_date: str = ""
    right_title: str = ""
    work_scope: str = ""
    level_vv: str = ""
    level_odo: str = ""
    card_note: str = ""

    @property
    def registry_title(self) -> str:
        return REGISTRY_TITLE.get(self.registry, self.registry)

    @property
    def url(self) -> str:
        return member_public_url(self.registry, self.member_id)

    @property
    def status_line(self) -> str:
        return _status_line(
            self.status_title,
            self.status_code,
            self.registry_date,
            self.suspension_date,
        )


def make_client(transport=None, *, timeout: float | None = None) -> RegistryClient:
    """Короткий запрос из чата: один таймаут, без паузы синка.

    Без timeout — 12 секунд, так ходит MAX. Telegram передаёт 6.
    """
    return RegistryClient(
        transport,
        min_interval=0,
        timeout=REQUEST_TIMEOUT if timeout is None else timeout,
        retries=1,
        sleep=lambda _s: None,
    )


def format_intro() -> str:
    return (
        "🏛 <b>Поиск в НОСТРОЙ / НОПРИЗ</b>\n\n"
        "Единый реестр членов <b>всех</b> СРО, не только 15 партнёров.\n"
        "НОСТРОЙ — строители, НОПРИЗ — изыскатели и проектировщики.\n\n"
        "Введите <b>ИНН</b>, <b>ОГРН</b> или часть <b>названия</b>."
    )


def error_result() -> SearchResult:
    return SearchResult(SEARCH_FAIL)


def classify_query(text: str) -> tuple[str, str]:
    """inn | ogrn | name | short | bad."""
    raw = (text or "").strip()
    compact = re.sub(r"\s+", "", raw)
    if compact.isdigit():
        if len(compact) in (10, 12):
            return "inn", compact
        if len(compact) in (13, 15):
            return "ogrn", compact
        return "bad", compact
    name = raw.replace('"', "").replace("«", "").replace("»", "")
    name = re.sub(r"\s+", " ", name).strip()
    if len(name) < NAME_MIN:
        return "short", name
    return "name", name[:120]


def format_date(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    matched = re.match(r"(\d{2}\.\d{2}\.\d{4})", text)
    if matched:
        return matched.group(1)
    matched = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if matched:
        return f"{matched.group(3)}.{matched.group(2)}.{matched.group(1)}"
    return ""


def _h(value) -> str:
    return html.escape(str(value or ""), quote=False)


def _text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _status_parts(obj) -> tuple[str, str]:
    if isinstance(obj, dict):
        return _text(obj.get("title")), _text(obj.get("code"))
    if isinstance(obj, str):
        return obj.strip(), ""
    return "", ""


def _status_line(title: str, code: str, registry_date: str, suspension_date: str) -> str:
    title = title or "статус не указан"
    if code == "2":
        bits: list[str] = []
        if suspension_date:
            bits.append(suspension_date)
        if registry_date:
            bits.append(f"в реестре с {registry_date}")
        if bits:
            return f"{title} ({', '.join(bits)})"
        return title
    if registry_date:
        return f"{title} (в реестре с {registry_date})"
    return title


def _sro_fields(obj: dict) -> tuple[str, str, str, int | None, str]:
    sro = obj.get("sro") if isinstance(obj, dict) else None
    if not isinstance(sro, dict):
        return "", "", "", None, ""
    name = _text(sro.get("full_description")) or _text(sro.get("short_description"))
    short = _text(sro.get("short_description"))
    reg = _text(sro.get("registration_number"))
    note = _text(sro.get("deactivate_message"))
    return name, short, reg, _as_int(sro.get("id")), note


def _org_name(obj: dict) -> str:
    if not isinstance(obj, dict):
        return ""
    return _text(obj.get("short_description")) or _text(obj.get("full_description"))


def _level_text(level) -> str:
    if not isinstance(level, dict):
        return ""
    title = _text(level.get("title"))
    cost = _text(level.get("cost"))
    if str(level.get("code") or "") == "0" and title and "снос" not in title.lower():
        title = f"{title} (только снос)"
    if title and cost:
        return f"{title}, {cost}"
    return title or cost


def _right_title(card: dict) -> str:
    right = card.get("right") if isinstance(card.get("right"), dict) else None
    vv = card.get("member_right_vv") if isinstance(card.get("member_right_vv"), dict) else None

    def _one(obj) -> str:
        if not isinstance(obj, dict):
            return ""
        title, _code = _status_parts(obj.get("right_status"))
        return title

    main = _one(right)
    extra = _one(vv)
    if main and extra and extra != main:
        return f"{main}; ВВ — {extra}"
    return main or extra


def _work_scope(card: dict) -> str:
    right = card.get("right") if isinstance(card.get("right"), dict) else None
    if right is None:
        right = card.get("member_right_vv") if isinstance(card.get("member_right_vv"), dict) else None
    if not isinstance(right, dict):
        return ""
    parts: list[str] = []
    if right.get("is_simple") is True:
        parts.append("обычные объекты")
    if right.get("is_extremely_dangerous") is True:
        parts.append("особо опасные")
    if right.get("is_nuclear") is True:
        parts.append("атомная энергия")
    if right.get("is_odo") is True:
        parts.append("договоры ОДО")
    return ", ".join(parts)


def _vv_level(card: dict) -> str:
    text = _level_text(card.get("responsibility_level_vv"))
    if text:
        return text
    vv = card.get("member_right_vv")
    if isinstance(vv, dict):
        return _level_text(vv.get("responsibility_level"))
    return ""


def parse_list_row(registry: str, row: dict) -> MemberHit | None:
    if registry not in REGISTRY_TITLE or not isinstance(row, dict):
        return None
    member_id = _as_int(row.get("id"))
    if member_id is None:
        return None
    title, code = _status_parts(row.get("member_status"))
    sro_name, sro_short, sro_reg, sro_id, sro_note = _sro_fields(row)
    return MemberHit(
        registry=registry,
        member_id=member_id,
        name=_org_name(row) or f"Член {member_id}",
        inn=_text(row.get("inn")),
        ogrn=_text(row.get("ogrnip")),
        sro_name=sro_name,
        sro_short=sro_short,
        sro_reg=sro_reg,
        sro_id=sro_id,
        sro_note=sro_note,
        status_title=title,
        status_code=code,
        registry_date=format_date(row.get("registry_registration_date"))
        or format_date(row.get("registry_registration_date_time_string")),
        suspension_date=format_date(row.get("suspension_date")),
    )


def apply_card(hit: MemberHit, card: dict) -> MemberHit:
    """Дополнить строку списка полями карточки. Пустые поля карточки не затирают список."""
    if not isinstance(card, dict):
        return hit
    title, code = _status_parts(card.get("member_status"))
    sro_name, sro_short, sro_reg, sro_id, sro_note = _sro_fields(card)
    name = _org_name(card) or hit.name
    suspension = format_date(card.get("suspension_date")) or hit.suspension_date
    registry_date = (
        format_date(card.get("registry_registration_date"))
        or format_date(card.get("registry_registration_date_time_string"))
        or hit.registry_date
    )
    if not title and not code and suspension and not hit.status_title:
        title, code = "Исключен", "2"
    return replace(
        hit,
        name=name,
        inn=_text(card.get("inn")) or hit.inn,
        ogrn=_text(card.get("ogrnip")) or hit.ogrn,
        sro_name=sro_name or hit.sro_name,
        sro_short=sro_short or hit.sro_short,
        sro_reg=sro_reg or hit.sro_reg,
        sro_id=sro_id if sro_id is not None else hit.sro_id,
        sro_note=sro_note or hit.sro_note,
        status_title=title or hit.status_title,
        status_code=code or hit.status_code,
        registry_date=registry_date,
        suspension_date=suspension,
        right_title=_right_title(card),
        work_scope=_work_scope(card),
        level_vv=_vv_level(card),
        level_odo=_level_text(card.get("responsibility_level_odo")),
    )


def hit_from_card(registry: str, member_id: int, card: dict) -> MemberHit:
    base = MemberHit(registry=registry, member_id=member_id, name=f"Член {member_id}")
    return apply_card(base, card if isinstance(card, dict) else {})


def rows_from_payload(payload: dict) -> tuple[list[dict], int]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return [], 0
    chunk = data.get("data") or []
    if not isinstance(chunk, list):
        return [], 0
    rows = [row for row in chunk if isinstance(row, dict)]
    count = _as_int(data.get("count"))
    if count is None:
        count = len(rows)
    return rows, count


def list_url(registry: str) -> str:
    return f"{api_base(registry)}/sro/all/member/list"


def info_url(registry: str, member_id: int) -> str:
    return f"{api_base(registry)}/member/{int(member_id)}/info"


def sro_url(registry: str, sro_id: int) -> str:
    return f"{api_base(registry)}/sro/{int(sro_id)}"


def _request_body(kind: str, value: str) -> dict:
    filters: dict = {}
    search = ""
    if kind == "inn":
        filters = {"inn": value}
    elif kind == "ogrn":
        filters = {"ogrnip": value}
    else:
        search = value
    return {
        "filters": filters,
        "page": 1,
        "pageCount": "20",
        "sortBy": {},
        "searchString": search,
    }


def _down_phrase(title: str, exc: BaseException) -> str:
    raw = str(exc).lower()
    if "timeout" in raw or "timed out" in raw:
        return f"Реестр {title} не ответил вовремя."
    return f"Реестр {title} временно недоступен."


def _post(client: RegistryClient, url: str, body: dict) -> tuple[dict | None, BaseException | None]:
    try:
        return client.post(url, body), None
    except (SyncRequestError, requests.RequestException, OSError) as exc:
        log.warning("реестр не ответил: %s", exc)
        return None, exc
    except Exception as exc:
        log.warning("реестр: неожиданный сбой", exc_info=True)
        return None, exc


def _fill_sro_reg(client: RegistryClient, hit: MemberHit) -> MemberHit:
    sro_id = hit.sro_id
    if hit.sro_reg or sro_id is None:
        return hit
    payload, exc = _post(client, sro_url(hit.registry, sro_id), {})
    if exc or not isinstance(payload, dict):
        return hit
    data = payload.get("data")
    if not isinstance(data, dict):
        return hit
    reg = _text(data.get("registration_number"))
    short = _text(data.get("short_description"))
    name = _text(data.get("full_description")) or short
    if not reg and not name and not short:
        return hit
    _remember_sro_brief(hit.registry, sro_id, short, name, reg)
    return replace(
        hit,
        sro_reg=reg or hit.sro_reg,
        sro_name=name or hit.sro_name,
        sro_short=short or hit.sro_short,
    )


def format_member_card(hit: MemberHit) -> str:
    lines = [
        f"🏛 <b>{_h(hit.registry_title)}</b>",
        f"<b>{_h(hit.name)}</b>",
    ]
    if hit.inn:
        lines.append(f"ИНН: <code>{_h(hit.inn)}</code>")
    if hit.ogrn:
        lines.append(f"ОГРН: <code>{_h(hit.ogrn)}</code>")
    if hit.sro_name:
        lines.append(f"СРО: {_h(hit.sro_name)}")
    if hit.sro_reg:
        lines.append(f"Рег. номер СРО: <code>{_h(hit.sro_reg)}</code>")
    if hit.sro_note:
        lines.append(
            "Сведения об этом СРО исключены из государственного реестра "
            f"({_h(hit.sro_note)})."
        )
    lines.append(f"Статус: {_h(hit.status_line)}")
    if hit.right_title:
        lines.append(f"Право на работы: {_h(hit.right_title)}")
    if hit.work_scope:
        lines.append(f"Виды объектов: {_h(hit.work_scope)}")
    if hit.level_vv:
        lines.append(f"Уровень ВВ: {_h(hit.level_vv)}")
    if hit.level_odo:
        lines.append(f"Уровень ОДО: {_h(hit.level_odo)}")
    if hit.card_note:
        lines.append(_h(hit.card_note))
    lines.append(f'Карточка: <a href="{html.escape(hit.url, quote=True)}">открыть в реестре</a>')
    return "\n".join(lines)


# Кнопка Telegram — до 64 символов, callback_data — до 64 байт.
# Держим подпись короче, чтобы на телефоне было видно реестр и СРО.
_BUTTON_LIMIT = 60
_SEP = " · "
_QUOTE_RE = re.compile(r"[«»\"“”„]+")
_SRO_PREFIX_RE = re.compile(
    r"^(?:"
    r"саморегулируемая\s+организация|"
    r"некоммерческое\s+партн[её]рство|"
    r"ассоциация|"
    r"союз|"
    r"сро|"
    r"нп|"
    r"ас|"
    r"а"
    r")(?=\s|$|[«»\"“”„()\-–—])",
    re.IGNORECASE,
)
_ORG_PREFIX_RE = re.compile(
    r"^(?:"
    r"общество\s+с\s+ограниченной\s+ответственностью|"
    r"публичное\s+акционерное\s+общество|"
    r"непубличное\s+акционерное\s+общество|"
    r"закрытое\s+акционерное\s+общество|"
    r"открытое\s+акционерное\s+общество|"
    r"акционерное\s+общество|"
    r"индивидуальный\s+предприниматель|"
    r"ооо|оао|зао|пао|нао|ао|ип|нко|ано"
    r")(?=\s|$)",
    re.IGNORECASE,
)
_SRO_TAIL_RE = re.compile(
    r"\s+в\s+(?:строительстве|проектировании|изысканиях)\.?\s*$",
    re.IGNORECASE,
)


def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").replace("\n", " ")).strip()


def _clip(text: str, limit: int) -> str:
    """Обрезать по словам, лимит — в символах, не в байтах."""
    text = _one_line(text)
    if limit <= 0 or not text:
        return ""
    if len(text) <= limit:
        return text
    if limit == 1:
        return "…"
    cut = text[: limit - 1].rstrip()
    if " " in cut:
        head = cut.rsplit(" ", 1)[0].rstrip(" ·,;:-")
        if len(head) >= max(4, limit // 3):
            cut = head
    cut = cut.rstrip(" ·,;:-")
    if not cut:
        cut = text[: limit - 1].rstrip()
    return cut + "…"


def _strip_sro_wrappers(text: str) -> str:
    cleaned = _one_line(_QUOTE_RE.sub(" ", text))
    for _ in range(8):
        nxt = cleaned.lstrip(" \t-–—\"'«»“”„().,")
        nxt = _SRO_PREFIX_RE.sub("", nxt, count=1)
        nxt = nxt.strip(" \t-–—\"'«»“”„().,")
        nxt = _one_line(nxt)
        if not nxt or nxt == cleaned:
            break
        cleaned = nxt
    return cleaned


def _org_button_name(name: str) -> str:
    cleaned = _one_line(_QUOTE_RE.sub(" ", name))
    nxt = _ORG_PREFIX_RE.sub("", cleaned, count=1).strip()
    return _one_line(nxt) or cleaned


def _sro_button_name(name: str) -> str:
    """Короткое имя с карточки СРО: без «Ассоциация» и хвоста «в строительстве»."""
    raw = _one_line(_QUOTE_RE.sub(" ", name))
    if not raw:
        return ""
    cleaned = _strip_sro_wrappers(raw)
    if not cleaned:
        cleaned = raw
    cleaned = _one_line(_SRO_TAIL_RE.sub("", cleaned))
    cleaned = re.sub(r"(?i)^объединение\b", "Объед.", cleaned, count=1)
    return _one_line(cleaned)


def _fit_button(org: str, registry: str, sro: str) -> str:
    """Реестр не обрезаем: укорачиваем название организации и СРО."""
    org = _one_line(org) or "Организация"
    registry = _one_line(registry)
    sro = _one_line(sro)
    if registry and sro:
        overhead = len(_SEP) * 2 + len(registry)
        budget = _BUTTON_LIMIT - overhead
        if budget < 4:
            room = _BUTTON_LIMIT - len(_SEP) - len(registry)
            return f"{_clip(org, max(1, room))}{_SEP}{registry}"
        if len(org) + len(sro) <= budget:
            return f"{org}{_SEP}{registry}{_SEP}{sro}"
        sro_take = min(len(sro), max(4, budget // 2))
        org_take = budget - sro_take
        if len(org) < org_take:
            org_take = len(org)
            sro_take = budget - org_take
        elif len(sro) < sro_take:
            sro_take = len(sro)
            org_take = budget - sro_take
        org_part = _clip(org, max(1, org_take))
        sro_part = _clip(sro, max(1, sro_take))
        return f"{org_part}{_SEP}{registry}{_SEP}{sro_part}"
    if registry:
        room = _BUTTON_LIMIT - len(_SEP) - len(registry)
        if room < 1:
            return _clip(registry, _BUTTON_LIMIT)
        return f"{_clip(org, room)}{_SEP}{registry}"
    if sro:
        room = _BUTTON_LIMIT - len(_SEP) - len(sro)
        if room >= 4 and len(org) > room:
            return f"{_clip(org, room)}{_SEP}{sro}"
        return _clip(f"{org}{_SEP}{sro}", _BUTTON_LIMIT)
    return _clip(org, _BUTTON_LIMIT)


def _membership_where(hit: MemberHit) -> str:
    parts: list[str] = []
    if hit.registry_title:
        parts.append(hit.registry_title)
    sro = hit.sro_name or hit.sro_short
    if sro:
        parts.append(sro)
    if hit.sro_reg:
        parts.append(hit.sro_reg)
    return _SEP.join(parts)


def format_member_list(query: str, hits: list[MemberHit], total: int) -> str:
    lines = [
        f"🏛 По запросу «<b>{_h(query)}</b>» найдено: {total}",
        "Выберите организацию:",
    ]
    for index, hit in enumerate(hits, start=1):
        status = hit.status_title or "статус не указан"
        lines.append(
            f"{index}. {_h(hit.name)} — {_h(status)} — {_h(_membership_where(hit))}"
        )
    if total > len(hits):
        lines.append(f"Показаны первые {len(hits)} из {total}. Уточните запрос или введите ИНН.")
    return "\n".join(lines)


def button_label(hit: MemberHit) -> str:
    org = _org_button_name(hit.name)
    registry = hit.registry_title
    sro = _sro_button_name(hit.sro_short or hit.sro_name)
    if registry or sro:
        return _fit_button(org, registry, sro)
    if hit.status_code == "1":
        status = "член"
    else:
        status = hit.status_title or "карточка"
    return _clip(f"{hit.name}{_SEP}{status}", _BUTTON_LIMIT)


def callback_payload(hit: MemberHit) -> str:
    return f"nat:{hit.registry}:{hit.member_id}"


def parse_callback(payload: str) -> tuple[str, int] | None:
    matched = _CB_RE.match((payload or "").strip())
    if not matched:
        return None
    return matched.group(1), int(matched.group(2))


_HIT_CACHE: dict[tuple[str, int], MemberHit] = {}
_HIT_CACHE_MAX = 300
_cache_lock = threading.Lock()


def remember(hit: MemberHit) -> None:
    key = (hit.registry, hit.member_id)
    with _cache_lock:
        _HIT_CACHE.pop(key, None)
        _HIT_CACHE[key] = hit
        while len(_HIT_CACHE) > _HIT_CACHE_MAX:
            _HIT_CACHE.pop(next(iter(_HIT_CACHE)))


def cached_hit(registry: str, member_id: int) -> MemberHit | None:
    with _cache_lock:
        return _HIT_CACHE.get((registry, member_id))


def clear_hit_cache() -> None:
    with _cache_lock:
        _HIT_CACHE.clear()


# Короткое имя СРО с карточки /api/sro/{id}. В строке списка его нет.
# Телефоны и почта с той же карточки сюда не пишем.
_SRO_BRIEF: dict[tuple[str, int], tuple[str, str, str]] = {}
_SRO_BRIEF_MAX = 400


def _remember_sro_brief(
    registry: str, sro_id: int, short: str, full: str, reg: str
) -> None:
    key = (registry, int(sro_id))
    with _cache_lock:
        _SRO_BRIEF.pop(key, None)
        _SRO_BRIEF[key] = (short, full, reg)
        while len(_SRO_BRIEF) > _SRO_BRIEF_MAX:
            _SRO_BRIEF.pop(next(iter(_SRO_BRIEF)))


def _cached_sro_brief(registry: str, sro_id: int) -> tuple[str, str, str] | None:
    with _cache_lock:
        return _SRO_BRIEF.get((registry, int(sro_id)))


def clear_sro_cache() -> None:
    with _cache_lock:
        _SRO_BRIEF.clear()


def _apply_sro_brief(hit: MemberHit, short: str, full: str, reg: str) -> MemberHit:
    return replace(
        hit,
        sro_short=short or hit.sro_short,
        sro_name=hit.sro_name or full or short,
        sro_reg=hit.sro_reg or reg,
    )


def _load_sro_brief(client: RegistryClient, hit: MemberHit) -> MemberHit:
    if hit.sro_id is None:
        return hit
    cached = _cached_sro_brief(hit.registry, hit.sro_id)
    if cached is not None:
        return _apply_sro_brief(hit, *cached)
    payload, exc = _post(client, sro_url(hit.registry, hit.sro_id), {})
    if exc or not isinstance(payload, dict):
        return hit
    data = payload.get("data")
    if not isinstance(data, dict):
        return hit
    short = _text(data.get("short_description"))
    full = _text(data.get("full_description")) or short
    reg = _text(data.get("registration_number"))
    if not short and not full and not reg:
        return hit
    _remember_sro_brief(hit.registry, hit.sro_id, short, full, reg)
    return _apply_sro_brief(hit, short, full, reg)


def _attach_sro_shorts(client: RegistryClient, hits: list[MemberHit]) -> list[MemberHit]:
    """Подпись кнопки. Сбой карточки СРО не прячет уже найденный список."""
    ready: list[MemberHit] = []
    for hit in hits:
        if hit.sro_short or hit.sro_id is None:
            ready.append(hit)
            continue
        ready.append(_load_sro_brief(client, hit))
    return ready


def _enrich(client: RegistryClient, hit: MemberHit) -> MemberHit:
    payload, exc = _post(client, info_url(hit.registry, hit.member_id), {})
    data = payload.get("data") if isinstance(payload, dict) else None
    if exc or not isinstance(data, dict):
        return replace(
            hit,
            card_note="Подробности карточки (право и уровни) сейчас не загрузились.",
        )
    filled = apply_card(hit, data)
    return _fill_sro_reg(client, filled)


def search_members(query: str, *, client: RegistryClient | None = None) -> SearchResult:
    """Поиск по обоим реестрам. Сбой API — текст, не исключение."""
    try:
        return _search_members(query, client=client)
    except Exception:
        log.warning("поиск в едином реестре упал", exc_info=True)
        return error_result()


def _search_members(query: str, *, client: RegistryClient | None) -> SearchResult:
    kind, value = classify_query(query)
    if kind == "short":
        return SearchResult(
            "Для поиска по названию нужно хотя бы 3 символа. "
            "Или введите ИНН (10 или 12 цифр) либо ОГРН (13 или 15)."
        )
    if kind == "bad":
        return SearchResult(
            "ИНН — 10 или 12 цифр, ОГРН — 13, ОГРНИП — 15. "
            "Или введите часть названия."
        )
    own_client = client or make_client()
    body = _request_body(kind, value)
    hits: list[MemberHit] = []
    total = 0
    failures: list[tuple[str, BaseException]] = []
    for registry in REGISTRIES:
        title = REGISTRY_TITLE[registry]
        payload, exc = _post(own_client, list_url(registry), body)
        if exc or not isinstance(payload, dict):
            failures.append((title, exc or SyncRequestError("пустой ответ")))
            continue
        rows, count = rows_from_payload(payload)
        parsed = []
        for row in rows:
            hit = parse_list_row(registry, row)
            if hit:
                parsed.append(hit)
        total += max(count, len(parsed))
        hits.extend(parsed)

    if failures and not hits:
        if len(failures) == len(REGISTRIES):
            phrases = [_down_phrase(title, exc) for title, exc in failures]
            if all("не ответил вовремя" in phrase for phrase in phrases):
                return SearchResult(
                    "Реестры НОСТРОЙ и НОПРИЗ не ответили вовремя. "
                    "Попробуйте ещё раз через минуту."
                )
            return error_result()
        down = failures[0][0]
        up = "НОПРИЗ" if down == "НОСТРОЙ" else "НОСТРОЙ"
        return SearchResult(
            f"В реестре {up} такой организации нет. "
            f"{_down_phrase(down, failures[0][1])} "
            "Поиск по нему не выполнен."
        )

    if not hits:
        return SearchResult("В реестрах НОСТРОЙ и НОПРИЗ такой организации нет.")

    note = ""
    if failures:
        shown_title = "НОПРИЗ" if failures[0][0] == "НОСТРОЙ" else "НОСТРОЙ"
        down = _down_phrase(failures[0][0], failures[0][1])
        if total > TOO_MANY:
            note = f"\n\n{down} Этот реестр в подсчёт не вошёл."
        else:
            note = f"\n\n{down} Показаны только совпадения {shown_title}."

    if total > TOO_MANY:
        text = (
            f"🏛 По запросу «<b>{_h(value)}</b>» слишком много совпадений ({total}). "
            "Уточните название или введите ИНН / ОГРН."
        )
        return SearchResult(text + note)

    if len(hits) == 1 and total == 1:
        hit = _enrich(own_client, hits[0])
        remember(hit)
        return SearchResult(format_member_card(hit) + note)

    shown = _attach_sro_shorts(own_client, hits[:LIST_CAP])
    for hit in shown:
        remember(hit)
    buttons = [PickButton(button_label(hit), callback_payload(hit)) for hit in shown]
    return SearchResult(format_member_list(value, shown, total) + note, buttons)


# --- специалисты НРС организации (из той же карточки /member/{id}/info) ---


@dataclass
class Person:
    fio: str
    number: str = ""
    kind: str = ""
    work: str = ""
    added: str = ""


def _type_title(value) -> str:
    if isinstance(value, dict):
        return _text(value.get("title") or value.get("code"))
    return _text(value)


def specialists_block(card) -> dict | None:
    """Корзины специалистов или None, если реестр блок не отдал."""
    if not isinstance(card, dict):
        return None
    block = card.get("experts_by_category")
    if not isinstance(block, dict):
        block = card.get("specialists_data")
    return block if isinstance(block, dict) else None


def extract_people(card) -> list[Person]:
    """Специалисты карточки по порядку реестра, без дублей ФИО+номер."""
    block = specialists_block(card) or {}
    people: list[Person] = []
    seen: dict[tuple[str, str], Person] = {}
    for bucket, items in block.items():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            fio = " ".join(_text(item.get("fio")).split())
            if not fio:
                continue
            number = _text(item.get("number") or item.get("registration_number"))
            kind = _type_title(item.get("expert_type") or item.get("spec_type")) or _text(bucket)
            work = _type_title(item.get("work_type"))
            key = (fio.lower(), number)
            prev = seen.get(key)
            if prev is not None:
                if kind and kind not in prev.kind:
                    prev.kind = f"{prev.kind} · {kind}" if prev.kind else kind
                if work and work not in prev.work:
                    prev.work = f"{prev.work} · {work}" if prev.work else work
                continue
            person = Person(fio, number, kind, work, format_date(item.get("created")))
            seen[key] = person
            people.append(person)
    return people


def _people_pages(count: int) -> int:
    return max(1, (count + PEOPLE_PAGE - 1) // PEOPLE_PAGE)


def page_payload(registry: str, member_id: int, page: int) -> str:
    return f"natp:{registry}:{member_id}:{page}"


def parse_page_callback(payload: str) -> tuple[str, int, int] | None:
    match = _PAGE_CB_RE.match((payload or "").strip())
    if not match:
        return None
    return match.group(1), int(match.group(2)), max(1, int(match.group(3)))


def _format_person(index: int, person: Person) -> str:
    line = f"{index}. <b>{_h(person.fio)}</b>"
    if person.number:
        line += f" — <code>{_h(person.number)}</code>"
    extra = [part for part in (person.kind, _clip(person.work, 120)) if part]
    if person.added:
        extra.append(f"в списке с {person.added}")
    if extra:
        line += f"\n    {_h('; '.join(extra))}"
    return line


def format_people(card, page: int = 1) -> tuple[str, int, int]:
    """Текст страницы специалистов, номер страницы и число страниц."""
    block = specialists_block(card)
    if block is None:
        return "👥 Специалисты НРС: реестр не отдал список для этой организации.", 1, 1
    people = extract_people(card)
    if not people:
        return "👥 Специалисты НРС: в реестре нет данных о специалистах.", 1, 1
    pages = _people_pages(len(people))
    page = min(max(1, page), pages)
    start = (page - 1) * PEOPLE_PAGE
    shown = people[start : start + PEOPLE_PAGE]
    head = f"👥 <b>Специалисты НРС: {len(people)}</b>"
    if pages > 1:
        head += f" (стр. {page} из {pages})"
    lines = [head]
    lines.extend(_format_person(start + i, p) for i, p in enumerate(shown, start=1))
    return "\n".join(lines), page, pages


def fit_message(text: str) -> str:
    """Не больше MESSAGE_LIMIT: срезаем хвостовые строки целиком, без порванных тегов."""
    if len(text) <= MESSAGE_LIMIT:
        return text
    tail = "\n… не поместилось в сообщение — откройте карточку в реестре."
    lines = text.split("\n")
    while lines and len("\n".join(lines)) + len(tail) > MESSAGE_LIMIT:
        lines.pop()
    return "\n".join(lines) + tail


def _safe_people(card, page: int) -> tuple[str, int, int]:
    try:
        return format_people(card, page)
    except Exception:
        log.warning("специалисты карточки не разобрались", exc_info=True)
        return "👥 Специалисты НРС: список не разобрался. Откройте карточку в реестре.", 1, 1


def _page_buttons(registry: str, member_id: int, page: int, pages: int) -> list[PickButton]:
    buttons = []
    if page > 1:
        buttons.append(PickButton(f"◀ Специалисты, стр. {page - 1}", page_payload(registry, member_id, page - 1)))
    if page < pages:
        buttons.append(PickButton(f"Специалисты, стр. {page + 1} ▶", page_payload(registry, member_id, page + 1)))
    return buttons


def load_member_view(payload: str, *, client: RegistryClient | None = None) -> SearchResult:
    """Карточка с первой страницей специалистов, либо следующая страница.

    payload — nat:реестр:id (карточка) или natp:реестр:id:страница.
    Сбой API не пробрасывается.
    """
    try:
        if (payload or "").startswith("natp:"):
            return _load_people_page(payload, client=client)
        return _load_member_view(payload, client=client)
    except Exception:
        log.warning("карточка единого реестра упала", exc_info=True)
        return SearchResult(CARD_FAIL)


def load_member_text(payload: str, *, client: RegistryClient | None = None) -> str:
    """Карточка по inline-кнопке (только текст). Сбой API не пробрасывается."""
    return load_member_view(payload, client=client).text


def _load_people_page(payload: str, *, client: RegistryClient | None) -> SearchResult:
    parsed = parse_page_callback(payload)
    if not parsed:
        return SearchResult("Кнопка устарела. Повторите поиск.")
    registry, member_id, page = parsed
    raw, exc = _post(client or make_client(), info_url(registry, member_id), {})
    data = raw.get("data") if isinstance(raw, dict) else None
    cached = cached_hit(registry, member_id)
    if exc or not isinstance(data, dict):
        if cached and cached.name:
            return SearchResult(f"🏛 <b>{_h(cached.name)}</b>\n{PEOPLE_FAIL}")
        return SearchResult(PEOPLE_FAIL)
    name = cached.name if cached else _org_name(data)
    text, page, pages = _safe_people(data, page)
    if name:
        text = f"🏛 <b>{_h(name)}</b>\n{text}"
    return SearchResult(fit_message(text), _page_buttons(registry, member_id, page, pages))


def _load_member_view(payload: str, *, client: RegistryClient | None) -> SearchResult:
    parsed = parse_callback(payload)
    if not parsed:
        return SearchResult("Кнопка устарела. Повторите поиск.")
    registry, member_id = parsed
    own_client = client or make_client()
    cached = cached_hit(registry, member_id)
    raw, exc = _post(own_client, info_url(registry, member_id), {})
    data = raw.get("data") if isinstance(raw, dict) else None
    if exc or not isinstance(data, dict):
        if cached:
            card = format_member_card(
                replace(
                    cached,
                    card_note="Подробности карточки (право и уровни) сейчас не загрузились.",
                )
            )
            return SearchResult(f"{card}\n\n{PEOPLE_FAIL}")
        return SearchResult(CARD_FAIL)
    hit = apply_card(cached, data) if cached else hit_from_card(registry, member_id, data)
    hit = _fill_sro_reg(own_client, hit)
    remember(hit)
    people, page, pages = _safe_people(data, 1)
    text = fit_message(f"{format_member_card(hit)}\n\n{people}")
    return SearchResult(text, _page_buttons(registry, member_id, page, pages))


# --- режим ввода, отдельно для Telegram и MAX ---

_plat = (os.getenv("BOT_PLATFORM") or "tg").strip().lower()
_plat = "max" if _plat == "max" else "tg"
_MODE_FILE = str(Path(__file__).resolve().parent / f"national_mode_{_plat}.json")
_mode_lock = threading.Lock()
_await_national: set[int] = set()


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
            snap = sorted(_await_national)
            tmp = _MODE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(snap, fh)
            os.replace(tmp, _MODE_FILE)
        except OSError:
            pass


_await_national = _load_mode_users()


def enter_national_mode(chat_id: int) -> None:
    try:
        _await_national.add(int(chat_id))
    except (TypeError, ValueError):
        return
    _save_mode_users()


def exit_national_mode(chat_id: int) -> None:
    try:
        _await_national.discard(int(chat_id))
    except (TypeError, ValueError):
        return
    _save_mode_users()


def is_national_mode(chat_id: int) -> bool:
    try:
        return int(chat_id) in _await_national
    except (TypeError, ValueError):
        return False
