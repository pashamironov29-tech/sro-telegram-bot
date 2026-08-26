# -*- coding: utf-8 -*-
"""Точечная проверка кнопок MAX: FAQ/НРС, меню, Checko-payload, ссылки реестров.

Запуск из GOLD: py -u scripts/check_max_menu.py
Сеть для Checko/НОПРИЗ API не обязательна (кроме опции --live-nrs).
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import bot_MAX as m  # noqa: E402
from checko_client import SECTIONS as CHECKO_SECTIONS  # noqa: E402
from nrs_search_links import nrs_registry_link_buttons  # noqa: E402

FAILS: list[str] = []
OKS: list[str] = []


def ok(msg: str) -> None:
    OKS.append(msg)
    print(f"  OK  {msg}")


def fail(msg: str) -> None:
    FAILS.append(msg)
    print(f"  FAIL {msg}")


def _payloads(atts) -> list[tuple[str, str, str]]:
    """(kind, text, payload_or_url) from MAX keyboard attachments."""
    out: list[tuple[str, str, str]] = []
    if not atts:
        return out
    for att in atts:
        if not isinstance(att, dict):
            continue
        if att.get("type") != "inline_keyboard":
            continue
        payload = att.get("payload") or {}
        rows = payload.get("buttons") or []
        for row in rows:
            for btn in row or []:
                if not isinstance(btn, dict):
                    continue
                text = btn.get("text") or ""
                kind = btn.get("type") or ""
                if kind == "callback":
                    out.append(("callback", text, btn.get("payload") or ""))
                elif kind == "link":
                    out.append(("link", text, btn.get("url") or ""))
    return out


def check_faq_buttons() -> None:
    print("\n== FAQ: каждая кнопка → свой текст ==")
    captured: list[tuple[str, str]] = []

    def capture(user_id, text, attachments=None):
        captured.append((text or "", json.dumps(attachments, ensure_ascii=False) if attachments else ""))

    orig = m.send
    m.send = capture  # type: ignore[assignment]
    uid = 16526987
    try:
        expected = {
            "nrs_docs": ("Документы для внесения в НРС", "Кураторы по вопросам НРС"),
            "nrs_cur": ("Кураторы по вопросам НРС", "Нотариальная копия диплома"),
            "nok_rules": ("Правила независимой оценки", "курс подготовки к НОК"),
            "nok_prep": ("курс подготовки к НОК", "Правила независимой оценки квалификации"),
            "specs": ("Требования к специалистам", "Документы для внесения в НРС НОСТРОЙ"),
            "join_docs": ("Пакет документов для вступления", "Кураторы по вопросам НРС"),
            "how": ("вступ", None),
            "terms": ("срок", None),
            "extract": ("выписк", None),
            "changes": ("изменен", None),
            "schedule": ("проверя", None),
            "violations": ("нарушен", None),
            "laws": ("Нормативно-правовая", None),
            "refund": ("Возврат взноса", None),
            "own": ("собственных нужд", None),
            "lk": ("кабинет", None),
            "about": ("Ассоциац", None),
            "trusted": ("известные компании", None),
            "partners": ("Партнёр", None),
            "regions": ("Филиал", None),
            "feedback": ("Жалоб", None),
            "charity": ("Благотворит", None),
            "fees": ("взнос", None),
        }
        nok_map = {
            "📋 Документы в НРС": "nrs_docs",
            "👤 Кураторы НРС": "nrs_cur",
            "🎓 Правила НОК": "nok_rules",
            "🎓 Подготовка к НОК": "nok_prep",
        }
        for label, topic in nok_map.items():
            captured.clear()
            m.send_faq_topic(uid, topic)
            if not captured:
                fail(f"{label} → нет ответа")
                continue
            text = captured[0][0]
            must, must_not = expected[topic]
            if must.lower() not in text.lower():
                fail(f"{label} → нет «{must}». Начало: {text[:80]!r}")
            elif must_not and must_not.lower() in text.lower() and topic in ("nrs_docs", "nrs_cur", "nok_rules", "nok_prep"):
                # nrs_docs не должен быть текстом кураторов и наоборот
                if topic == "nrs_docs" and "Вельвич" in text:
                    fail(f"{label} открыл кураторов, а не документы")
                elif topic == "nrs_cur" and "Нотариальная копия" in text:
                    fail(f"{label} открыл документы, а не кураторов")
                elif topic == "nok_rules" and "480 тестовых" in text:
                    fail(f"{label} открыл подготовку, а не правила")
                elif topic == "nok_prep" and "не реже одного раза в 5 лет" in text and "480" not in text:
                    fail(f"{label} открыл правила, а не подготовку")
                else:
                    ok(f"{label} → {topic}")
            else:
                ok(f"{label} → {topic}")

        for topic, (must, _mn) in expected.items():
            if topic in nok_map.values():
                continue
            captured.clear()
            m.send_faq_topic(uid, topic)
            if not captured:
                fail(f"faq:{topic} → нет ответа")
                continue
            text = captured[0][0]
            if "готовится" in text.lower() and topic not in ("how", "fees", "about"):
                fail(f"faq:{topic} → «раздел готовится»")
            elif must.lower() not in text.lower():
                fail(f"faq:{topic} → нет «{must}». Начало: {text[:90]!r}")
            else:
                ok(f"faq:{topic}")
    finally:
        m.send = orig


def check_menu_routes() -> None:
    print("\n== Меню: payload → свой экран ==")
    captured: list[str] = []

    def capture(user_id, text, attachments=None):
        captured.append(text or "")

    orig = m.send
    m.send = capture  # type: ignore[assignment]
    uid = 16526987
    fake = {}
    try:
        routes = [
            ("menu:search", "ИНН"),
            ("menu:info", "Полезная информация"),
            ("menu:help", "Справка"),
            ("menu:controller", "Меню контролёра"),
            ("menu:nrs", "НРС"),
            ("menu:cai", "ИИ-помощник"),
            ("faq:root", "FAQ"),
            ("faq:join", "Для вступающих"),
            ("faq:members", "Действующим членам"),
            ("faq:nok", "Специалисты и НОК"),
            ("faq:assoc", "Ассоциация"),
        ]
        for payload, needle in routes:
            captured.clear()
            m.handle_callback(uid, payload, fake)
            blob = "\n".join(captured)
            if needle.lower() not in blob.lower():
                fail(f"{payload} → нет «{needle}». Получено: {blob[:100]!r}")
            else:
                ok(f"{payload} → {needle}")
        captured.clear()
        m.handle_callback(uid, "faq:nok", fake)
        btns = _payloads(m.faq_nok_keyboard())
        labels = {t for _k, t, _p in btns}
        for need in ("Документы в НРС", "Кураторы НРС", "Правила НОК", "Подготовка к НОК"):
            if not any(need in x for x in labels):
                fail(f"клавиатура НОК без «{need}»")
            else:
                ok(f"клавиатура НОК: {need}")
        by_payload = {p: t for k, t, p in btns if k == "callback"}
        if by_payload.get("faq:nrs_docs") and "Документы" not in by_payload["faq:nrs_docs"]:
            fail("faq:nrs_docs привязан не к «Документы в НРС»")
        if by_payload.get("faq:nrs_cur") and "Кураторы" not in by_payload["faq:nrs_cur"]:
            fail("faq:nrs_cur привязан не к «Кураторы НРС»")
    finally:
        m.send = orig


def check_nrs_links() -> None:
    print("\n== НРС: кнопка НОСТРОЙ ≠ кнопка НОПРИЗ ==")
    cases = [
        ("С-55-267917", "nostroy", "nopriz"),
        ("C-BY-260757", "nostroy", "nopriz"),
        ("П-122864", "nopriz", "nostroy"),
        ("ПИ-083721", "nopriz", "nostroy"),
        ("Иванов Иван Иванович", "both", None),
    ]
    for query, expect, _other in cases:
        btns = nrs_registry_link_buttons(query)
        urls = {label: url for label, url in btns}
        nst = [u for l, u in btns if "НОСТРОЙ" in l]
        npr = [u for l, u in btns if "НОПРИЗ" in l]
        if expect == "nostroy":
            if len(nst) != 1 or npr:
                fail(f"{query!r}: должен быть только НОСТРОЙ, есть {list(urls)}")
            elif "nrs.nostroy.ru" not in nst[0] or "nopriz" in nst[0]:
                fail(f"{query!r}: НОСТРОЙ-кнопка ведёт не туда: {nst[0]}")
            else:
                ok(f"{query} → только nrs.nostroy.ru")
        elif expect == "nopriz":
            if len(npr) != 1 or nst:
                fail(f"{query!r}: должен быть только НОПРИЗ, есть {list(urls)}")
            elif "nrs.nopriz.ru" not in npr[0] or "nostroy" in npr[0]:
                fail(f"{query!r}: НОПРИЗ-кнопка ведёт не туда: {npr[0]}")
            else:
                ok(f"{query} → только nrs.nopriz.ru")
        else:
            if len(nst) != 1 or len(npr) != 1:
                fail(f"{query!r}: нужны обе кнопки, есть {list(urls)}")
            elif "nrs.nostroy.ru" not in nst[0] or "nrs.nopriz.ru" not in npr[0]:
                fail(f"{query!r}: URL перепутаны: {nst} / {npr}")
            elif nst[0] == npr[0]:
                fail(f"{query!r}: обе кнопки на один URL")
            else:
                ok(f"{query} → НОСТРОЙ и НОПРИЗ разные URL")


def check_checko_payloads() -> None:
    print("\n== Checko: каждая секция свой payload ==")
    inn = "7707083893"
    kb = m.checko_sections_keyboard(inn)
    btns = _payloads(kb)
    seen_codes: dict[str, str] = {}
    for kind, text, payload in btns:
        if kind != "callback" or not payload.startswith("chk:s:"):
            continue
        parts = payload.split(":")
        if len(parts) < 4:
            fail(f"битый payload Checko {payload}")
            continue
        code, inn_p = parts[2], parts[3]
        if inn_p != inn:
            fail(f"{text}: ИНН в payload {inn_p} ≠ {inn}")
        if code in seen_codes:
            fail(f"код секции {code} на двух кнопках: {seen_codes[code]!r} и {text!r}")
        else:
            seen_codes[code] = text
            ok(f"{text} → chk:s:{code}:{inn}")
    expected_codes = {c for c, _l, _m in CHECKO_SECTIONS}
    if set(seen_codes) != expected_codes:
        fail(f"секции Checko {set(seen_codes)} ≠ {expected_codes}")
    else:
        ok(f"все {len(expected_codes)} разделов Checko на месте")

    captured: list[str] = []

    def capture(user_id, text, attachments=None):
        captured.append(text or "")

    orig_send = m.send
    orig_fmt = m.format_checko_section

    def fake_fmt(section, inn_arg):
        return f"CHECKO_SECTION={section}|INN={inn_arg}"

    m.send = capture  # type: ignore[assignment]
    m.format_checko_section = fake_fmt  # type: ignore[assignment]
    try:
        for code, label, _method in CHECKO_SECTIONS:
            captured.clear()
            m.handle_checko(16526987, f"chk:s:{code}:{inn}")
            blob = "\n".join(captured)
            if f"CHECKO_SECTION={code}" not in blob:
                fail(f"кнопка {label} не открыла section={code}: {blob[:80]!r}")
            elif f"INN={inn}" not in blob:
                fail(f"кнопка {label} потеряла ИНН")
            else:
                ok(f"нажатие {label} → section {code}")
        captured.clear()
        m.handle_checko(16526987, f"chk:f:{inn}")
        blob = "\n".join(captured)
        if "CHECKO_SECTION=general" not in blob:
            fail(f"Полная информация не открыла general: {blob[:80]!r}")
        else:
            ok("chk:f → general + клавиатура разделов")
    finally:
        m.send = orig_send
        m.format_checko_section = orig_fmt


def check_start_search_commands() -> None:
    print("\n== /start /search /controller ==")
    captured: list[str] = []

    def capture(user_id, text, attachments=None):
        captured.append(text or "")

    orig = m.send
    m.send = capture  # type: ignore[assignment]
    uid = 16526987
    fake = {"update_type": "bot_started", "user": {"user_id": uid, "name": "Test"}}
    try:
        captured.clear()
        m.handle_text(uid, "/start", fake)
        blob = "\n".join(captured)
        if "ИНН" not in blob and "меню" not in blob.lower() and "СРО" not in blob:
            fail(f"/start пустой: {blob[:120]!r}")
        else:
            ok("/start отвечает")
        captured.clear()
        m.handle_text(uid, "/search", fake)
        if "ИНН" not in "\n".join(captured):
            fail("/search без приглашения ИНН")
        else:
            ok("/search → поиск ИНН")
        captured.clear()
        m.handle_text(uid, "/controller", fake)
        if "контролёр" not in "\n".join(captured).lower() and "контролер" not in "\n".join(captured).lower():
            fail(f"/controller: {captured[:1]}")
        else:
            ok("/controller → меню контролёра")
        captured.clear()
        m.handle_text(uid, "/info", fake)
        if "Полезная информация" not in "\n".join(captured):
            fail("/info не открыл полезное")
        else:
            ok("/info → полезная информация")
    finally:
        m.send = orig


def main() -> int:
    print("Прогон кнопок MAX (без рассылки в чат)")
    check_faq_buttons()
    check_menu_routes()
    check_nrs_links()
    check_checko_payloads()
    check_start_search_commands()
    print(f"\nИтого: {len(OKS)} ок, {len(FAILS)} ошибок")
    for f in FAILS:
        print("  -", f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
