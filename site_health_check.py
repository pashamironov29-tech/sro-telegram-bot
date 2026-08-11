#!/usr/bin/env python3
"""Ежедневная проверка НРС (НОСТРОЙ/НОПРИЗ) и сайтов/реестров 15 СРО.

При сбоях — сообщение в Telegram всем BOT_ADMIN_IDS.
Запуск на VPS: python3 site_health_check.py
  --notify-ok   — писать и когда всё зелёное (для ручного теста)
  --no-telegram — только лог/stdout, без Telegram
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urlparse

import requests

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(CURRENT_DIR, "site_health_state.json")
LOG_DIR = os.path.join(CURRENT_DIR, "logs")

UA = {"User-Agent": "SRO-Bot/1.0 (+site health check)"}
TIMEOUT = 25

NOSTROY_URL = "https://nrs.nostroy.ru/"
NOPRIZ_URL = "https://nrs.nopriz.ru/"
NOPRIZ_API = "https://nrs.nopriz.ru/api/specialist/list"

# Маркеры: если пропали — похоже, сменили вёрстку/API
NOSTROY_MARKERS = ("s.registrationNumber", "s.fio", "registrationNumber")
NOPRIZ_API_KEYS = ("registrationNumber", "fio", "workTypes")


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    url: str = ""


def _admin_ids() -> list[int]:
    try:
        from config_keys import BOT_ADMIN_IDS
    except Exception:
        return []
    if BOT_ADMIN_IDS is None:
        return []
    if isinstance(BOT_ADMIN_IDS, (int, str)):
        try:
            return [int(BOT_ADMIN_IDS)]
        except (TypeError, ValueError):
            return []
    out: list[int] = []
    for x in BOT_ADMIN_IDS:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


def _bot_token() -> str:
    from config_keys import BOT_TOKEN

    return BOT_TOKEN


def _send_telegram(text: str) -> bool:
    token = _bot_token()
    admins = _admin_ids()
    if not admins:
        print("WARN: BOT_ADMIN_IDS пуст — Telegram некуда слать", flush=True)
        return False
    ok_any = False
    api = f"https://api.telegram.org/bot{token}/sendMessage"
    for admin_id in admins:
        try:
            r = requests.post(
                api,
                json={
                    "chat_id": admin_id,
                    "text": text[:4000],
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=30,
            )
            data = r.json()
            if data.get("ok"):
                ok_any = True
            else:
                print(f"WARN telegram {admin_id}: {data}", flush=True)
        except Exception as exc:
            print(f"WARN telegram {admin_id}: {exc}", flush=True)
    return ok_any


def _get(url: str) -> tuple[int | None, str, str | None]:
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT, allow_redirects=True)
        return r.status_code, r.text or "", None
    except Exception as exc:
        return None, "", str(exc)


def check_nostroy() -> CheckResult:
    code, body, err = _get(NOSTROY_URL)
    if err:
        return CheckResult("НОСТРОЙ НРС", False, f"сеть: {err}", NOSTROY_URL)
    if code != 200:
        return CheckResult("НОСТРОЙ НРС", False, f"HTTP {code}", NOSTROY_URL)
    missing = [m for m in NOSTROY_MARKERS if m not in body]
    # Достаточно любого маркера фильтра — сайт SPA может менять набор
    if len(missing) == len(NOSTROY_MARKERS):
        return CheckResult(
            "НОСТРОЙ НРС",
            False,
            "страница открылась, но нет маркеров фильтра "
            f"({', '.join(NOSTROY_MARKERS)}) — возможно сменили вёрстку",
            NOSTROY_URL,
        )
    return CheckResult("НОСТРОЙ НРС", True, f"HTTP {code}, маркеры ок", NOSTROY_URL)


def check_nopriz() -> CheckResult:
    # 1) Главная
    code, body, err = _get(NOPRIZ_URL)
    if err:
        return CheckResult("НОПРИЗ НРС", False, f"сайт: {err}", NOPRIZ_URL)
    if code != 200:
        return CheckResult("НОПРИЗ НРС", False, f"сайт HTTP {code}", NOPRIZ_URL)

    # 2) API списка (то, чем пользуется бот)
    try:
        r = requests.post(
            NOPRIZ_API,
            json={"filters": {"registrationNumber": "П-122864"}, "page": 1},
            headers={
                **UA,
                "Accept": "application/json",
                "Content-Type": "application/json;charset=UTF-8",
                "Referer": NOPRIZ_URL,
                "Origin": "https://nrs.nopriz.ru",
            },
            timeout=TIMEOUT,
        )
    except Exception as exc:
        return CheckResult("НОПРИЗ API", False, f"сеть: {exc}", NOPRIZ_API)

    if r.status_code != 200:
        return CheckResult("НОПРИЗ API", False, f"HTTP {r.status_code}", NOPRIZ_API)
    try:
        payload = r.json().get("data") or {}
        rows = payload.get("data") or []
    except Exception as exc:
        return CheckResult("НОПРИЗ API", False, f"не JSON: {exc}", NOPRIZ_API)
    if not rows:
        return CheckResult(
            "НОПРИЗ API",
            False,
            "ответ 200, но пустой список по контрольному номеру — формат/фильтр?",
            NOPRIZ_API,
        )
    row = rows[0]
    missing = [k for k in NOPRIZ_API_KEYS if k not in row]
    if missing:
        return CheckResult(
            "НОПРИЗ API",
            False,
            f"нет полей {missing} — возможно сменили API",
            NOPRIZ_API,
        )
    return CheckResult(
        "НОПРИЗ API",
        True,
        f"HTTP 200, карточка {row.get('registrationNumber')}",
        NOPRIZ_API,
    )


def check_http_page(name: str, url: str, *, must_contain: tuple[str, ...] = ()) -> CheckResult:
    code, body, err = _get(url)
    if err:
        return CheckResult(name, False, f"сеть: {err}", url)
    if code is None or code >= 400:
        return CheckResult(name, False, f"HTTP {code}", url)
    low = body.lower()
    if must_contain:
        missing = [m for m in must_contain if m.lower() not in low]
        if len(missing) == len(must_contain):
            return CheckResult(
                name,
                False,
                f"HTTP {code}, но нет ожидаемых фрагментов ({', '.join(must_contain)})",
                url,
            )
    return CheckResult(name, True, f"HTTP {code}", url)


def check_sro_sites() -> list[CheckResult]:
    from reestr_sync import SRO_SOURCES

    results: list[CheckResult] = []
    for sro_id, src in SRO_SOURCES.items():
        name = src.get("name") or sro_id
        list_url = src.get("list_url") or ""
        if not list_url:
            results.append(CheckResult(f"{name} реестр", False, "нет list_url", ""))
            continue
        parsed = urlparse(list_url)
        base = f"{parsed.scheme}://{parsed.netloc}/" if parsed.scheme and parsed.netloc else ""

        # Главная сайта
        if base:
            results.append(
                check_http_page(
                    f"{name} сайт",
                    base,
                    must_contain=(),  # достаточно открыться
                )
            )
        # Страница реестра — критична для бота
        results.append(
            check_http_page(
                f"{name} реестр",
                list_url,
                must_contain=("инн", "reestr", "реестр"),
            )
        )
        time.sleep(0.15)
    return results


def run_all_checks() -> list[CheckResult]:
    out: list[CheckResult] = []
    out.append(check_nostroy())
    out.append(check_nopriz())
    out.extend(check_sro_sites())
    return out


def format_report(results: list[CheckResult]) -> str:
    failed = [r for r in results if not r.ok]
    ok_n = len(results) - len(failed)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if failed:
        head = f"🛡 <b>Проверка сайтов</b> — есть проблемы\n{stamp}\n"
    else:
        head = f"🛡 <b>Проверка сайтов</b> — всё ок\n{stamp}\n"
    head += f"Итого: ✅ {ok_n} · ❌ {len(failed)} из {len(results)}\n\n"

    lines = [head]
    if failed:
        lines.append("<b>Сломалось:</b>")
        for r in failed:
            url = f"\n  {html.escape(r.url)}" if r.url else ""
            lines.append(
                f"❌ <b>{html.escape(r.name)}</b>: {html.escape(r.detail)}{url}"
            )
        lines.append("")
    # Кратко по НРС всегда
    for r in results:
        if r.name.startswith(("НОСТРОЙ", "НОПРИЗ")):
            mark = "✅" if r.ok else "❌"
            lines.append(f"{mark} {html.escape(r.name)} — {html.escape(r.detail)}")
    return "\n".join(lines).strip()


def save_state(results: list[CheckResult]) -> None:
    payload = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "ok": all(r.ok for r in results),
        "results": [asdict(r) for r in results],
    }
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except OSError as exc:
        print(f"WARN state: {exc}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Проверка НРС + сайтов СРО")
    parser.add_argument(
        "--notify-ok",
        action="store_true",
        help="Писать в Telegram даже если всё зелёное",
    )
    parser.add_argument(
        "--no-telegram",
        action="store_true",
        help="Не слать в Telegram (только stdout/лог)",
    )
    args = parser.parse_args(argv)

    print(f"=== site health {datetime.now(timezone.utc).isoformat()} ===", flush=True)
    results = run_all_checks()
    save_state(results)

    failed = [r for r in results if not r.ok]
    for r in results:
        mark = "OK" if r.ok else "FAIL"
        print(f"[{mark}] {r.name}: {r.detail} ({r.url})", flush=True)

    report = format_report(results)
    print("--- telegram preview ---", flush=True)
    print(report, flush=True)

    should_notify = (not args.no_telegram) and (bool(failed) or args.notify_ok)
    if should_notify:
        sent = _send_telegram(report)
        print(f"telegram sent={sent} admins={_admin_ids()}", flush=True)
    else:
        print("telegram skipped (всё ок или --no-telegram)", flush=True)

    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(
        LOG_DIR,
        f"site_health_{datetime.now(timezone.utc).strftime('%Y-%m-%d_%H%M%S')}.log",
    )
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(report + "\n\n")
            for r in results:
                f.write(f"{'OK' if r.ok else 'FAIL'}\t{r.name}\t{r.detail}\t{r.url}\n")
        print(f"log: {log_path}", flush=True)
    except OSError as exc:
        print(f"WARN log: {exc}", flush=True)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
