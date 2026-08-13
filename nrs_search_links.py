"""Ссылки на открытые реестры НРС (НОСТРОЙ / НОПРИЗ) с подставленным фильтром.

Бот карточки не кэширует — собирает URL на официальные сайты.
Для НОПРИЗ по ФИО — короткий запрос к их API, чтобы подставить номер в ссылку.
"""

from __future__ import annotations

import json
import os
import re
import time
from urllib.parse import urlencode

import requests

NOSTROY_NRS = "https://nrs.nostroy.ru/"
NOPRIZ_NRS = "https://nrs.nopriz.ru/"
NOPRIZ_API_LIST = "https://nrs.nopriz.ru/api/specialist/list"
_MODE_FILE = os.path.join(os.path.dirname(__file__), "nrs_link_mode.json")

# False = только BOT_ADMIN_IDS + ОГПС (пилот). True = кнопка всем пользователям.
NRS_LINK_FOR_ALL = True

NRS_LINK_BUTTON = "👤 Проверить в НРС" if NRS_LINK_FOR_ALL else "👤 НРС ссылка (пилот)"
NRS_LINK_BACK = "⬅️ Назад в меню"

_await_nrs_query: set[int] = set()
# антисpam: chat_id -> last API time
_nopriz_last_call: dict[int, float] = {}
_NOPRIZ_COOLDOWN_SEC = 2.0


def _load_nrs_mode_users() -> set[int]:
    try:
        with open(_MODE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return {int(x) for x in data}
    except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return set()


def _save_nrs_mode_users() -> None:
    try:
        with open(_MODE_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(_await_nrs_query), f)
    except OSError:
        pass


_await_nrs_query = _load_nrs_mode_users()

# Только префикс С: латинская C → кириллическая С. Середина номера (BY) — лatin как на сайте!
_LATIN_PREFIX_C = str.maketrans({"C": "С", "c": "с"})

# С-BY-260757; С-55-267917; BY-260757; ПИ-083721
_REG_TOKEN_RE = re.compile(
    r"(?<![А-ЯA-Za-z0-9])"
    r"("
    r"[СC]-[A-Za-z]{2,3}-\d{4,8}"
    r"|"
    r"[А-Я]-\d{1,2}-\d{4,8}"
    r"|"
    r"[A-Za-z]{2,3}-\d{4,8}"
    r"|"
    r"[А-Я]{1,3}-\d{3,8}"
    r")"
    r"(?![А-ЯA-Za-z0-9])",
    re.IGNORECASE,
)


def _prefix_s(ch: str) -> str:
    ch = (ch or "").strip()
    if ch.upper() in ("C", "С"):
        return "С"
    return ch.upper()

def can_use_nrs_link_pilot(chat_id: int, sro_id: str | None) -> bool:
    if NRS_LINK_FOR_ALL:
        return True
    try:
        from users_log import is_bot_admin
    except Exception:
        return False
    if not is_bot_admin(chat_id):
        return False
    return (sro_id or "").strip().upper() == "OGPS"


def _is_nostroy_number(number: str) -> bool:
    n = _nostroy_registration(number)
    if not n:
        return False
    return n.startswith("С-") and not _is_nopriz_number(n)


def _is_nopriz_number(number: str) -> bool:
    n = normalize_nrs_number(number)
    # Кириллица П/ПИ/И и латинские P/PI (если ввели с англ. раскладки)
    if re.match(r"^(П|ПИ|И)-\d", n, re.I):
        return True
    if re.match(r"^(P|PI|I)-\d", n, re.I):
        return True
    return False


def _nostroy_registration(number: str) -> str:
    """Номер для nrs.nostroy.ru: BY-260757 → С-BY-260757 (BY лatin!)."""
    n = normalize_nrs_number(number)
    if not n:
        return ""
    if _is_nopriz_number(n):
        return n
    if re.match(r"^С-", n):
        return n
    if re.match(r"^[A-Z]{2,3}-\d{4,8}$", n):
        return f"С-{n}"
    return n


def normalize_nrs_number(raw: str) -> str:
    q = re.sub(r"\s+", "", (raw or "").strip())
    if not q:
        return ""
    parts = [p for p in q.split("-") if p]
    # С-BY-260757 / C-by-260757 — середина Latin BY
    if len(parts) == 3 and parts[2].isdigit() and not parts[1].isdigit():
        mid = parts[1].upper() if parts[1].isascii() else parts[1].upper()
        return f"{_prefix_s(parts[0])}-{mid}-{parts[2]}"
    # С-55-267917
    if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
        return f"{_prefix_s(parts[0])}-{parts[1]}-{parts[2]}"
    # BY-260757 / ПИ-083721 / P-122864 (лат. P → П)
    if len(parts) == 2 and parts[1].isdigit():
        if parts[0].isascii() and re.match(r"^[A-Za-z]+$", parts[0]):
            head = parts[0].upper()
            head = {"P": "П", "PI": "ПИ", "I": "И"}.get(head, head)
        else:
            head = parts[0].translate(_LATIN_PREFIX_C).upper()
        return f"{head}-{parts[1]}"
    m = re.match(r"^([A-Za-zА-Я]{1,3})(\d{3,8})$", q, re.I)
    if m:
        h = m.group(1).upper() if m.group(1).isascii() else m.group(1).upper()
        if m.group(1).isascii():
            h = {"P": "П", "PI": "ПИ", "I": "И"}.get(h, h)
        return f"{h}-{m.group(2)}"
    return q.upper()


def enter_nrs_link_mode(chat_id: int) -> None:
    _await_nrs_query.add(chat_id)
    _save_nrs_mode_users()


def exit_nrs_link_mode(chat_id: int) -> None:
    _await_nrs_query.discard(chat_id)
    _save_nrs_mode_users()


def is_nrs_link_mode(chat_id: int) -> bool:
    return chat_id in _await_nrs_query


def looks_like_nrs_person_query(text: str) -> bool:
    """Полное ФИО — для НРС, не для телефонного справочника."""
    raw = (text or "").strip()
    if not raw or "?" in raw:
        return False
    lower = raw.lower().replace("ё", "е")
    if any(re.search(rf"\b{re.escape(hint)}\b", lower) for hint in (
        "телефон", "тел", "доб", "добавочн", "email", "почта", "e-mail", "mail",
        "контакт", "найти", "номер", "звонок", "сотрудник", "работник",
    )):
        return False
    if not re.fullmatch(r"[а-яёА-ЯЁ.\s\-]+", raw):
        return False
    words = [w for w in re.split(r"\s+", raw) if w]
    if len(words) == 3:
        return all(re.match(r"^[А-ЯЁ][а-яё\-]{1,}$", w) for w in words)
    if len(words) == 2:
        return bool(
            re.match(r"^[А-ЯЁ][а-яё\-]{2,}$", words[0])
            and re.match(r"^[А-ЯЁ][а-яё]{2,}$", words[1])
        )
    return False


def parse_nrs_query(text: str) -> dict:
    """Вытащить номер (если есть) и оставшееся ФИО из одной строки."""
    raw = (text or "").strip()
    if not raw:
        return {"fio": "", "number": ""}

    numbers = [normalize_nrs_number(m.group(1)) for m in _REG_TOKEN_RE.finditer(raw)]
    fio = _REG_TOKEN_RE.sub(" ", raw)
    fio = re.sub(r"\s+", " ", fio).strip(" ,.;")
    number = numbers[0] if numbers else ""

    # Только номер без ФИО
    if number and not fio:
        return {"fio": "", "number": number}
    # Только ФИО
    if fio and not number:
        return {"fio": fio, "number": ""}
    return {"fio": fio, "number": number}


def _nostroy_url(*, fio: str = "", number: str = "") -> str:
    reg = _nostroy_registration(number) if number else ""
    if reg:
        qs = urlencode({"s.registrationNumber": reg}, encoding="utf-8")
    else:
        qs = urlencode({"s.fio": fio}, encoding="utf-8")
    return f"{NOSTROY_NRS}?{qs}"

def _nopriz_url(*, number: str = "", fio: str = "") -> str:
    # У НОПРИЗ в URL надёжно работает номер; ФИО в query SPA часто игнорирует.
    if number:
        qs = urlencode({"s.registrationNumber": number}, encoding="utf-8")
        return f"{NOPRIZ_NRS}?{qs}"
    if fio:
        qs = urlencode({"s.fio": fio}, encoding="utf-8")
        return f"{NOPRIZ_NRS}?{qs}"
    return NOPRIZ_NRS


# Короткие подписи видов работ НОПРИЗ (код API → текст в боте)
_NOPRIZ_WORK_SHORT = {
    "project": "Проектирование",
    "research": "Изыскания",
}
_NOPRIZ_WORK_ORDER = ("project", "research")


def _parse_nopriz_work_types(raw) -> list[dict]:
    """Из ответа API: [{code, short, status, cert_date}, ...]."""
    if not isinstance(raw, dict):
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for code in _NOPRIZ_WORK_ORDER:
        item = raw.get(code)
        if not isinstance(item, dict):
            continue
        status = (item.get("statusTitle") or item.get("statusCode") or "").strip()
        if not status:
            continue
        short = _NOPRIZ_WORK_SHORT.get(code) or (item.get("title") or code).strip()
        cert = (item.get("certIssuedDate") or "").strip()
        out.append({"code": code, "short": short, "status": status, "cert_date": cert})
        seen.add(code)
    for code, item in raw.items():
        if code in seen or not isinstance(item, dict):
            continue
        status = (item.get("statusTitle") or item.get("statusCode") or "").strip()
        if not status:
            continue
        short = _NOPRIZ_WORK_SHORT.get(code) or (item.get("title") or str(code)).strip()
        cert = (item.get("certIssuedDate") or "").strip()
        out.append({"code": str(code), "short": short, "status": status, "cert_date": cert})
    return out


def _format_nopriz_work_lines(work_types: list[dict]) -> list[str]:
    """Короткие строки: • Проектирование — действует (НОК 02.11.2023)."""
    lines: list[str] = []
    for wt in work_types:
        status = (wt.get("status") or "").strip()
        if not status:
            continue
        status_l = status[:1].lower() + status[1:] if status else status
        short = wt.get("short") or wt.get("code") or "вид работ"
        cert = (wt.get("cert_date") or "").strip()
        if cert:
            lines.append(f"• {short} — {status_l} (НОК {cert})")
        else:
            lines.append(f"• {short} — {status_l}")
    return lines


def _nopriz_api(
    filters: dict,
    *,
    limit: int = 5,
    chat_id: int | None = None,
    sort_fio: str = "",
) -> tuple[list[dict], int | None]:
    """Запрос к API НОПРИЗ → (строки, всего в реестре или None)."""
    if chat_id is not None:
        now = time.monotonic()
        last = _nopriz_last_call.get(chat_id, 0.0)
        if now - last < _NOPRIZ_COOLDOWN_SEC:
            return [], None
        _nopriz_last_call[chat_id] = now
    try:
        r = requests.post(
            NOPRIZ_API_LIST,
            json={"filters": filters, "page": 1},
            headers={
                "User-Agent": "SRO-Bot/1.0 (+nrs link)",
                "Accept": "application/json",
                "Content-Type": "application/json;charset=UTF-8",
                "Referer": NOPRIZ_NRS,
                "Origin": "https://nrs.nopriz.ru",
            },
            timeout=10,
        )
        r.raise_for_status()
        payload = r.json().get("data") or {}
        rows = payload.get("data") or []
        total_raw = payload.get("count")
        try:
            total = int(total_raw) if total_raw is not None else None
        except (TypeError, ValueError):
            total = None
    except Exception:
        return [], None
    out = []
    fio_n = re.sub(r"\s+", " ", sort_fio).strip().lower()
    for row in rows:
        reg = (row.get("registrationNumber") or "").strip()
        name = (row.get("fio") or "").strip()
        if not reg or not name:
            continue
        out.append(
            {
                "registrationNumber": reg,
                "fio": name,
                "work_types": _parse_nopriz_work_types(row.get("workTypes")),
            }
        )
        if len(out) >= limit:
            break
    if fio_n:
        out.sort(key=lambda x: 0 if x["fio"].lower() == fio_n else 1)
    return out, total


def _nopriz_lookup_by_fio(fio: str, *, limit: int = 5, chat_id: int | None = None) -> tuple[list[dict], int | None]:
    return _nopriz_api({"fio": fio}, limit=limit, chat_id=chat_id, sort_fio=fio)


def _nopriz_lookup_by_number(
    number: str, *, chat_id: int | None = None
) -> tuple[list[dict], int | None]:
    n = normalize_nrs_number(number)
    if not n or not _is_nopriz_number(n):
        return [], None
    return _nopriz_api({"registrationNumber": n}, limit=1, chat_id=chat_id)

def _a(url: str, title: str) -> str:
    # Короткий текст ссылки; длинный URL только в href
    safe = url.replace('"', "%22")
    return f'<a href="{safe}">{title}</a>'


def format_nrs_link_intro() -> str:
    title = "👤 <b>Проверка в НРС</b>" if NRS_LINK_FOR_ALL else "👤 <b>НРС — быстрая ссылка (пилот)</b>"
    return (
        f"{title}\n\n"
        "Введите <b>ФИО</b> и/или <b>номер</b> специалиста.\n"
        "Бот даст ссылки на официальные реестры НОСТРОЙ и НОПРИЗ.\n"
        "По НОПРИЗ при точном попадании — кратко вид работ, статус и дата НОК.\n\n"
        "Примеры:\n"
        "• <code>Иванов Иван Иванович</code>\n"
        "• <code>C-by-260757</code> или <code>BY-260757</code> (НОСТРОЙ, BY лatin)\n"
        "• <code>Иванов Петр Петрович П-000000</code> (НОПРИЗ)\n"
        "• <code>ПИ-000000</code> (только номер)\n\n"
        "<i>Официальные данные — на сайтах реестров; в боте — краткая выдержка и ссылка.</i>"
    )


def format_nrs_link_reply(query: str, chat_id: int | None = None) -> str:
    parsed = parse_nrs_query(query)
    fio = parsed["fio"]
    number = parsed["number"]
    if not fio and not number:
        return "⚠️ Введите ФИО или номер НРС (например <code>С-55-267917</code> или <code>ПИ-083721</code>)."

    is_nostroy = bool(number and _is_nostroy_number(number))
    is_nopriz = bool(number and _is_nopriz_number(number))

    # НОПРИЗ: по номеру П-/ПИ- или по ФИО (если не ввели С-)
    nopriz_hit: dict | None = None
    nopriz_matches: list[dict] = []
    nopriz_total: int | None = None
    if is_nopriz:
        nopriz_matches, nopriz_total = _nopriz_lookup_by_number(number, chat_id=chat_id)
        if nopriz_matches:
            nopriz_hit = nopriz_matches[0]
            if not fio:
                fio = nopriz_hit["fio"]
    elif not is_nostroy and fio and not number:
        nopriz_matches, nopriz_total = _nopriz_lookup_by_fio(fio, chat_id=chat_id)
        if len(nopriz_matches) == 1:
            nopriz_hit = nopriz_matches[0]

    # Закрываем чужой реестр только по ТИПУ введённого номера:
    # С- → НОПРИЗ закрыт; П-/ПИ- → НОСТРОЙ закрыт.
    # По ФИО оба реестра открыты (человек может быть и там, и там).
    block_nostroy = is_nopriz
    block_nopriz = is_nostroy

    lines: list[str] = []
    if number and fio:
        if is_nostroy:
            show_num = _nostroy_registration(number) or number
        elif nopriz_hit:
            show_num = nopriz_hit["registrationNumber"]
        else:
            show_num = number
        lines.append(f"🔗 <b>{fio}</b> · номер <code>{show_num}</code>")
    elif number:
        nostroy_num = _nostroy_registration(number)
        show = nostroy_num or number
        if nostroy_num and nostroy_num.upper() != number.upper() and is_nostroy:
            lines.append(
                f"🔗 Номер для НОСТРОЙ: <code>{show}</code>\n"
                f"(ввели: <code>{number}</code>)"
            )
        else:
            lines.append(f"🔗 Поиск по номеру: <code>{show}</code>")
            if is_nostroy:
                lines.append(
                    "<i>ФИО — только на сайте НОСТРОЙ после перехода по ссылке.</i>"
                )
    else:
        lines.append(f"🔗 Поиск по ФИО: <b>{fio}</b>")

    # НОСТРОЙ
    lines.append("")
    lines.append("🏗 <b>НОСТРОЙ</b> (строители)")
    if block_nostroy:
        reg = (nopriz_hit or {}).get("registrationNumber") or number or "П-/ПИ-…"
        lines.append(
            f"<i>⛔ Номер НОПРИЗ (<code>{reg}</code>) — другой реестр. "
            "Поиск строителей по нему закрыт.</i>"
        )
    else:
        nostroy = _nostroy_url(fio=fio, number=number)
        lines.append(_a(nostroy, "➡️ Открыть в НОСТРОЙ"))

    # НОПРИЗ
    lines.append("")
    lines.append("📐 <b>НОПРИЗ</b> (проект / изыскания)")
    if block_nopriz:
        show = _nostroy_registration(number) or number
        lines.append(
            f"<i>⛔ Номер строителя (<code>{show}</code>) — другой реестр. "
            "Поиск в НОПРИЗ по нему закрыт.</i>"
        )
    elif number and is_nopriz:
        reg = (nopriz_hit or {}).get("registrationNumber") or number
        if nopriz_hit:
            lines.append(
                f"{nopriz_hit['fio']} · <code>{reg}</code>\n"
                + _a(_nopriz_url(number=reg), "➡️ Открыть в НОПРИЗ")
            )
            lines.extend(_format_nopriz_work_lines(nopriz_hit.get("work_types") or []))
        else:
            lines.append(_a(_nopriz_url(number=number), "➡️ Открыть в НОПРИЗ"))
            lines.append("<i>Карточку на сайте не нашли — проверьте номер.</i>")
    elif nopriz_hit:
        m = nopriz_hit
        lines.append(
            f"{m['fio']} · <code>{m['registrationNumber']}</code>\n"
            + _a(_nopriz_url(number=m["registrationNumber"]), "➡️ Открыть в НОПРИЗ")
        )
        lines.extend(_format_nopriz_work_lines(m.get("work_types") or []))
    elif number:
        # Не С- и не П- (редкий формат) — просто ссылка
        lines.append(_a(_nopriz_url(number=number, fio=fio), "➡️ Открыть в НОПРИЗ"))
    else:
        if not nopriz_matches:
            lines.append(_a(_nopriz_url(fio=fio), "➡️ Открыть в НОПРИЗ"))
            lines.append("<i>Если список пустой — уточните номер (П-, ПИ-…).</i>")
        else:
            shown = len(nopriz_matches)
            if nopriz_total is not None and nopriz_total > shown:
                lines.append(
                    f"Найдено в НОПРИЗ: <b>{nopriz_total}</b> (показаны первые {shown})"
                )
            else:
                lines.append(f"Найдено в НОПРИЗ: <b>{shown}</b>")
            for m in nopriz_matches[:5]:
                lines.append(
                    f"• {m['fio']} · <code>{m['registrationNumber']}</code> — "
                    + _a(_nopriz_url(number=m["registrationNumber"]), "открыть")
                )
            lines.append(
                "<i>Уточните номер (П-, ПИ-…) — тогда покажем вид работ и дату НОК.</i>"
            )
    lines.append("")
    lines.append(
        "<i>Официальные реестры: nrs.nostroy.ru · nrs.nopriz.ru</i>"
    )
    return "\n".join(lines)
