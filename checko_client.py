"""Клиент Checko API (ЕГРЮЛ и доп. сведения) для контролёров СРО-бота."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import requests

API_BASE = "https://api.checko.ru/v2"
CACHE_TTL_SEC = 24 * 3600
DAILY_LIMIT = 100  # тариф Лайт
CHECKO_SITE = "https://checko.ru/company"

# code -> (кнопка, api_method) — короткий набор для контролёров
SECTIONS: list[tuple[str, str, str]] = [
    ("general", "📋 Общая информация", "company"),
    ("requisites", "📄 Реквизиты", "company"),
    ("contacts", "📞 Контакты", "company"),
    ("managers", "👤 Руководитель", "company"),
    ("reliability", "🔥 Надёжность", "company"),
    ("inspections", "📅 Проверки и КНМ", "inspections"),
    ("legal", "⚖️ Арбитражные дела", "legal-cases"),
    ("fssp", "💵 ФССП", "enforcements"),
]


def _api_key() -> str:
    try:
        from config_keys import CHECKO_API_KEY

        return (CHECKO_API_KEY or "").strip()
    except Exception:
        return ""


def _data_dir() -> Path:
    try:
        from config_keys import SRO_FILES_DIR

        base = Path(SRO_FILES_DIR)
    except Exception:
        base = Path(__file__).resolve().parent
    d = base / "checko_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_path(method: str, inn: str) -> Path:
    safe = "".join(c for c in f"{method}_{inn}" if c.isalnum() or c in ("_", "-"))
    return _data_dir() / f"{safe}.json"


def _quota_path() -> Path:
    return _data_dir() / "daily_quota.json"


def _load_quota() -> dict[str, Any]:
    p = _quota_path()
    if not p.exists():
        return {"day": "", "count": 0}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"day": "", "count": 0}


def _save_quota(data: dict[str, Any]) -> None:
    _quota_path().write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def requests_used_today() -> int:
    q = _load_quota()
    today = time.strftime("%Y-%m-%d", time.gmtime())
    if q.get("day") != today:
        return 0
    return int(q.get("count") or 0)


def _bump_quota() -> bool:
    today = time.strftime("%Y-%m-%d", time.gmtime())
    q = _load_quota()
    if q.get("day") != today:
        q = {"day": today, "count": 0}
    if int(q.get("count") or 0) >= DAILY_LIMIT:
        return False
    q["count"] = int(q.get("count") or 0) + 1
    _save_quota(q)
    return True


def _read_cache(method: str, inn: str) -> dict | None:
    p = _cache_path(method, inn)
    if not p.exists():
        return None
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
        if time.time() - float(payload.get("ts") or 0) > CACHE_TTL_SEC:
            return None
        return payload.get("data")
    except Exception:
        return None


def _write_cache(method: str, inn: str, data: dict) -> None:
    p = _cache_path(method, inn)
    p.write_text(
        json.dumps({"ts": time.time(), "data": data}, ensure_ascii=False),
        encoding="utf-8",
    )


def checko_configured() -> bool:
    return bool(_api_key())


def fetch_method(method: str, inn: str, extra: dict | None = None) -> tuple[dict | None, str | None]:
    inn = (inn or "").strip()
    if not inn:
        return None, "Не указан ИНН."
    if not checko_configured():
        return None, "Checko не настроен (нет CHECKO_API_KEY)."

    cached = _read_cache(method, inn)
    if cached is not None:
        return cached, None

    if not _bump_quota():
        return None, (
            f"⚠️ Лимит Checko на сегодня ({DAILY_LIMIT} запросов) исчерпан.\n"
            "Завтра сбросится; кэш за сутки ещё работает."
        )

    payload = {"key": _api_key(), "inn": inn}
    if extra:
        payload.update(extra)
    url = f"{API_BASE}/{method}"
    try:
        r = requests.post(url, json=payload, timeout=30)
        if r.status_code in (402, 429):
            return None, "⚠️ Лимит или оплата Checko. Проверьте тариф в личном кабинете."
        r.raise_for_status()
        body = r.json()
    except requests.HTTPError as exc:
        logging.warning("Checko HTTP %s: %s", method, exc)
        code = getattr(exc.response, "status_code", "?")
        return None, f"⚠️ Checko вернул ошибку HTTP ({code})."
    except Exception as exc:
        logging.warning("Checko request failed %s: %s", method, exc)
        return None, "⚠️ Не удалось связаться с Checko. Попробуйте позже."

    if isinstance(body, dict) and body.get("error"):
        return None, f"⚠️ Checko: {body.get('error')}"

    _write_cache(method, inn, body)
    return body, None


def company_data(inn: str) -> tuple[dict | None, str | None]:
    body, err = fetch_method("company", inn)
    if err:
        return None, err
    if not body:
        return None, "Пустой ответ Checko."
    data = body.get("data") if isinstance(body, dict) else None
    if data is None and isinstance(body, dict):
        data = body
    return data if isinstance(data, dict) else None, None


def site_url(inn: str) -> str:
    return f"{CHECKO_SITE}/{inn}"


def _esc(s: Any) -> str:
    t = str(s if s is not None else "").strip()
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _format_ru_date(raw: Any) -> str:
    s = str(raw or "").strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        # 1996-03-04 → 04.03.1996
        return f"{s[8:10]}.{s[5:7]}.{s[0:4]}"
    return s


def _get(d: dict | None, *keys, default="—"):
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    if cur is None or cur == "":
        return default
    return cur


def format_section(section: str, inn: str) -> str:
    meta = next((s for s in SECTIONS if s[0] == section), None)
    title = meta[1] if meta else section
    method = meta[2] if meta else "company"
    footer = (
        f"\n\n<i>Источник: Checko (сторонние данные). Сверяйте с ЕГРЮЛ.</i>\n"
        f'🌐 <a href="{site_url(inn)}">Карточка на checko.ru</a>\n'
        f"<i>Запросов сегодня: {requests_used_today()}/{DAILY_LIMIT}</i>"
    )

    if section == "finances":
        body, err = fetch_method("finances", inn)
        if err:
            return err
        data = (body or {}).get("data") if isinstance(body, dict) else body
        lines = [f"<b>{title}</b>", f"ИНН <code>{_esc(inn)}</code>", ""]
        if isinstance(data, dict):
            for k, v in list(data.items())[:12]:
                if isinstance(v, (str, int, float)):
                    lines.append(f"• {_esc(k)}: {_esc(v)}")
                elif isinstance(v, dict):
                    lines.append(f"• <b>{_esc(k)}</b>")
                    for kk, vv in list(v.items())[:6]:
                        if isinstance(vv, (str, int, float)):
                            lines.append(f"  — {_esc(kk)}: {_esc(vv)}")
        else:
            lines.append("Нет кратких данных в ответе — откройте на сайте.")
        return "\n".join(lines) + footer

    if section == "timeline":
        body, err = fetch_method("timeline", inn)
        if err:
            return err
        data = (body or {}).get("data") if isinstance(body, dict) else body
        items = data if isinstance(data, list) else []
        if isinstance(data, dict):
            items = data.get("items") or data.get("list") or data.get("Записи") or []
        lines = [f"<b>{title}</b>", f"ИНН <code>{_esc(inn)}</code>", ""]
        if not items:
            lines.append("Записей не найдено.")
        else:
            # как на сайте — свежие сверху
            shown = list(reversed(items))[:10]
            for item in shown:
                if not isinstance(item, dict):
                    lines.append(f"• {_esc(item)}")
                    continue
                date_raw = item.get("Дата") or item.get("date") or ""
                event = (
                    item.get("Событие")
                    or item.get("Наим")
                    or item.get("name")
                    or item.get("Текст")
                    or ""
                )
                date_s = _format_ru_date(date_raw)
                if date_s and event:
                    lines.append(f"<b>{_esc(date_s)}</b>\n{_esc(event)}")
                    lines.append("")
                elif event:
                    lines.append(f"• {_esc(event)}")
                elif date_s:
                    lines.append(f"• {_esc(date_s)}")
            if len(items) > 10:
                lines.append(
                    f'<i>…ещё {len(items) - 10}. '
                    f'<a href="{site_url(inn)}">Полная история на checko.ru</a></i>'
                )
        return "\n".join(lines).rstrip() + footer

    if section in ("contracts", "inspections", "legal", "fssp"):
        body, err = fetch_method(method, inn)
        if err:
            return err
        data = (body or {}).get("data") if isinstance(body, dict) else body
        lines = [f"<b>{title}</b>", f"ИНН <code>{_esc(inn)}</code>", ""]
        items: Any = data
        if isinstance(data, dict):
            items = data.get("items") or data.get("list") or data.get("Записи") or data
        if isinstance(items, list):
            if not items:
                lines.append("Записей не найдено.")
            for i, item in enumerate(items[:8]):
                if isinstance(item, dict):
                    label = (
                        item.get("Наим")
                        or item.get("name")
                        or item.get("Номер")
                        or item.get("number")
                        or item.get("Событие")
                        or item.get("Дата")
                        or item.get("date")
                        or f"запись {i + 1}"
                    )
                    extra = item.get("Событие") if label == item.get("Дата") else None
                    if extra:
                        lines.append(f"• <b>{_esc(label)}</b> — {_esc(extra)}")
                    else:
                        lines.append(f"• {_esc(label)}")
                else:
                    lines.append(f"• {_esc(item)}")
            if len(items) > 8:
                lines.append(f"<i>…ещё {len(items) - 8}, полный список на сайте</i>")
        elif isinstance(items, dict):
            for k, v in list(items.items())[:15]:
                if isinstance(v, (str, int, float)):
                    lines.append(f"• {_esc(k)}: {_esc(v)}")
        else:
            lines.append("Нет данных в кратком виде — откройте на сайте.")
        return "\n".join(lines) + footer

    data, err = company_data(inn)
    if err:
        return err
    if not data:
        return "Организация не найдена в Checko." + footer

    name = _get(data, "НаимСокр", default=_get(data, "НаимПолн"))
    lines = [f"<b>{title}</b>", f"{_esc(name)}", f"ИНН <code>{_esc(inn)}</code>", ""]

    if section == "general":
        status = _get(data, "Статус", "Наим")
        addr = _get(data, "ЮрАдрес", "Наим", default=_get(data, "ЮрАдрес", "АдресРФ"))
        lines.extend(
            [
                f"ОГРН: <code>{_esc(_get(data, 'ОГРН'))}</code>",
                f"КПП: {_esc(_get(data, 'КПП'))}",
                f"Статус: {_esc(status)}",
                f"Дата регистрации: {_esc(_get(data, 'ДатаРег'))}",
                f"Адрес: {_esc(addr)}",
            ]
        )
    elif section == "reliability":
        risks = data.get("ФакторыРиска") or data.get("Риски") or []
        if isinstance(risks, list) and risks:
            for r in risks[:15]:
                if isinstance(r, dict):
                    lines.append(f"• {_esc(r.get('Наим') or r.get('name') or r)}")
                else:
                    lines.append(f"• {_esc(r)}")
        else:
            lines.append("Явных факторов риска в кратком ответе нет (или блок пуст).")
            lines.append("Сверьте раздел «Надёжность» на сайте Checko.")
    elif section == "requisites":
        lines.extend(
            [
                f"ОГРН: <code>{_esc(_get(data, 'ОГРН'))}</code>",
                f"ИНН: <code>{_esc(_get(data, 'ИНН', default=inn))}</code>",
                f"КПП: {_esc(_get(data, 'КПП'))}",
                f"ОКПО: {_esc(_get(data, 'ОКПО'))}",
                f"Полное наименование: {_esc(_get(data, 'НаимПолн'))}",
            ]
        )
    elif section == "contacts":
        contacts = data.get("Контакты") or {}
        phones = contacts.get("Тел") or contacts.get("phones") or []
        emails = contacts.get("Емэйл") or contacts.get("Email") or contacts.get("emails") or []
        sites = contacts.get("ВебСайт") or contacts.get("sites") or []
        if isinstance(phones, str):
            phones = [phones]
        if isinstance(emails, str):
            emails = [emails]
        if isinstance(sites, str):
            sites = [sites]
        if phones:
            lines.append("Телефоны: " + ", ".join(_esc(p) for p in phones[:8]))
        if emails:
            lines.append("Email: " + ", ".join(_esc(e) for e in emails[:5]))
        if sites:
            lines.append("Сайт: " + ", ".join(_esc(s) for s in sites[:5]))
        if len(lines) <= 4:
            lines.append("Контактов в ответе нет или они скрыты.")
    elif section == "okved":
        okved = data.get("ОКВЭД") or {}
        main = okved.get("Осн") or okved.get("main")
        if isinstance(main, dict):
            lines.append(f"Основной: {_esc(main.get('Код'))} — {_esc(main.get('Наим'))}")
        extras = okved.get("Доп") or okved.get("list") or []
        if isinstance(extras, list):
            for item in extras[:12]:
                if isinstance(item, dict):
                    lines.append(f"• {_esc(item.get('Код'))} — {_esc(item.get('Наим'))}")
        if len(lines) <= 4:
            lines.append("ОКВЭД не найден в ответе.")
    elif section == "taxes":
        taxes = data.get("Налоги") or {}
        if isinstance(taxes, dict) and taxes:
            for k, v in list(taxes.items())[:15]:
                if isinstance(v, (str, int, float)):
                    lines.append(f"• {_esc(k)}: {_esc(v)}")
                elif isinstance(v, dict):
                    lines.append(
                        f"• <b>{_esc(k)}</b>: {_esc(v.get('Наим') or v.get('Сумма') or '…')}"
                    )
        else:
            lines.append("Блок налогов пуст в кратком ответе — смотрите на сайте.")
    elif section == "managers":
        managers = data.get("Руковод") or data.get("Руководители") or []
        if isinstance(managers, dict):
            managers = [managers]
        if not managers:
            lines.append("Руководитель не указан.")
        for m in managers[:8]:
            if isinstance(m, dict):
                fio = m.get("ФИО") or m.get("name") or "—"
                post = m.get("Должн") or m.get("post") or ""
                lines.append(f"• {_esc(fio)}" + (f" — {_esc(post)}" if post else ""))
    elif section == "founders":
        founders = data.get("Учред") or data.get("Учредители") or []
        if isinstance(founders, dict):
            founders = [founders]
        if not founders:
            lines.append("Учредители не указаны.")
        for f in founders[:10]:
            if isinstance(f, dict):
                name_f = f.get("Наим") or f.get("ФИО") or f.get("name") or "—"
                share = f.get("Доля") or f.get("share") or ""
                lines.append(f"• {_esc(name_f)}" + (f" ({_esc(share)})" if share else ""))
    elif section == "links":
        links = data.get("Связ") or data.get("Связи") or []
        if isinstance(links, list) and links:
            for item in links[:12]:
                if isinstance(item, dict):
                    lines.append(f"• {_esc(item.get('Наим') or item.get('name') or item)}")
                else:
                    lines.append(f"• {_esc(item)}")
        else:
            lines.append("Связей в кратком ответе нет.")
    elif section == "licenses":
        lic = data.get("Лицензии") or []
        if isinstance(lic, list) and lic:
            for item in lic[:10]:
                if isinstance(item, dict):
                    lines.append(f"• {_esc(item.get('Наим') or item.get('Номер') or item)}")
                else:
                    lines.append(f"• {_esc(item)}")
        else:
            lines.append("Лицензии не найдены в ответе.")
    elif section == "trademarks":
        tm = data.get("ТоварныеЗнаки") or data.get("ТЗ") or []
        if isinstance(tm, list) and tm:
            for item in tm[:10]:
                if isinstance(item, dict):
                    lines.append(f"• {_esc(item.get('Наим') or item)}")
                else:
                    lines.append(f"• {_esc(item)}")
        else:
            lines.append("Товарные знаки не найдены в ответе.")
    elif section == "employees":
        emp = data.get("Сотрудники") or data.get("Численность") or {}
        if isinstance(emp, (str, int, float)):
            lines.append(f"Численность / сведения: {_esc(emp)}")
        elif isinstance(emp, dict):
            for k, v in list(emp.items())[:12]:
                if isinstance(v, (str, int, float)):
                    lines.append(f"• {_esc(k)}: {_esc(v)}")
        else:
            lines.append("Сведений о сотрудниках в кратком ответе нет.")
    else:
        lines.append("Раздел в разработке — откройте карточку на сайте.")

    return "\n".join(lines) + footer
