#!/usr/bin/env python3
"""Extract selected OGPS docs into sro files/docs_qa/*.txt"""
from __future__ import annotations

import re
import shutil
import struct
import zipfile
from pathlib import Path

import olefile

ROOT = Path(__file__).resolve().parents[1]
DOCS_QA = ROOT / "sro files" / "docs_qa"
SRC = DOCS_QA / "sources"
DESK = Path.home() / "Desktop" / "файлы для добавление в бота сро"

# (filename on desktop, source copy name, txt name)
FILES = [
    ("01_pol_ob_obmene_dok_OGPS_30092025_z.docx", "pol_obmen_dok_ogps.docx", "polozhenie_obmen_dok_ogps.txt"),
    ("06 strah_odo_ogps_18052026.doc", "strah_odo_ogps.doc", "polozhenie_strah_odo_ogps.txt"),
    ("inform_srogen_2019.doc", "inform_srogen_2019.doc", "polozhenie_inform_otkrytost_ogps.txt"),
    ("Pol_kf_vv_srogen_10042026_zam.docx", "pol_kf_vv_ogps.docx", "polozhenie_kf_vv_ogps.txt"),
    ("Pol_mery_disc_vozd_srogen_10042026_zam.doc", "pol_mery_disc_ogps.doc", "polozhenie_mery_disc_ogps.txt"),
    ("Pol_o_chelenstve_10042026_srogen_zam (2).doc", "pol_chlenstvo_ogps.doc", "polozhenie_chlenstvo_ogps.txt"),
    ("Pol_o_jalobakh_10042026_srogen_zam.doc", "pol_zhaloby_ogps.doc", "polozhenie_zhaloby_ogps.txt"),
    ("pol_o_poryadke_uved_ogps_18052026.docx", "pol_uved_dogovor_ogps.docx", "polozhenie_uved_dogovor_ogps.txt"),
    ("Pol_o_reestre_srogen_10042026_zam.docx", "pol_reestr_ogps.docx", "polozhenie_reestr_ogps.txt"),
    ("standart_srogen_2019.docx", "standart_srogen_2019.docx", "standart_assotsiatsii_ogps.txt"),
    ("Ustav_SROGEN_16012023.pdf", "ustav_srogen_16012023.pdf", "ustav_ogps.txt"),
    ("vv_ogps_16032026.doc", "strah_go_vv_ogps.doc", "polozhenie_strah_go_ogps.txt"),
]


def cyr(s: str) -> int:
    return sum(1 for c in s if "\u0400" <= c <= "\u04FF")


def clean(s: str) -> str:
    s = s.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    # strip leftover xml tags from crude docx extract
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()


def from_ole(path: Path) -> str:
    ole = olefile.OleFileIO(str(path))
    try:
        data = ole.openstream("WordDocument").read()
    finally:
        ole.close()
    blocks: list[str] = []
    i = 0
    buf = bytearray()
    n = len(data)

    def keep(ch: int) -> bool:
        if 0x0400 <= ch <= 0x04FF:
            return True
        if ch in (0x09, 0x0A, 0x0D, 0x20, 0xA0):
            return True
        if 0x21 <= ch <= 0x7E:
            return True
        return ch in (0xAB, 0xBB, 0x2013, 0x2014, 0x201C, 0x201D, 0x2026, 0x2116, 0x00B0, 0x00A7)

    def flush() -> None:
        nonlocal buf
        if len(buf) < 12:
            buf = bytearray()
            return
        try:
            t = buf.decode("utf-16le")
        except Exception:
            buf = bytearray()
            return
        if cyr(t) > 0:
            blocks.append(t)
        buf = bytearray()

    while i + 1 < n:
        ch = data[i] | (data[i + 1] << 8)
        if keep(ch):
            buf += struct.pack("<H", ch)
            i += 2
        else:
            flush()
            i += 1
    flush()
    return "\n".join(blocks)


def from_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
    texts = re.findall(r"<w:t[^>]*>(.*?)</w:t>", xml)
    # unescape basic entities
    out = []
    for t in texts:
        t = t.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
        out.append(t)
    return " ".join(out)


def from_pdf(path: Path) -> str:
    from pypdf import PdfReader

    r = PdfReader(str(path))
    parts = []
    for page in r.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts)


def extract(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".doc":
        return from_ole(path)
    if ext == ".docx":
        return from_docx(path)
    if ext == ".pdf":
        return from_pdf(path)
    raise ValueError(ext)


def main() -> None:
    SRC.mkdir(parents=True, exist_ok=True)
    DOCS_QA.mkdir(parents=True, exist_ok=True)
    for desk_name, src_name, txt_name in FILES:
        desk = DESK / desk_name
        if not desk.is_file():
            raise FileNotFoundError(desk)
        src_path = SRC / src_name
        shutil.copy2(desk, src_path)
        text = clean(extract(desk if desk.suffix.lower() != ".doc" else src_path))
        if cyr(text) < 200:
            raise ValueError(f"too little cyrillic: {txt_name} cyr={cyr(text)}")
        out = DOCS_QA / txt_name
        out.write_text(text + "\n", encoding="utf-8")
        print(f"{txt_name}: chars={len(text)} cyr={cyr(text)}")
    print("extract_ok")


if __name__ == "__main__":
    main()
