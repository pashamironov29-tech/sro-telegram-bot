# -*- coding: utf-8 -*-
"""Нагрузка ядра бота без Telegram polling (безопасно для боевого)."""
from __future__ import annotations

import json
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

CACHE = Path("/opt/sro-bot/reestr_cache.json")
if not CACHE.exists():
    CACHE = Path("reestr_cache.json")


def load_orgs() -> dict:
    raw = json.loads(CACHE.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and isinstance(raw.get("organizations"), dict):
        return raw["organizations"]
    if isinstance(raw, dict) and isinstance(raw.get("by_inn"), dict):
        return raw["by_inn"]
    return raw if isinstance(raw, dict) else {}


def org_name(row: dict) -> str:
    for k in ("name", "short_name", "full_name", "title", "org_name", "наименование"):
        v = row.get(k)
        if v:
            return str(v)
    for k in ("card", "info", "data"):
        nested = row.get(k)
        if isinstance(nested, dict):
            n = org_name(nested)
            if n:
                return n
    return ""


def search_by_name(by_inn: dict, query: str, limit: int = 15) -> list:
    q = (query or "").lower().strip()
    if len(q) < 2:
        return []
    out = []
    for inn, row in by_inn.items():
        if not isinstance(row, dict):
            continue
        name = org_name(row)
        if q in name.lower():
            out.append((inn, name))
            if len(out) >= limit:
                break
    return out


def main():
    t0 = time.perf_counter()
    by_inn = load_orgs()
    inns = [k for k in by_inn.keys() if str(k).isdigit() and len(str(k)) in (10, 12)]
    names = []
    for inn in inns[:8000]:
        name = org_name(by_inn.get(inn) or {})
        toks = [t for t in name.replace('"', " ").split() if len(t) >= 4]
        if toks:
            names.append(toks[0])
    names = list({n for n in names})[:300]
    print(f"cache_orgs={len(by_inn)} inns={len(inns)} name_tokens={len(names)}")
    print(f"load_sec={time.perf_counter()-t0:.2f}")
    if inns:
        sample = by_inn[inns[0]]
        print("sample_keys", list(sample)[:12] if isinstance(sample, dict) else type(sample))
        print("sample_name", org_name(sample)[:80])

    scenarios = [
        ("100_parallel_inn", 100, "inn"),
        ("100_parallel_name", 100, "name"),
        ("300_mixed", 300, "mixed"),
    ]

    for title, n, kind in scenarios:
        lat = []
        errors = 0
        hits = 0
        start = time.perf_counter()

        def one(i: int):
            st = time.perf_counter()
            try:
                if kind == "inn" or (kind == "mixed" and i % 2 == 0):
                    inn = random.choice(inns)
                    ok = inn in by_inn
                    return time.perf_counter() - st, True, 1 if ok else 0
                q = random.choice(names) if names else "строй"
                found = search_by_name(by_inn, q)
                return time.perf_counter() - st, True, 1 if found else 0
            except Exception:
                return time.perf_counter() - st, False, 0

        workers = min(100, n)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(one, i) for i in range(n)]
            for f in as_completed(futs):
                sec, ok, hit = f.result()
                lat.append(sec * 1000)
                hits += hit
                if not ok:
                    errors += 1

        total = time.perf_counter() - start
        lat.sort()
        p50 = lat[len(lat) // 2]
        p95 = lat[max(0, int(len(lat) * 0.95) - 1)]
        p99 = lat[max(0, int(len(lat) * 0.99) - 1)]
        print(
            f"{title}: n={n} workers={workers} total_s={total:.2f} "
            f"rps={n/total:.1f} p50_ms={p50:.1f} p95_ms={p95:.1f} p99_ms={p99:.1f} "
            f"max_ms={max(lat):.1f} hits={hits} errors={errors}"
        )

    print("OK_CORE_LOAD")


if __name__ == "__main__":
    main()