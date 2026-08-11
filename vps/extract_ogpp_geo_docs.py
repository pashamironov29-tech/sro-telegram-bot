#!/usr/bin/env python3
"""Скачанные .doc/.docx ОГПП+Гео → txt в docs_qa/ (LibreOffice + docx xml)."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "sro files" / "docs_qa" / "_raw"
OUT = ROOT / "sro files" / "docs_qa"
SOFFICE = Path(r"C:\Program Files\LibreOffice\program\soffice.exe")

MAP = [
    ("polozhenie_chlenstvo_ogpp.doc", "polozhenie_chlenstvo_ogpp.txt"),
    ("polozhenie_kontrol_ogpp.doc", "polozhenie_kontrol_ogpp.txt"),
    ("polozhenie_zhaloby_ogpp.doc", "polozhenie_zhaloby_ogpp.txt"),
    ("polozhenie_kf_vv_ogpp.doc", "polozhenie_kf_vv_ogpp.txt"),
    ("polozhenie_uved_dogovor_ogpp.docx", "polozhenie_uved_dogovor_ogpp.txt"),
    ("polozhenie_chlenstvo_geo.doc", "polozhenie_chlenstvo_geo.txt"),
    ("polozhenie_kontrol_geo.doc", "polozhenie_kontrol_geo.txt"),
    ("polozhenie_zhaloby_geo.doc", "polozhenie_zhaloby_geo.txt"),
    ("polozhenie_kf_vv_geo.doc", "polozhenie_kf_vv_geo.txt"),
    ("polozhenie_uved_dogovor_geo.docx", "polozhenie_uved_dogovor_geo.txt"),
]


def docx_to_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    parts: list[str] = []
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag == "t" and node.text:
            parts.append(node.text)
        elif tag == "tab":
            parts.append("\t")
        elif tag in ("br", "cr"):
            parts.append("\n")
        elif tag == "p":
            parts.append("\n")
    return "".join(parts).replace("\r", "\n")


def soffice_to_text(src: Path, tmp: Path) -> str:
    work = tmp / src.name
    shutil.copy2(src, work)
    subprocess.run(
        [
            str(SOFFICE),
            "--headless",
            "--nologo",
            "--nofirststartwizard",
            "--convert-to",
            "txt:Text",
            "--outdir",
            str(tmp),
            str(work),
        ],
        check=True,
        timeout=180,
    )
    produced = work.with_suffix(".txt")
    if not produced.is_file():
        candidates = sorted(tmp.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            raise FileNotFoundError(f"no txt for {src.name}")
        produced = candidates[0]
    raw = produced.read_bytes()
    for enc in ("utf-8", "utf-16", "cp1251", "latin-1"):
        try:
            text = raw.decode(enc)
            if len(text.strip()) > 200:
                return text
        except Exception:
            continue
    return raw.decode("utf-8", errors="ignore")


def main() -> None:
    if not SOFFICE.is_file():
        raise SystemExit(f"no soffice: {SOFFICE}")
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ogpp_geo_") as tmp_s:
        tmp = Path(tmp_s)
        for src_name, txt_name in MAP:
            src = RAW / src_name
            if not src.is_file():
                raise FileNotFoundError(src)
            if src.suffix.lower() == ".docx":
                text = docx_to_text(src)
            else:
                text = soffice_to_text(src, tmp)
            text = text.replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"
            if len(text) < 500:
                raise RuntimeError(f"too short: {txt_name} ({len(text)})")
            out = OUT / txt_name
            out.write_text(text, encoding="utf-8")
            print(f"ok {txt_name}: {len(text)} chars")
    print("extract_ogpp_geo_ok")


if __name__ == "__main__":
    main()
