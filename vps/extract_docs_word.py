#!/usr/bin/env python3
"""Extract .doc text via Word COM into sro files/docs_qa/*.txt"""
from pathlib import Path
import shutil

import win32com.client

ROOT = Path(__file__).resolve().parents[1]
DOCS_QA = ROOT / "sro files" / "docs_qa"
SRC = DOCS_QA / "sources"
DESKTOP = Path.home() / "Desktop"

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
    SRC.mkdir(parents=True, exist_ok=True)
    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    try:
        for desktop_path, src_name, txt_name in FILES:
            if not desktop_path.is_file():
                raise FileNotFoundError(desktop_path)
            src_path = SRC / src_name
            shutil.copy2(desktop_path, src_path)
            doc = word.Documents.Open(str(src_path.resolve()), ReadOnly=True)
            try:
                text = doc.Content.Text or ""
            finally:
                doc.Close(False)
            out = DOCS_QA / txt_name
            out.write_text(text.replace("\r", "\n"), encoding="utf-8")
            print(f"{txt_name}: {len(text)} chars")
    finally:
        word.Quit()
    print("extract_ok")


if __name__ == "__main__":
    main()
