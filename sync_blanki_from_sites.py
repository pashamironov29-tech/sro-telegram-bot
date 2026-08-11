"""
Скачать бланки контроля с сайтов всех 15 СРО в sro files/blanki/<ID>/.

Карта URL: blanki_remote_map.json (обновить: py discover_blanki_urls.py)
Запуск: py sync_blanki_from_sites.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

from blanki_sro import BLANKI_FILES, BLANKI_SRO_IDS

ROOT = Path(__file__).resolve().parent
MAP_FILE = ROOT / "blanki_remote_map.json"


def _sro_files_root() -> str:
    try:
        from config_keys import SRO_FILES_DIR

        return SRO_FILES_DIR
    except ImportError:
        return str(ROOT / "sro files")


def _load_map() -> dict:
    if not MAP_FILE.is_file():
        raise FileNotFoundError(
            f"Нет {MAP_FILE.name}. Сначала: py discover_blanki_urls.py"
        )
    return json.loads(MAP_FILE.read_text(encoding="utf-8"))


def download_all() -> int:
    remote_map = _load_map()
    root = _sro_files_root()
    session = requests.Session()
    session.headers["User-Agent"] = "GOLD-blanki-sync/1.0"
    errors = 0

    for sro_id in BLANKI_SRO_IDS:
        entry = remote_map.get(sro_id) or {}
        base = entry.get("_base", "")
        if not base:
            print(f"SKIP {sro_id}: нет _base в карте", file=sys.stderr)
            errors += 1
            continue
        out_dir = os.path.join(root, "blanki", sro_id)
        os.makedirs(out_dir, exist_ok=True)
        local_names = BLANKI_FILES[sro_id]
        for key, local_name in local_names.items():
            remote = entry.get(key)
            if not remote:
                print(f"SKIP {sro_id}/{key}: нет URL", file=sys.stderr)
                errors += 1
                continue
            url = base.rstrip("/") + remote
            dest = os.path.join(out_dir, local_name)
            print(f"GET {url} -> {dest}")
            try:
                r = session.get(url, timeout=60)
                r.raise_for_status()
                with open(dest, "wb") as f:
                    f.write(r.content)
            except Exception as exc:
                print(f"  ERROR: {exc}", file=sys.stderr)
                errors += 1
    return errors


if __name__ == "__main__":
    n = download_all()
    sys.exit(1 if n else 0)
