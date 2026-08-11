# -*- coding: utf-8 -*-
from pathlib import Path

path = Path(r"C:\Users\User\OneDrive\Рабочие\GOLD\doc_qa.py")
text = path.read_text(encoding="utf-8")
start = text.index("def format_doc_qa_intro(")
end = text.index("\n_DOC_ASK_MODE:")
fixed = '''def format_doc_qa_intro(sro_id: str | None = None) -> str:
    """Подсказка раздела Документы — только тексты выбранного СРО (+ ГрК)."""
    sid = (sro_id or "").strip().upper() or None
    name = DOC_QA_SRO_TEXTS.get(sid or "")
    if name:
        return (
            f"📕 <b>Документы — {name}</b>\\n\\n"
            f"Ищем только в текстах <b>{name}</b> и в Градкодексе РФ.\\n\\n"
            f"<b>В базе:</b>\\n"
            f"• Градостроительный кодекс РФ\\n"
            f"• Положения {name}: {_POL_KINDS}\\n\\n"
            "⬇️ Напишите вопрос в чат или нажмите «💬 Спросить по документам».\\n\\n"
            f"{DOC_QA_DISCLAIMER}"
        )
    if sid:
        listed = ", ".join(DOC_QA_SRO_TEXTS.values())
        return (
            "📕 <b>Документы</b>\\n\\n"
            "Для выбранного СРО текстов положений в боте пока нет "
            f"(есть: {listed}).\\n"
            "Доступен <b>Градостроительный кодекс РФ</b> — можно спросить по нему.\\n\\n"
            "⬇️ Напишите вопрос по ГрК или смените СРО.\\n\\n"
            f"{DOC_QA_DISCLAIMER}"
        )
    return (
        "📕 <b>Документы СРО</b>\\n\\n"
        "Сначала выберите СРО (ИНН / контекст) — тогда поиск пойдёт "
        "по положениям <b>вашего</b> СРО.\\n"
        "Тексты положений есть для всех 15 партнёрских СРО.\\n"
        "Без выбора СРО доступен Градкодекс РФ.\\n\\n"
        "⬇️ Напишите вопрос в чат или нажмите «💬 Спросить по документам».\\n\\n"
        f"{DOC_QA_DISCLAIMER}"
    )


def format_doc_qa_hint(sro_id: str | None = None) -> str:
    sid = (sro_id or "").strip().upper() or None
    name = DOC_QA_SRO_TEXTS.get(sid or "")
    if name:
        return (
            f"📕 <b>Вопросы по документам — {name}</b>\\n\\n"
            f"Короткий ответ <b>только по тексту</b> {name} или Градкодекса.\\n\\n"
            f"<b>В базе:</b>\\n"
            f"• Градостроительный кодекс РФ\\n"
            f"• Положения {name}: {_POL_KINDS}\\n\\n"
            "Примеры: «состав сведений реестра», «срок устранения нарушений», "
            "«что такое КФ ВВ».\\n\\n"
            f"{DOC_QA_DISCLAIMER}\\n\\n"
            "«⬅️ Назад в меню» — выход."
        )
    if sid:
        return (
            "📕 <b>Вопросы по документам</b>\\n\\n"
            "Положений вашего СРО в боте пока нет. Можно спросить по "
            "<b>Градостроительному кодексу РФ</b>.\\n\\n"
            f"{DOC_QA_DISCLAIMER}\\n\\n"
            "«⬅️ Назад в меню» — выход."
        )
    return (
        "📕 <b>Вопросы по документам</b>\\n\\n"
        "Выберите СРО в контексте — поиск пойдёт по его положениям "
        "(тексты есть у всех 15 партнёрских СРО).\\n\\n"
        f"{DOC_QA_DISCLAIMER}\\n\\n"
        "«⬅️ Назад в меню» — выход."
    )


# совместимость со старыми импортами
DOC_QA_HINT = format_doc_qa_hint(None)
DOC_QA_INTRO = format_doc_qa_intro(None)
'''
# The fixed string uses \\n which in the source file written by this script
# should become \n escape sequences in the target Python file.
# When we write fixed to disk as part of text, we want the target file to contain
# the two characters \ and n inside the string literals.
path.write_text(text[:start] + fixed + text[end:], encoding="utf-8")
# Verify compile
compile(path.read_text(encoding="utf-8"), str(path), "exec")
print("fixed ok")
