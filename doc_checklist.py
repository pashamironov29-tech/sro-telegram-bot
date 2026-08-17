"""Памятка документов к проверке: контролёр задаёт список, организация отмечает галочки.

Пилот для демо: включается флагом DOC_CHECKLIST_ENABLED в config_keys.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

DOC_CHECKLIST_BUTTON = "📋 Памятка к проверке"
DOC_CHECKLIST_HINT_BUTTON = "🧠 Что собрать?"

DEFAULT_ITEMS: tuple[tuple[str, str], ...] = (
    ("dover", "Доверенность на проверку"),
    ("info", "Информационный лист"),
    ("ustav", "Учредительные документы (если были изменения)"),
    ("strah", "Договор и полис страхования"),
    ("nrs", "Документы специалистов НРС"),
    ("kach", "Документы по контролю качества работ"),
)

HINTS = {
    "plan": (
        "📋 <b>Плановая проверка — что обычно просят</b>\n\n"
        "1. <b>Доверенность</b> на представителя (бланк есть в боте).\n"
        "2. <b>Информационный лист</b> на день проверки (можно заполнить вопросами).\n"
        "3. <b>Страхование</b> — действующий договор и полис, сроки не просрочены.\n"
        "4. <b>Специалисты НРС</b> — дипломы, трудовые, НОК, должностные; сверить номера в НРС.\n"
        "5. <b>Учредительные</b> — только если с прошлой проверки менялись устав / ЕГРЮЛ / руководитель.\n"
        "6. <b>Контроль качества</b> — порядок/регламент, приказы, журналы по работам.\n\n"
        "Жалоба / текущий контроль в этом году <b>не заменяют</b> плановую: организацию в план оставляют."
    ),
    "complaint": (
        "📋 <b>Жалоба / внеплановая — акцент не на всём пакете</b>\n\n"
        "• Доверенность и информационный лист — как обычно.\n"
        "• Документы <b>по предмету жалобы</b>: договор подряда, акты, исполнительная, переписка.\n"
        "• Специалисты и страхование — если жалоба про допуск / ответственность.\n"
        "• Не раздувать список «на всякий случай»: только то, без чего нельзя разобрать обращение.\n\n"
        "Организацию из годового плана из‑за жалобы <b>не убирают</b>."
    ),
    "change": (
        "📋 <b>Изменения в реестре / сведениях</b>\n\n"
        "• Заявление о внесении изменений (бланк в боте — без автозаполнения причины).\n"
        "• Новый устав / лист ЕГРЮЛ / решение о руководителе — по сути изменения.\n"
        "• Информационный лист с актуальными адресами, телефонами, НРС.\n"
        "• Если менялись специалисты — пакет НРС на новых лиц."
    ),
}

_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "doc_checklists.json")
_await_add: dict[int, str] = {}


def checklist_enabled() -> bool:
    try:
        from config_keys import DOC_CHECKLIST_ENABLED

        return bool(DOC_CHECKLIST_ENABLED)
    except Exception:
        return False


def _load() -> dict[str, Any]:
    try:
        with open(_STORE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return {}


def _save(data: dict[str, Any]) -> None:
    tmp = _STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _STORE)


def get_checklist(inn: str) -> dict[str, Any] | None:
    inn = re.sub(r"\D", "", inn or "")
    if not inn:
        return None
    rec = _load().get(inn)
    return rec if isinstance(rec, dict) else None


def create_default(inn: str, *, sro_id: str = "", by: int = 0, title: str = "") -> dict[str, Any]:
    inn = re.sub(r"\D", "", inn or "")
    rec = {
        "inn": inn,
        "sro_id": sro_id or "",
        "title": title or "",
        "created_by": int(by) if by else 0,
        "updated": int(time.time()),
        "items": [{"id": i, "title": t, "done": False} for i, t in DEFAULT_ITEMS],
    }
    data = _load()
    data[inn] = rec
    _save(data)
    return rec


def toggle_item(inn: str, item_id: str) -> dict[str, Any] | None:
    inn = re.sub(r"\D", "", inn or "")
    data = _load()
    rec = data.get(inn)
    if not isinstance(rec, dict):
        return None
    for item in rec.get("items") or []:
        if str(item.get("id")) == str(item_id):
            item["done"] = not bool(item.get("done"))
            rec["updated"] = int(time.time())
            data[inn] = rec
            _save(data)
            return rec
    return rec


def add_item(inn: str, title: str) -> dict[str, Any] | None:
    inn = re.sub(r"\D", "", inn or "")
    title = (title or "").strip()
    if not inn or not title or len(title) > 200:
        return None
    data = _load()
    rec = data.get(inn)
    if not isinstance(rec, dict):
        rec = create_default(inn)
        data = _load()
        rec = data.get(inn) or rec
    items = list(rec.get("items") or [])
    n = 1 + sum(1 for x in items if str(x.get("id", "")).startswith("x"))
    items.append({"id": f"x{n}", "title": title, "done": False})
    rec["items"] = items
    rec["updated"] = int(time.time())
    data[inn] = rec
    _save(data)
    return rec


def delete_checklist(inn: str) -> None:
    inn = re.sub(r"\D", "", inn or "")
    data = _load()
    data.pop(inn, None)
    _save(data)


def begin_await_add(chat_id: int, inn: str) -> None:
    _await_add[int(chat_id)] = re.sub(r"\D", "", inn or "")


def cancel_await_add(chat_id: int) -> None:
    _await_add.pop(int(chat_id), None)


def awaiting_add_inn(chat_id: int) -> str | None:
    return _await_add.get(int(chat_id))


def format_checklist_text(rec: dict[str, Any], *, org_name: str = "") -> str:
    items = rec.get("items") or []
    done = sum(1 for x in items if x.get("done"))
    total = len(items)
    inn = rec.get("inn") or ""
    name = org_name or rec.get("title") or ""
    head = "📋 <b>Памятка документов к проверке</b>\n"
    if name:
        head += f"{name}\n"
    head += f"ИНН <code>{inn}</code> · собрано <b>{done}/{total}</b>\n\n"
    lines = []
    for item in items:
        mark = "✅" if item.get("done") else "⬜"
        lines.append(f"{mark} {item.get('title') or '—'}")
    tail = (
        "\n\n<i>Нажмите пункт — галочка «есть / нет». "
        "Контролёр задаёт список, организация отмечает, что уже собрали.</i>"
    )
    return head + "\n".join(lines) + tail


def hint_text(kind: str) -> str:
    return HINTS.get(kind) or HINTS["plan"]