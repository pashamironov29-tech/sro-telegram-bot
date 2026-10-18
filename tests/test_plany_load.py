"""Загрузка планов проверок: одна кривая строка не обнуляет папку plany."""

from __future__ import annotations

import os

import log_redact

# Импорт оболочки не должен заворачивать stdout pytest и писать bot_errors.log.
# Подмена только на время импорта: тесты log_redact зовут настоящую функцию.
_real_install = log_redact.install_secret_log_redaction
log_redact.install_secret_log_redaction = lambda *a, **k: None  # type: ignore[method-assign]
import bot_FINAL_GOLD  # noqa: E402

log_redact.install_secret_log_redaction = _real_install
from docx import Document  # noqa: E402


def _write_plan(path, rows: list[list[str]]) -> None:
    doc = Document()
    width = max(len(row) for row in rows)
    table = doc.add_table(rows=0, cols=width)
    for values in rows:
        row = table.add_row()
        for index, value in enumerate(values):
            row.cells[index].text = value
    doc.save(path)


def test_two_cell_plan_row_does_not_abort_folder(tmp_path, monkeypatch):
    plany = tmp_path / "plany"
    plany.mkdir()
    # Строка из двух ячеек раньше звала list.isdigit() и обрывала всю папку.
    _write_plan(
        plany / "OGPS.docx",
        [
            ["Февраль"],
            ["ООО До", "7700000001"],
            ["Март", "2026"],
            ["ООО После", "7700000002", "Москва"],
        ],
    )
    _write_plan(
        plany / "OGPP.docx",
        [
            ["Апрель"],
            ["ООО Другое", "7700000003", "Тула"],
        ],
    )
    (plany / "ZZZ.docx").write_bytes(b"not a docx")
    real_listdir = bot_FINAL_GOLD.os.listdir

    def _listdir(path):
        if os.path.abspath(path) == os.path.abspath(plany):
            return ["ZZZ.docx", "OGPS.docx", "OGPP.docx"]
        return real_listdir(path)

    monkeypatch.setattr(bot_FINAL_GOLD.os, "listdir", _listdir)

    data = bot_FINAL_GOLD.load_plany_folder(str(plany))

    assert data["7700000001"]["name"] == "ООО До"
    assert "Февраль" in data["7700000001"]["month"]
    assert data["7700000002"]["name"] == "ООО После"
    assert "Март" in data["7700000002"]["month"]
    assert data["7700000003"]["name"] == "ООО Другое"
    assert "Апрель" in data["7700000003"]["month"]
