#!/usr/bin/env python3
"""Extract Russian text from .doc via LibreOffice HTML (+ OLE fallback)."""
from __future__ import annotations

import re
import shutil
import struct
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path

import olefile

ROOT = Path(__file__).resolve().parents[1]
DOCS_QA = ROOT / "sro files" / "docs_qa"
SRC = DOCS_QA / "sources"
DESKTOP = Path.home() / "Desktop"
SOFFICE = Path(r"C:\Program Files\LibreOffice\program\soffice.exe")

FILES = [
    (
        DESKTOP / "kontrol_ogps_30062022 (1).doc",
        "kontrol_ogps_30062022.doc",
        "polozhenie_kontrol_ogps.txt",
    ),
    (
        DESKTOP / "polozhenie_kk_2019_01_21_ogps (1).doc",
        "polozhenie_kk_2019_01_21_ogps.doc",
        "polozhenie_kk_ogps.txt",
    ),
]


class _HtmlText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip = True
        if tag in ("br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = False
        if tag in ("p", "div", "tr", "li", "h1", "h2", "h3", "h4", "table"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip and data:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _HtmlText()
    parser.feed(html)
    text = "".join(parser.parts)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _is_keep_char(ch: int) -> bool:
    if 0x0400 <= ch <= 0x04FF:
        return True
    if ch in (0x09, 0x0A, 0x0D, 0x20, 0xA0):
        return True
    if 0x21 <= ch <= 0x7E:
        return True
    if ch in (0xAB, 0xBB, 0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D, 0x2026, 0x2116, 0x00B0, 0x00A7):
        return True
    return False


def extract_ole_utf16(path: Path) -> str:
    ole = olefile.OleFileIO(str(path))
    try:
        data = ole.openstream("WordDocument").read()
    finally:
        ole.close()
    blocks: list[str] = []
    i = 0
    buf = bytearray()
    n = len(data)

    def flush() -> None:
        nonlocal buf
        if len(buf) < 12:
            buf = bytearray()
            return
        try:
            s = buf.decode("utf-16le")
        except Exception:
            buf = bytearray()
            return
        if any("\u0400" <= c <= "\u04FF" for c in s):
            blocks.append(s)
        buf = bytearray()

    while i + 1 < n:
        ch = data[i] | (data[i + 1] << 8)
        if _is_keep_char(ch):
            buf += struct.pack("<H", ch)
            i += 2
        else:
            flush()
            i += 1
    flush()
    text = "\n".join(blocks)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def cyr_count(s: str) -> int:
    return sum(1 for c in s if "\u0400" <= c <= "\u04FF")


def convert_via_libreoffice(doc_path: Path, out_dir: Path) -> str | None:
    if not SOFFICE.is_file():
        return None
    work = out_dir / doc_path.name
    shutil.copy2(doc_path, work)
    subprocess.run(
        [
            str(SOFFICE),
            "--headless",
            "--nologo",
            "--nofirststartwizard",
            "--convert-to",
            "html:HTML:EmbedImages",
            "--outdir",
            str(out_dir),
            str(work),
        ],
        check=True,
        timeout=180,
    )
    html_path = work.with_suffix(".html")
    if not html_path.is_file():
        found = list(out_dir.glob("*.html"))
        if not found:
            return None
        html_path = found[0]
    html = html_path.read_text(encoding="utf-8", errors="replace")
    return html_to_text(html)


def extract_best(doc_path: Path, tmp: Path) -> str:
    html_text = None
    try:
        html_text = convert_via_libreoffice(doc_path, tmp)
    except Exception as e:
        print(f"  libreoffice failed: {e}")
    ole_text = extract_ole_utf16(doc_path)

    candidates = []
    if html_text and cyr_count(html_text) >= 200:
        candidates.append(("html", html_text))
    if ole_text and cyr_count(ole_text) >= 200:
        candidates.append(("ole", ole_text))
    if not candidates:
        raise ValueError(f"no usable text from {doc_path.name}")

    # Prefer longer Cyrillic, then longer overall
    name, text = max(candidates, key=lambda x: (cyr_count(x[1]), len(x[1])))
    print(f"  chosen={name} cyr={cyr_count(text)} chars={len(text)}")
    return text


def main() -> None:
    SRC.mkdir(parents=True, exist_ok=True)
    DOCS_QA.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="doc_qa_") as tmp:
        tmp_path = Path(tmp)
        for desktop_path, src_name, txt_name in FILES:
            if not desktop_path.is_file():
                raise FileNotFoundError(desktop_path)
            src_path = SRC / src_name
            shutil.copy2(desktop_path, src_path)
            # fresh subdir per file so html names don't collide
            sub = tmp_path / src_name.replace(".", "_")
            sub.mkdir()
            print(txt_name)
            text = extract_best(src_path, sub)
            out = DOCS_QA / txt_name
            out.write_text(text + "\n", encoding="utf-8")
            print(f"  wrote {out.name}")
    print("extract_ok")


if __name__ == "__main__":
    main()
