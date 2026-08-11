#!/usr/bin/env python3
"""Peek titles/snippets from docs folder (no bot install)."""
from __future__ import annotations

import re
import struct
import zipfile
from pathlib import Path

import olefile

DIR = Path(r"C:\Users\User\Desktop\файлы для добавление в бота сро")


def cyr(s: str) -> int:
    return sum(1 for c in s if "\u0400" <= c <= "\u04FF")


def clean(s: str) -> str:
    s = s.replace("\xa0", " ").replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def snippet(s: str, n: int = 700) -> str:
    s = clean(s)
    return s[:n] + ("…" if len(s) > n else "")


def from_ole(path: Path) -> str:
    ole = olefile.OleFileIO(str(path))
    try:
        data = ole.openstream("WordDocument").read()
    finally:
        ole.close()
    blocks = []
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
        return ch in (0xAB, 0xBB, 0x2013, 0x2014, 0x201C, 0x201D, 0x2026, 0x2116)

    def flush():
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
    return " ".join(texts)


def from_pdf(path: Path) -> str:
    from pypdf import PdfReader

    r = PdfReader(str(path))
    parts = []
    for i, page in enumerate(r.pages[:4]):
        parts.append(page.extract_text() or "")
    return "\n".join(parts)


def main():
    for path in sorted(DIR.iterdir()):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        try:
            if ext == ".doc":
                text = from_ole(path)
            elif ext == ".docx":
                text = from_docx(path)
            elif ext == ".pdf":
                text = from_pdf(path)
            else:
                print(f"=== {path.name}: skip {ext}")
                continue
        except Exception as e:
            print(f"=== {path.name}: ERROR {e}")
            continue
        print(f"=== {path.name} ({path.stat().st_size} bytes, cyr={cyr(text)}, len={len(text)})")
        print(snippet(text, 650))
        print()


if __name__ == "__main__":
    main()
