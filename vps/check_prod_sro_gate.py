#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Перед выкладкой/стартом: нельзя поднять бой с урезанным набором СРО."""
from __future__ import annotations
import os
from pathlib import Path as _Path
_orig_resolve = _Path.resolve

def _safe_resolve(self, strict=False):
    try:
        return _orig_resolve(self, strict=strict)
    except OSError:
        return _Path(os.path.abspath(str(self)))

_Path.resolve = _safe_resolve  # type: ignore[method-assign]


import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sro_profiles import (  # noqa: E402
    PROD_SRO_COUNT,
    assert_prod_sro_ready,
    list_known_sro_ids,
    site_base_for_sro,
)


def main() -> int:
    try:
        assert_prod_sro_ready()
    except Exception as e:
        print("FAIL:", e)
        return 1
    ids = list_known_sro_ids()
    print(f"OK: prod gate — {len(ids)}/{PROD_SRO_COUNT} СРО, сайты уникальны")
    for sid in ids:
        print(f"  {sid}: {site_base_for_sro(sid)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())