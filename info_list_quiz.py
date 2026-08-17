"""Опрос для информационного листа: ответы пользователя → поля Word.

Пилот: по умолчанию админы и контролёры. Всем — INFO_LIST_QUIZ_FOR_ALL = True.
Отправка готового .docx на почту — отдельным шагом, здесь только Word в чат.
"""

from __future__ import annotations

from typing import Any

# Пилот опроса. False = как раньше (сразу файл из реестра / пустой шаблон).
INFO_LIST_QUIZ_ENABLED = True
# False = только админы и контролёры (тест). True = всем, у кого есть ИНН.
INFO_LIST_QUIZ_FOR_ALL = False

ILQ_SKIP_BTN = "⏭ Пропустить"
ILQ_CANCEL_BTN = "❌ Отмена опроса"
SKIP_TOKENS = frozenset({"-", "—", "–", "пропустить", "нет", "не знаю", ILQ_SKIP_BTN.lower()})
CANCEL_TOKENS = frozenset({"отмена", "cancel", "/cancel", ILQ_CANCEL_BTN.lower()})

SAME_LEGAL = frozenset(
    {
        "как юр",
        "как юр.",
        "как юридический",
        "как юр адрес",
        "как юр. адрес",
        "тот же",
        "то же",
        "совпадает",
        "юридический",
    }
)
SAME_FACT = frozenset(
    {
        "как факт",
        "как факт.",
        "как фактический",
        "как факт адрес",
        "как факт. адрес",
        "фактический",
    }
)

# chat_id -> {step, inn, sro_id, answers}
_sessions: dict[int, dict[str, Any]] = {}

STEPS: tuple[tuple[str, str], ...] = (
    (
        "fact_address",
        "1️⃣ <b>Фактический адрес</b> организации?\n"
        "Напишите адрес, «как юр.» если совпадает с юридическим, или нажмите «Пропустить».",
    ),
    (
        "post_address",
        "2️⃣ <b>Почтовый адрес</b>?\n"
        "Адрес, «как юр.», «как факт.» или «Пропустить».",
    ),
    (
        "org_phone",
        "3️⃣ <b>Публичный телефон</b> организации?\n"
        "Например: +7 (495) 123-45-67",
    ),
    (
        "org_email",
        "4️⃣ <b>E-mail организации</b>?",
    ),
    (
        "director_mobile",
        "5️⃣ <b>Мобильный телефон руководителя</b>?",
    ),
    (
        "director_email",
        "6️⃣ <b>E-mail руководителя</b>?",
    ),
    (
        "accountant",
        "7️⃣ <b>Главный бухгалтер</b> — одной строкой через запятую:\n"
        "<code>ФИО, мобильный, e-mail</code>\n"
        "Пример: <code>Иванова И.И., +7 999 123-45-67, buh@mail.ru</code>",
    ),
    (
        "responsible",
        "8️⃣ <b>Ответственный за взаимодействие с СРО</b> — через запятую:\n"
        "<code>должность, ФИО, мобильный, e-mail</code>\n"
        "Пример: <code>Инженер, Петров П.П., +7 900 111-22-33, sro@firma.ru</code>",
    ),
    (
        "specialists",
        "9️⃣ <b>Специалисты НРС</b> — каждый с новой строки:\n"
        "<code>должность, ФИО, № в НРС</code>\n"
        "Пример:\n<code>Главный инженер, Сидоров С.С., С-77-123456</code>",
    ),
    (
        "insurance_extra",
        "🔟 <b>Договор страхования</b> — через запятую:\n"
        "<code>номер, дата с, дата по</code>\n"
        "Пример: <code>123/2026, 01.01.2026, 31.12.2026</code>\n"
        "Страховую компанию и сумму возьму из реестра, если они там есть.",
    ),
)


def can_use_info_list_quiz(chat_id: int) -> bool:
    if not INFO_LIST_QUIZ_ENABLED:
        return False
    for_all = INFO_LIST_QUIZ_FOR_ALL
    try:
        from config_keys import INFO_LIST_QUIZ_FOR_ALL as _cfg_flag
        for_all = bool(_cfg_flag)
    except Exception:
        pass
    if for_all:
        return True
    try:
        from users_log import is_bot_admin
        from controller_access import is_controller
    except Exception:
        return False
    return bool(is_bot_admin(chat_id) or is_controller(chat_id))


def is_info_list_quiz_active(chat_id: int) -> bool:
    return chat_id in _sessions


def cancel_info_list_quiz(chat_id: int) -> bool:
    return _sessions.pop(chat_id, None) is not None


def start_info_list_quiz(chat_id: int, inn: str, sro_id: str | None) -> str:
    _sessions[chat_id] = {
        "step": 0,
        "inn": inn,
        "sro_id": sro_id or "",
        "answers": {},
    }
    intro = (
        "✍️ <b>Заполним информационный лист вопросами</b> (10 штук).\n\n"
        "Из реестра уже подставлю: название, ИНН, юр. адрес, руководитель, "
        "страховую компанию и сумму (если есть).\n"
        "На любой вопрос — «Пропустить» или «-».\n"
        "<i>Готовый Word пришлю в чат. Отправка на почту — позже.</i>\n\n"
    )
    return intro + STEPS[0][1]


def _is_skip(text: str) -> bool:
    t = (text or "").strip().lower()
    return t in SKIP_TOKENS or t.startswith("пропуст")


def _is_cancel(text: str) -> bool:
    return (text or "").strip().lower() in CANCEL_TOKENS


def _split_csv(text: str, max_parts: int) -> list[str]:
    parts = [p.strip() for p in text.split(",")]
    parts = [p for p in parts if p]
    if len(parts) <= max_parts:
        return parts
    head, tail = parts[: max_parts - 1], parts[max_parts - 1 :]
    return head + [", ".join(tail)]


def _parse_accountant(text: str) -> dict[str, str]:
    parts = _split_csv(text, 3)
    out: dict[str, str] = {}
    if not parts:
        return out
    out["accountant_fio"] = parts[0]
    if len(parts) >= 2:
        out["accountant_phone"] = parts[1]
    if len(parts) >= 3:
        out["accountant_email"] = parts[2]
    return out


def _parse_responsible(text: str) -> dict[str, str]:
    parts = _split_csv(text, 4)
    out: dict[str, str] = {}
    if not parts:
        return out
    if len(parts) == 1:
        out["responsible_fio"] = parts[0]
    elif len(parts) == 2:
        out["responsible_position"] = parts[0]
        out["responsible_fio"] = parts[1]
    elif len(parts) == 3:
        out["responsible_fio"] = parts[0]
        out["responsible_phone"] = parts[1]
        out["responsible_email"] = parts[2]
    else:
        out["responsible_position"] = parts[0]
        out["responsible_fio"] = parts[1]
        out["responsible_phone"] = parts[2]
        out["responsible_email"] = parts[3]
    return out


def _parse_insurance(text: str) -> dict[str, str]:
    parts = _split_csv(text, 3)
    out: dict[str, str] = {}
    if not parts:
        return out
    out["insurance_contract"] = parts[0]
    if len(parts) >= 2:
        out["insurance_from"] = parts[1]
    if len(parts) >= 3:
        out["insurance_to"] = parts[2]
    return out


def _store_step(answers: dict[str, str], key: str, raw: str) -> None:
    text = (raw or "").strip()
    if key == "accountant":
        answers.update(_parse_accountant(text))
        return
    if key == "responsible":
        answers.update(_parse_responsible(text))
        return
    if key == "insurance_extra":
        answers.update(_parse_insurance(text))
        return
    answers[key] = text


def resolve_quiz_addresses(form_data: dict, answers: dict[str, str]) -> dict[str, str]:
    """Раскрывает «как юр.» / «как факт.» относительно данных реестра."""
    out = dict(answers)
    legal = (form_data.get("location") or "").strip()

    fact_raw = (out.get("fact_address") or "").strip()
    if fact_raw.lower() in SAME_LEGAL:
        out["fact_address"] = legal
    fact = (out.get("fact_address") or "").strip()

    post_raw = (out.get("post_address") or "").strip()
    post_low = post_raw.lower()
    if post_low in SAME_LEGAL:
        out["post_address"] = legal
    elif post_low in SAME_FACT:
        out["post_address"] = fact or legal
    return out


def apply_info_list_quiz_answer(chat_id: int, user_text: str) -> dict[str, Any]:
    """kind: question | done | cancelled | inactive"""
    sess = _sessions.get(chat_id)
    if not sess:
        return {"kind": "inactive"}
    if _is_cancel(user_text):
        cancel_info_list_quiz(chat_id)
        return {"kind": "cancelled"}

    step = int(sess.get("step") or 0)
    if step >= len(STEPS):
        extra = dict(sess.get("answers") or {})
        inn = sess.get("inn")
        sro_id = sess.get("sro_id")
        cancel_info_list_quiz(chat_id)
        return {"kind": "done", "extra": extra, "inn": inn, "sro_id": sro_id}

    key = STEPS[step][0]
    if not _is_skip(user_text):
        _store_step(sess.setdefault("answers", {}), key, user_text)

    sess["step"] = step + 1
    if sess["step"] >= len(STEPS):
        extra = dict(sess.get("answers") or {})
        inn = sess.get("inn")
        sro_id = sess.get("sro_id")
        cancel_info_list_quiz(chat_id)
        return {"kind": "done", "extra": extra, "inn": inn, "sro_id": sro_id}

    return {"kind": "question", "text": STEPS[sess["step"]][1]}