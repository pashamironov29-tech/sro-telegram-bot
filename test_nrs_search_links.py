#!/usr/bin/env python3
"""Smoke/regression tests for nrs_search_links (parse + live NOPRIZ API)."""
from __future__ import annotations

import sys

from nrs_search_links import (
    format_nrs_link_reply,
    parse_nrs_query,
    _nostroy_url,
    _nostroy_registration,
    _nopriz_lookup_by_fio,
    _nopriz_lookup_by_number,
    _parse_nopriz_work_types,
    _format_nopriz_work_lines,
    looks_like_nrs_person_query,
)

CASES_PARSE = [
    ("Иванов Иван Иванович", {"fio": "Иванов Иван Иванович", "number": ""}),
    ("С-BY-260757", {"fio": "", "number": "С-BY-260757"}),
    ("c-by-260757", {"fio": "", "number": "С-BY-260757"}),
    ("BY-260757", {"fio": "", "number": "BY-260757"}),
    ("С-55-267917", {"fio": "", "number": "С-55-267917"}),
    ("ПИ-083721", {"fio": "", "number": "ПИ-083721"}),
    ("П-000222", {"fio": "", "number": "П-000222"}),
    (
        "Черемнов Евгений Леонидович С-55-267917",
        {"fio": "Черемнов Евгений Леонидович", "number": "С-55-267917"},
    ),
    (
        "Харламова Олеся Владимировна ПИ-083721",
        {"fio": "Харламова Олеся Владимировна", "number": "ПИ-083721"},
    ),
    ("Мелик-Гусейнов Михаил Сергеевич", {"fio": "Мелик-Гусейнов Михаил Сергеевич", "number": ""}),
    ("", {"fio": "", "number": ""}),
    ("   ", {"fio": "", "number": ""}),
]


def test_parse():
    failed = 0
    for raw, want in CASES_PARSE:
        got = parse_nrs_query(raw)
        if got != want:
            print("FAIL parse:", repr(raw), "want", want, "got", got)
            failed += 1
        else:
            print("OK parse:", raw[:50] or "(empty)")
    return failed


def test_work_types_format():
    failed = 0
    raw = {
        "project": {
            "code": "project",
            "title": "Организация выполнения работ по подготовке проектной документации",
            "statusCode": "active",
            "statusTitle": "Действует",
            "certIssuedDate": "18.03.2025",
            "exclusionDate": "",
        },
        "research": {
            "code": "research",
            "title": "Организация выполнения работ по инженерным изысканиям",
            "statusCode": "active",
            "statusTitle": "Действует",
            "certIssuedDate": "09.07.2024",
            "exclusionDate": "",
        },
    }
    parsed = _parse_nopriz_work_types(raw)
    lines = _format_nopriz_work_lines(parsed)
    text = "\n".join(lines)
    if "Проектирование — действует (НОК 18.03.2025)" not in text:
        print("FAIL work project line", text)
        failed += 1
    elif "Изыскания — действует (НОК 09.07.2024)" not in text:
        print("FAIL work research line", text)
        failed += 1
    else:
        print("OK work types short format")
    raw2 = {"research": {"statusTitle": "Действует", "certIssuedDate": ""}}
    lines2 = _format_nopriz_work_lines(_parse_nopriz_work_types(raw2))
    if lines2 != ["• Изыскания — действует"]:
        print("FAIL work without NOK date", lines2)
        failed += 1
    else:
        print("OK work types without NOK date")
    return failed


def _section_between(text: str, start: str, end: str) -> str:
    if start not in text or end not in text:
        return ""
    return text.split(start, 1)[1].split(end, 1)[0]


def test_reply_shape():
    failed = 0
    samples = [
        "Иванов Иван Иванович",
        "С-55-267917",
        "ПИ-083721",
        "П-122864",
        "Титов Алексей Витальевич",
        "Мелик-Гусейнов Михаил Сергеевич",
        "xyz",
    ]
    for q in samples:
        try:
            text = format_nrs_link_reply(q)
            if "НОСТРОЙ" not in text or "НОПРИЗ" not in text:
                print("FAIL reply missing sections:", q)
                failed += 1
            elif len(text) > 4000:
                print("FAIL reply too long:", q, len(text))
                failed += 1
            else:
                print("OK reply:", q[:40], "len", len(text))
        except Exception as e:
            print("FAIL reply exception:", q, e)
            failed += 1
    t_n = format_nrs_link_reply("С-BY-260757")
    nopriz_sec = _section_between(t_n, "📐 <b>НОПРИЗ</b>", "<i>Официальные реестры")
    if "href=" in nopriz_sec:
        print("FAIL nostroy number should not link NOPRIZ")
        failed += 1
    elif "закрыт" not in nopriz_sec:
        print("FAIL nostroy number missing nopriz block msg", nopriz_sec)
        failed += 1
    else:
        print("OK nostroy number blocks NOPRIZ link")
    t_p = format_nrs_link_reply("П-122864")
    nostroy_sec = _section_between(t_p, "🏗 <b>НОСТРОЙ</b>", "📐 <b>НОПРИЗ</b>")
    if "Шигапов" not in t_p:
        print("FAIL nopriz number missing FIO in reply")
        failed += 1
    elif "href=" in nostroy_sec:
        print("FAIL nopriz number should not link NOSTROY")
        failed += 1
    elif "закрыт" not in nostroy_sec:
        print("FAIL nopriz number should block NOSTROY", nostroy_sec)
        failed += 1
    else:
        print("OK nopriz number shows FIO, blocks NOSTROY link")
    t_pi = format_nrs_link_reply("ПИ-083721")
    if "Проектирование" not in t_pi and "Изыскания" not in t_pi:
        print("FAIL ПИ-083721 missing work types", t_pi)
        failed += 1
    elif "НОК" not in t_pi:
        print("FAIL ПИ-083721 missing NOK date", t_pi)
        failed += 1
    else:
        print("OK ПИ-083721 shows work types + NOK")
    t_fio = format_nrs_link_reply("Харламова Олеся Владимировна")
    nostroy_fio = _section_between(t_fio, "🏗 <b>НОСТРОЙ</b>", "📐 <b>НОПРИЗ</b>")
    if "href=" not in nostroy_fio:
        print("FAIL FIO search must keep NOSTROY open", nostroy_fio)
        failed += 1
    elif "закрыт" in nostroy_fio:
        print("FAIL FIO search must not block NOSTROY", nostroy_fio)
        failed += 1
    else:
        print("OK FIO search keeps both registries")
    return failed


def test_live_nopriz():
    failed = 0
    checks = [
        ("Харламова Олеся Владимировна", 1, "ПИ-083721"),
        ("Титов Алексей Витальевич", 2, None),
        ("Мелик-Гусейнов Михаил Сергеевич", 0, None),
    ]
    for fio, min_n, exact_reg in checks:
        rows, total = _nopriz_lookup_by_fio(fio)
        n = len(rows)
        if min_n == 0 and n != 0:
            print("FAIL live expect 0 got", n, fio)
            failed += 1
        elif min_n and n < min_n:
            print("FAIL live expect >=", min_n, "got", n, fio)
            failed += 1
        else:
            print("OK live NOPRIZ fio:", fio, "n=", n, "total=", total, rows[:2])
        if exact_reg and rows and rows[0]["registrationNumber"] != exact_reg:
            print("FAIL reg", rows[0]["registrationNumber"], "!=", exact_reg)
            failed += 1
        if exact_reg and rows and not rows[0].get("work_types"):
            print("FAIL live missing work_types", fio, rows[0])
            failed += 1
    rows, total = _nopriz_lookup_by_number("П-122864")
    if not rows or rows[0]["fio"] != "Шигапов Артём Ильдарович":
        print("FAIL live NOPRIZ number", rows)
        failed += 1
    else:
        print("OK live NOPRIZ number П-122864", rows[0])
        if not rows[0].get("work_types"):
            print("FAIL live П-122864 missing work_types")
            failed += 1
    return failed


def test_nostroy_urls():
    failed = 0
    u1 = _nostroy_url(number="С-55-267917")
    if "registrationNumber" not in u1 or "55" not in u1:
        print("FAIL nostroy url number", u1)
        failed += 1
    else:
        print("OK nostroy number url")
    u2 = _nostroy_url(fio="Мелик-Гусейнов Михаил Сергеевич")
    if "s.fio" not in u2:
        print("FAIL nostroy fio url", u2)
        failed += 1
    else:
        print("OK nostroy fio url")
    u3 = _nostroy_url(number="BY-260757")
    if _nostroy_registration("BY-260757") != "С-BY-260757":
        print("FAIL nostroy reg BY", _nostroy_registration("BY-260757"))
        failed += 1
    elif "BY" not in u3 or "260757" not in u3:
        print("FAIL nostroy BY url", u3)
        failed += 1
    else:
        print("OK nostroy BY-260757 -> С-BY-260757")
    u4 = _nostroy_url(number="c-by-260757")
    if "BY" not in u4 and "%42%59" not in u4:
        print("FAIL c-by url", u4)
        failed += 1
    else:
        print("OK c-by-260757 url")
    return failed


def test_nrs_person_query():
    failed = 0
    yes = ["Малинина Ольга Николаевна", "Юренко Денис Николаевич", "Иванов Иван"]
    no = ["Филина", "телефон Миронова", "П-122864", "xyz?"]
    for q in yes:
        if not looks_like_nrs_person_query(q):
            print("FAIL nrs person yes", q)
            failed += 1
        else:
            print("OK nrs person yes", q)
    for q in no:
        if looks_like_nrs_person_query(q):
            print("FAIL nrs person no", q)
            failed += 1
        else:
            print("OK nrs person no", q)
    return failed


if __name__ == "__main__":
    total = 0
    total += test_parse()
    total += test_work_types_format()
    total += test_nostroy_urls()
    total += test_nrs_person_query()
    total += test_reply_shape()
    print("--- live API (needs network) ---")
    total += test_live_nopriz()
    print("---")
    if total:
        print("FAILED:", total)
        sys.exit(1)
    print("ALL OK")
    sys.exit(0)
