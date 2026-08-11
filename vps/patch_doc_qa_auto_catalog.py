# -*- coding: utf-8 -*-
"""Patch doc_qa.py: auto-catalog for all SRO docs."""
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "doc_qa.py"
text = path.read_text(encoding="utf-8")

# 1) Replace SRO texts + helpers through DOC_QA_INTRO assignment
start = text.index("# СРО, для которых лежат тексты положений в docs_qa")
end = text.index("\n_DOC_ASK_MODE:")
new_head = '''# СРО, для которых лежат тексты положений в docs_qa
DOC_QA_SRO_TEXTS = {
    "OGPS": "ОГПС",
    "OGPP": "ОГПП",
    "GEOIND": "ГеоИндустрия",
    "MOTS": "МОТС",
    "OSO": "ОСО",
    "SPROF": "СПРОФ",
    "PRIIS": "ПРИИС",
    "OPP": "ОПП",
    "NOSO": "НОСО",
    "OSOES": "ОСОЕС",
    "OSOT": "ОСОТ",
    "SOVS": "ОСОВС",
    "OGPO": "ОГПО",
    "MGEO": "МГЕО",
    "GPS": "ГПС",
}

# суффикс файла → id СРО
_DOC_SUFFIX_TO_SRO = {
    "ogps": "OGPS",
    "ogpp": "OGPP",
    "geo": "GEOIND",
    "mots": "MOTS",
    "oso": "OSO",
    "sprof": "SPROF",
    "priis": "PRIIS",
    "opp": "OPP",
    "noso": "NOSO",
    "osoes": "OSOES",
    "osot": "OSOT",
    "sovs": "SOVS",
    "ogpo": "OGPO",
    "mgeo": "MGEO",
    "gps": "GPS",
}

_KIND_TITLE = {
    "ustav": "Устав",
    "standart": "Стандарт ассоциации",
    "chlenstvo": "Положение о членстве",
    "kontrol": "Положение о контроле",
    "kk": "Положение о контрольном комитете",
    "reestr": "Положение о реестре членов",
    "zhaloby": "Положение о рассмотрении жалоб",
    "mery_disc": "Положение о мерах дисциплинарного воздействия",
    "kf_vv": "Положение о КФ возмещения вреда",
    "kf_odo": "Положение о КФ обеспечения договорных обязательств",
    "strah_go": "Положение о страховании гражданской ответственности",
    "strah_odo": "Положение о страховании риска по договорам подряда",
    "uved_dogovor": "Положение о порядке уведомления о договорах подряда",
    "obmen_dok": "Положение об обмене документами",
    "analiz": "Положение об анализе деятельности членов",
    "inform_otkrytost": "Положение об информационной открытости",
}

_POL_KINDS = (
    "членство/взносы, контроль, КК, реестр, жалобы, дисциплина, "
    "КФ ВВ и ОДО, страхование, уведомления о договорах, обмен документами, "
    "анализ, открытость, устав, стандарт"
)


def _parse_doc_stem(stem: str) -> tuple[str, str] | None:
    """stem файла → (kind, suffix) или None."""
    for suf in _DOC_SUFFIX_TO_SRO:
        ending = "_" + suf
        if not stem.endswith(ending):
            continue
        head = stem[: -len(ending)]
        if head == "ustav":
            return "ustav", suf
        if head == "standart_assotsiatsii":
            return "standart", suf
        if head.startswith("polozhenie_"):
            return head[len("polozhenie_") :], suf
    return None


def _sro_for_doc_id(doc_id: str) -> str | None:
    did = (doc_id or "").lower()
    if not did or did == "grk_rf":
        return None
    parsed = _parse_doc_stem(did)
    if parsed:
        return _DOC_SUFFIX_TO_SRO[parsed[1]]
    for suf, sro in _DOC_SUFFIX_TO_SRO.items():
        if did.endswith("_" + suf):
            return sro
    return None


def format_doc_qa_intro(sro_id: str | None = None) -> str:
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
        return (
            f"📕 <b>Документы</b>\\n\\n"
            "Для выбранного СРО текстов положений в боте пока нет "
            f"(есть: {', '.join(DOC_QA_SRO_TEXTS.values())}).\\n"
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
            f"Примеры: «состав сведений реестра», «срок устранения нарушений», "
            f"«что такое КФ ВВ».\\n\\n"
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
# fix double-escaped newlines in the patch file - I used \\n by mistake in the write
new_head = new_head.replace("\\n", "\n")
text = text[:start] + new_head + text[end:]

# 2) Replace _documents() body
start2 = text.index("def _documents() -> list[dict]:")
end2 = text.index("\ndef ensure_grk_text()")
new_docs = '''def _documents() -> list[dict]:
    """Каталог: ГрК + все polozhenie_*/ustav_*/standart_* из docs_qa/."""
    d = _docs_dir()
    docs: list[dict] = [
        {
            "id": "grk_rf",
            "family": "grk",
            "title": "Градостроительный кодекс РФ",
            "path": d / "grk_rf.txt",
            "pdf": _project_root() / "grkodeksrf.pdf",
        }
    ]
    for path in sorted(d.glob("*.txt")):
        if path.name == "grk_rf.txt":
            continue
        parsed = _parse_doc_stem(path.stem)
        if not parsed:
            continue
        kind, suf = parsed
        sro_id = _DOC_SUFFIX_TO_SRO[suf]
        sro_name = DOC_QA_SRO_TEXTS.get(sro_id, sro_id)
        kind_title = _KIND_TITLE.get(kind, kind.replace("_", " "))
        docs.append(
            {
                "id": f"{kind}_{suf}",
                "family": "polozhenie",
                "title": f"{kind_title} {sro_name}",
                "path": path,
            }
        )
    return docs

'''
text = text[:start2] + new_docs + text[end2:]
path.write_text(text, encoding="utf-8")
print("patched", path)
