#!/usr/bin/env python3
"""Оставшиеся .doc/.docx/.pdf ОГПП+Гео → txt в docs_qa/."""
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
    # OGPP rest
    ("ustav_ogpp.pdf", "ustav_ogpp.txt"),
    ("polozhenie_reestr_ogpp.doc", "polozhenie_reestr_ogpp.txt"),
    ("polozhenie_kk_ogpp.doc", "polozhenie_kk_ogpp.txt"),
    ("polozhenie_mery_disc_ogpp.doc", "polozhenie_mery_disc_ogpp.txt"),
    ("polozhenie_strah_go_ogpp.doc", "polozhenie_strah_go_ogpp.txt"),
    ("polozhenie_strah_odo_ogpp.doc", "polozhenie_strah_odo_ogpp.txt"),
    ("polozhenie_kf_odo_ogpp.doc", "polozhenie_kf_odo_ogpp.txt"),
    ("polozhenie_obmen_dok_ogpp.docx", "polozhenie_obmen_dok_ogpp.txt"),
    ("polozhenie_inform_otkrytost_ogpp.doc", "polozhenie_inform_otkrytost_ogpp.txt"),
    ("standart_assotsiatsii_ogpp.pdf", "standart_assotsiatsii_ogpp.txt"),
    ("polozhenie_analiz_ogpp.doc", "polozhenie_analiz_ogpp.txt"),
    # GEO rest
    ("ustav_geo.pdf", "ustav_geo.txt"),
    ("polozhenie_reestr_geo.docx", "polozhenie_reestr_geo.txt"),
    ("polozhenie_kk_geo.doc", "polozhenie_kk_geo.txt"),
    ("polozhenie_mery_disc_geo.docx", "polozhenie_mery_disc_geo.txt"),
    ("polozhenie_strah_go_geo.doc", "polozhenie_strah_go_geo.txt"),
    ("polozhenie_strah_odo_geo.doc", "polozhenie_strah_odo_geo.txt"),
    ("polozhenie_kf_odo_geo.doc", "polozhenie_kf_odo_geo.txt"),
    ("polozhenie_obmen_dok_geo.docx", "polozhenie_obmen_dok_geo.txt"),
    ("polozhenie_inform_otkrytost_geo.docx", "polozhenie_inform_otkrytost_geo.txt"),
    ("standart_assotsiatsii_geo.doc", "standart_assotsiatsii_geo.txt"),
    ("polozhenie_analiz_geo.doc", "polozhenie_analiz_geo.txt"),
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


def pdf_to_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts = []
    for i, page in enumerate(reader.pages):
        t = page.extract_text() or ""
        if t.strip():
            parts.append(f"--- стр. {i + 1} ---\n{t}")
    return "\n\n".join(parts)


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
    with tempfile.TemporaryDirectory(prefix="ogpp_geo_rest_") as tmp_s:
        tmp = Path(tmp_s)
        for src_name, txt_name in MAP:
            src = RAW / src_name
            if not src.is_file():
                raise FileNotFoundError(src)
            suf = src.suffix.lower()
            if suf == ".docx":
                text = docx_to_text(src)
            elif suf == ".pdf":
                text = pdf_to_text(src)
            else:
                text = soffice_to_text(src, tmp)
            text = text.replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"
            if len(text) < 400:
                raise RuntimeError(f"too short: {txt_name} ({len(text)})")
            out = OUT / txt_name
            out.write_text(text, encoding="utf-8")
            print(f"ok {txt_name}: {len(text)} chars")
    print("extract_rest_ok")


if __name__ == "__main__":
    main()
