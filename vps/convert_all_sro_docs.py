# -*- coding: utf-8 -*-
"""Конвертация docs_qa/_raw/{suffix}/* → docs_qa/*.txt (LibreOffice / docx / pdf)."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = ROOT / "sro files" / "docs_qa" / "_raw"
OUT = ROOT / "sro files" / "docs_qa"
SOFFICE = Path(r"C:\Program Files\LibreOffice\program\soffice.exe")

# Не конвертировать гигантские PDF-уставы (сканы) — слишком тяжело для DocQA
MAX_PDF_BYTES = 4_000_000


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
        elif tag in ("br", "cr", "p"):
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
        if i >= 80:  # safety
            parts.append("…")
            break
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
        timeout=240,
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


def convert_one(src: Path, tmp: Path) -> Path | None:
    out_name = src.stem + ".txt"
    out = OUT / out_name
    if out.is_file() and out.stat().st_size > 500:
        # already have decent txt
        return out
    suf = src.suffix.lower()
    if suf == ".pdf" and src.stat().st_size > MAX_PDF_BYTES:
        print(f"skip huge pdf {src.name} ({src.stat().st_size})")
        return None
    try:
        if suf == ".docx":
            text = docx_to_text(src)
        elif suf == ".pdf":
            text = pdf_to_text(src)
        else:
            text = soffice_to_text(src, tmp)
        text = text.replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"
        if len(text) < 400:
            print(f"too short {src.name}: {len(text)}")
            return None
        out.write_text(text, encoding="utf-8")
        print(f"ok {out.name}: {len(text)} chars")
        return out
    except Exception as e:
        print(f"FAIL {src.name}: {e}")
        return None


def main() -> None:
    if not SOFFICE.is_file():
        raise SystemExit(f"no soffice: {SOFFICE}")
    OUT.mkdir(parents=True, exist_ok=True)
    files = sorted(RAW_ROOT.glob("*/*.*"))
    files = [p for p in files if p.suffix.lower() in {".doc", ".docx", ".pdf", ".rtf"}]
    print(f"to convert: {len(files)}")
    with tempfile.TemporaryDirectory(prefix="sro_docs_all_") as tmp_s:
        tmp = Path(tmp_s)
        ok = 0
        for i, src in enumerate(files, 1):
            print(f"[{i}/{len(files)}] {src.parent.name}/{src.name}")
            if convert_one(src, tmp):
                ok += 1
    print(f"done ok={ok}/{len(files)}")


if __name__ == "__main__":
    main()
