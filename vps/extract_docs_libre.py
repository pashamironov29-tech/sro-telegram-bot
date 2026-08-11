#!/usr/bin/env python3
"""Convert .doc via LibreOffice to txt in sro files/docs_qa/."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

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


def main() -> None:
    if not SOFFICE.is_file():
        raise SystemExit(f"no soffice: {SOFFICE}")
    SRC.mkdir(parents=True, exist_ok=True)
    DOCS_QA.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="doc_qa_") as tmp:
        tmp_path = Path(tmp)
        for desktop_path, src_name, txt_name in FILES:
            if not desktop_path.is_file():
                raise FileNotFoundError(desktop_path)
            src_path = SRC / src_name
            shutil.copy2(desktop_path, src_path)
            work = tmp_path / src_name
            shutil.copy2(src_path, work)
            # Convert to txt
            subprocess.run(
                [
                    str(SOFFICE),
                    "--headless",
                    "--nologo",
                    "--nofirststartwizard",
                    "--convert-to",
                    "txt:Text",
                    "--outdir",
                    str(tmp_path),
                    str(work),
                ],
                check=True,
                timeout=120,
            )
            produced = work.with_suffix(".txt")
            if not produced.is_file():
                # LibreOffice may use different stem
                candidates = list(tmp_path.glob("*.txt"))
                if not candidates:
                    raise FileNotFoundError(f"no txt for {src_name}")
                produced = candidates[0]
            text = produced.read_text(encoding="utf-8", errors="ignore")
            if len(text.strip()) < 200:
                # try utf-16 / cp1251
                raw = produced.read_bytes()
                for enc in ("utf-16", "cp1251", "latin-1"):
                    try:
                        text = raw.decode(enc)
                        if len(text.strip()) > 200:
                            break
                    except Exception:
                        continue
            out = DOCS_QA / txt_name
            out.write_text(text.replace("\r\n", "\n").replace("\r", "\n"), encoding="utf-8")
            print(f"{txt_name}: {len(text)} chars")
            # cleanup leftover txt in tmp so next file isn't confused
            for t in tmp_path.glob("*.txt"):
                t.unlink(missing_ok=True)
    print("extract_ok")


if __name__ == "__main__":
    main()
