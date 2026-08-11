"""Вопросы по документам (PDF/TXT/DOC): поиск кусков + ответ ИИ только по ним.

Пилот: только для BOT_ADMIN_IDS. Не смешивать с обычным ИИ-помощником (разделы сайта).
"""

from __future__ import annotations

import re
from pathlib import Path

import requests

from bot_disclaimers import DOC_QA_DISCLAIMER

try:
    from config_keys import GROQ_API_KEY as _GROQ
except ImportError:
    _GROQ = ""

try:
    from config_keys import OPENROUTER_API_KEY as _OR_KEY
except ImportError:
    _OR_KEY = ""

try:
    from config_keys import OPENROUTER_MODEL as _OR_MODEL
except ImportError:
    _OR_MODEL = "openai/gpt-4.1-mini"

try:
    from gigachat_client import chat_completion as _gigachat_chat
    from gigachat_client import credentials_configured as _gigachat_ok
except ImportError:
    def _gigachat_ok():
        return False

    def _gigachat_chat(*_a, **_k):
        raise RuntimeError("gigachat_unavailable")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_DEFAULT_MODEL = "openai/gpt-4.1-mini"

# Кнопка в главном меню (для всех)
DOC_QA_BUTTON = "📕 Документы"
DOC_QA_ASK_BUTTON = "💬 Спросить по документам"
DOC_QA_BACK_BUTTON = "⬅️ Назад в меню"

# СРО, для которых лежат тексты положений в docs_qa
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
            f"📕 <b>Документы — {name}</b>\n\n"
            f"Ищем только в текстах <b>{name}</b> и в Градкодексе РФ.\n\n"
            f"<b>В базе:</b>\n"
            f"• Градостроительный кодекс РФ\n"
            f"• Положения {name}: {_POL_KINDS}\n\n"
            "⬇️ Напишите вопрос в чат или нажмите «💬 Спросить по документам».\n\n"
            f"{DOC_QA_DISCLAIMER}"
        )
    if sid:
        listed = ", ".join(DOC_QA_SRO_TEXTS.values())
        return (
            "📕 <b>Документы</b>\n\n"
            "Для выбранного СРО текстов положений в боте пока нет "
            f"(есть: {listed}).\n"
            "Доступен <b>Градостроительный кодекс РФ</b> — можно спросить по нему.\n\n"
            "⬇️ Напишите вопрос по ГрК или смените СРО.\n\n"
            f"{DOC_QA_DISCLAIMER}"
        )
    return (
        "📕 <b>Документы СРО</b>\n\n"
        "⚠️ Сейчас СРО не выбрано — по отчётам, членству, контролю "
        "сначала введите ИНН (/start) или «🔄 Другой ИНН / без ИНН».\n\n"
        "Тексты положений есть для всех 15 партнёрских СРО.\n"
        "Без выбора можно спросить только по <b>Градостроительному кодексу РФ</b>.\n\n"
        "⬇️ Напишите вопрос или нажмите «💬 Спросить по документам».\n\n"
        f"{DOC_QA_DISCLAIMER}"
    )


def format_doc_qa_hint(sro_id: str | None = None) -> str:
    sid = (sro_id or "").strip().upper() or None
    name = DOC_QA_SRO_TEXTS.get(sid or "")
    if name:
        return (
            f"📕 <b>Вопросы по документам — {name}</b>\n\n"
            f"Короткий ответ <b>только по тексту</b> {name} или Градкодекса.\n\n"
            f"<b>В базе:</b>\n"
            f"• Градостроительный кодекс РФ\n"
            f"• Положения {name}: {_POL_KINDS}\n\n"
            "Примеры: «состав сведений реестра», «срок устранения нарушений», "
            "«что такое КФ ВВ».\n\n"
            f"{DOC_QA_DISCLAIMER}\n\n"
            "«⬅️ Назад в меню» — выход."
        )
    if sid:
        return (
            "📕 <b>Вопросы по документам</b>\n\n"
            "Положений вашего СРО в боте пока нет. Можно спросить по "
            "<b>Градостроительному кодексу РФ</b>.\n\n"
            f"{DOC_QA_DISCLAIMER}\n\n"
            "«⬅️ Назад в меню» — выход."
        )
    return (
        "📕 <b>Вопросы по документам</b>\n\n"
        "Выберите СРО в контексте — поиск пойдёт по его положениям "
        "(тексты есть у всех 15 партнёрских СРО).\n\n"
        f"{DOC_QA_DISCLAIMER}\n\n"
        "«⬅️ Назад в меню» — выход."
    )


# совместимость со старыми импортами
DOC_QA_HINT = format_doc_qa_hint(None)
DOC_QA_INTRO = format_doc_qa_intro(None)

_DOC_ASK_MODE: set[int] = set()
# list of {"title": str, "text": str}
_CHUNKS_CACHE: list[dict] | None = None
# chat_id -> вопрос пользователя, ждёт «да» на фолбэк из обычного ИИ
_FALLBACK_PENDING: dict[int, str] = {}

DOC_FALLBACK_YES = "docfb:yes"
DOC_FALLBACK_NO = "docfb:no"
# Минимальный score куска, чтобы предложить фолбэк (слабые совпадения не дёргаем)
DOC_FALLBACK_MIN_SCORE = 4.0


def enter_doc_ask_mode(chat_id: int) -> None:
    _DOC_ASK_MODE.add(int(chat_id))


def exit_doc_ask_mode(chat_id: int) -> None:
    _DOC_ASK_MODE.discard(int(chat_id))


def is_doc_ask_mode(chat_id: int) -> bool:
    return int(chat_id) in _DOC_ASK_MODE


def set_doc_fallback_pending(chat_id: int, question: str) -> None:
    _FALLBACK_PENDING[int(chat_id)] = (question or "").strip()


def pop_doc_fallback_pending(chat_id: int) -> str | None:
    return _FALLBACK_PENDING.pop(int(chat_id), None)


def clear_doc_fallback_pending(chat_id: int) -> None:
    _FALLBACK_PENDING.pop(int(chat_id), None)


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def _docs_dir() -> Path:
    """Папка с txt: где уже лежит grk_rf.txt, иначе SRO_FILES_DIR/docs_qa."""
    candidates: list[Path] = []
    try:
        from config_keys import SRO_FILES_DIR

        candidates.append(Path(SRO_FILES_DIR) / "docs_qa")
    except Exception:
        pass
    candidates.append(_project_root() / "sro files" / "docs_qa")
    for p in candidates:
        if (p / "grk_rf.txt").is_file():
            return p
    return candidates[0]


def _documents() -> list[dict]:
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


def ensure_grk_text() -> Path:
    """TXT уже есть — ок. Иначе один раз вытаскиваем из PDF (нужен pypdf)."""
    doc = next(x for x in _documents() if x["id"] == "grk_rf")
    txt = doc["path"]
    if txt.is_file() and txt.stat().st_size > 1000:
        return txt
    pdf = doc.get("pdf")
    if not pdf or not pdf.is_file():
        raise FileNotFoundError(
            f"Нет PDF кодекса: {pdf}. Положите grkodeksrf.pdf в папку GOLD."
        )
    from pypdf import PdfReader

    txt.parent.mkdir(parents=True, exist_ok=True)
    reader = PdfReader(str(pdf))
    parts = []
    for i, page in enumerate(reader.pages):
        t = page.extract_text() or ""
        if t.strip():
            parts.append(f"--- стр. {i + 1} ---\n{t}")
    txt.write_text("\n\n".join(parts), encoding="utf-8")
    return txt


def _normalize(s: str) -> str:
    s = s.lower().replace("ё", "е")
    s = re.sub(r"[^\w\s]+", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


# Короткие аббревиатуры в вопросе → полные слова для поиска (иначе «кк» отбрасывается как <3 букв).
_QUERY_ABBREVS: tuple[tuple[str, str], ...] = (
    (r"\bкк\b", "контрольный комитет"),
    (r"\bгрк\b", "градостроительный кодекс"),
    (r"\bгкрф\b", "градостроительный кодекс"),
    (r"\bпк\b", "положение о контроле"),
    (r"\bкф\b", "компенсационный фонд"),
    (r"\bкф вв\b", "компенсационный фонд возмещения вреда"),
)

DOC_QA_RETRY_HINT = (
    "\n\n<i>Если ответ не про то — уточните документ: "
    "«по градкодексу», «членство», «жалобы», «дисциплина», "
    "«страхование», «КФ ВВ» и т.п.</i>"
)


def expand_doc_query(question: str) -> str:
    """Раскрывает известные сокращения в вопросе. Исходную фразу не ломает."""
    q = (question or "").strip()
    if not q:
        return q
    out = q
    for pattern, repl in _QUERY_ABBREVS:
        out = re.sub(pattern, repl, out, flags=re.IGNORECASE | re.UNICODE)
    return out


def detect_doc_family(question: str) -> str:
    """Какое семейство документов искать: grk | polozhenie | auto."""
    qn = _normalize(expand_doc_query(question))
    wants_grk = any(
        x in qn
        for x in (
            "градостроительн",
            "градкодекс",
            "кодекс рф",
            "гкрф",
            "территориальн планирован",
            "землепользован",
            "градостроительн регламент",
        )
    )
    # «кодекс» без «положение» — чаще ГрК
    if "кодекс" in qn and "положен" not in qn:
        wants_grk = True
    wants_pol = any(
        x in qn
        for x in (
            "контрольный комитет",
            "комитет",
            "положение о контроле",
            "положен",
            "проверк члена",
            "входной контроль",
            "риск ориентир",
            "членств",
            "вступлен",
            "вступительн",
            "членск",
            "взнос",
            "реестр член",
            "реестр",
            "компенсационн фонд",
            "кф вв",
            "возмещения вреда",
            "жалоб",
            "дисциплинар",
            "страхован",
            "уведомлен",
            "обмен документ",
            "устав",
            "информационн открыт",
            "стандарт ассоц",
            "отчёт",
            "отчет",
            "предоставлен отч",
            "анализ деятельност",
        )
    )
    # «взнос» без кодекса — внутренние положения
    if "взнос" in qn and "кодекс" not in qn and "градостроительн" not in qn:
        wants_pol = True
    # «проверка» одна — слабый сигнал; не форсим pol без положения/контроля
    if "контрол" in qn and "градостроительн" not in qn:
        wants_pol = True
    if wants_grk and not wants_pol:
        return "grk"
    if wants_pol and not wants_grk:
        return "polozhenie"
    return "auto"


def _split_raw_to_chunks(
    raw: str, title: str, *, doc_id: str = "", family: str = "", sro: str | None = None
) -> list[dict]:
    # ГрК: Статья/Глава; положения СРО: «4. Порядок…», «4.1. …»
    pieces = re.split(
        r"(?=\n\s*(?:Статья|Раздел|Глава|Пункт)\s+\d+)"
        r"|(?=\n\s*\d+\.\d+\.\s+)"
        r"|(?=\n\s*\d+\.\s+[А-ЯЁA-Z«\"])",
        raw,
    )
    chunks: list[str] = []
    buf = ""
    for p in pieces:
        p = p.strip()
        if not p:
            continue
        if len(p) < 80 and buf:
            buf += "\n" + p
            continue
        if len(buf) > 2800:
            chunks.append(buf.strip())
            buf = p
        else:
            buf = (buf + "\n\n" + p).strip() if buf else p
        if len(buf) >= 2200:
            chunks.append(buf.strip())
            buf = ""
    if buf.strip():
        chunks.append(buf.strip())
    if len(chunks) < 3:
        chunks = []
        step = 1200
        for i in range(0, len(raw), step):
            piece = raw[i : i + step + 400].strip()
            if len(piece) > 100:
                chunks.append(piece)
    sro_id = sro if sro is not None else _sro_for_doc_id(doc_id)
    return [
        {
            "title": title,
            "text": c,
            "doc_id": doc_id,
            "family": family or ("grk" if "кодекс" in _normalize(title) else "polozhenie"),
            "sro": sro_id,
        }
        for c in chunks
        if c.strip()
    ]


def _filter_chunks_by_sro(chunks: list[dict], sro_id: str | None) -> list[dict]:
    """ГрК всегда; положения — только выбранного СРО (если тексты есть)."""
    sid = (sro_id or "").strip().upper() or None
    if not sid:
        # без контекста — только кодекс (не смешиваем чужие положения)
        return [c for c in chunks if not c.get("sro")]
    if sid not in DOC_QA_SRO_TEXTS:
        return [c for c in chunks if not c.get("sro")]
    return [c for c in chunks if not c.get("sro") or c.get("sro") == sid]


def _load_chunks(force: bool = False) -> list[dict]:
    global _CHUNKS_CACHE
    if _CHUNKS_CACHE is not None and not force:
        return _CHUNKS_CACHE

    ensure_grk_text()
    all_chunks: list[dict] = []
    missing = []
    for doc in _documents():
        path = doc["path"]
        if not path.is_file() or path.stat().st_size < 200:
            missing.append(doc["title"])
            continue
        raw = path.read_text(encoding="utf-8", errors="ignore")
        all_chunks.extend(
            _split_raw_to_chunks(
                raw,
                doc["title"],
                doc_id=doc.get("id", ""),
                family=doc.get("family", ""),
                sro=_sro_for_doc_id(doc.get("id", "")),
            )
        )

    if missing and not all_chunks:
        raise FileNotFoundError(
            "Нет текстов документов: " + ", ".join(missing)
        )

    _CHUNKS_CACHE = all_chunks
    return all_chunks


def list_loaded_docs() -> list[str]:
    titles = []
    for doc in _documents():
        p = doc["path"]
        if p.is_file() and p.stat().st_size > 200:
            titles.append(doc["title"])
    return titles


def _score_chunk(chunk: dict, tokens: list[str], question_norm: str) -> float:
    text = chunk["text"]
    title = chunk["title"]
    title_n = _normalize(title)
    norm = _normalize(text + " " + title)
    if not tokens:
        return 0.0
    score = 0.0
    for t in tokens:
        if len(t) < 3:
            continue
        c = norm.count(t)
        if c:
            score += min(c, 8) * (1.0 + 0.15 * min(len(t), 12))
    if "регламент" in tokens and "регламент" in norm:
        score += 3.0
    if "градостроительн" in question_norm and "градостроительн" in title_n:
        score += 6.0
    elif "градостроительн" in question_norm and "градостроительн" in norm:
        score += 2.0
    # Предпочитаем положения ОГПС, если вопрос про контроль / комитет / проверку
    if "комитет" in question_norm and "комитет" in title_n:
        score += 12.0
    if "контрол" in question_norm and "контрол" in title_n and "комитет" not in title_n:
        # «Положение о контроле», не комитет
        score += 8.0
    if "проверк" in question_norm and "контрол" in title_n:
        score += 6.0
    if "огпс" in question_norm and "огпс" in title_n:
        score += 5.0
    if "огпп" in question_norm and "огпп" in title_n:
        score += 5.0
    if "геоиндустри" in question_norm and "геоиндустри" in title_n:
        score += 5.0
    elif "гео" in question_norm and "геоиндустри" in title_n:
        score += 4.0
    # если явно назвали СРО — слегка штрафуем чужие
    if "огпп" in question_norm and "огпп" not in title_n and "кодекс" not in title_n:
        score -= 3.0
    if "огпс" in question_norm and "огпс" not in title_n and "кодекс" not in title_n:
        score -= 3.0
    if "геоиндустри" in question_norm and "геоиндустри" not in title_n and "кодекс" not in title_n:
        score -= 3.0
    if "одо" in question_norm and (
        "одо" in title_n or "договорных обязательств" in title_n or "обеспечения договорных" in title_n
    ):
        score += 12.0
    if "одо" in question_norm and "возмещения вреда" in title_n:
        score -= 10.0
    # Точечные бусты по названию документа
    title_boosts = (
        ("жалоб", "жалоб", 14.0),
        ("дисциплинар", "дисциплинар", 14.0),
        ("членств", "членств", 14.0),
        ("вступительн", "членств", 12.0),
        ("членск", "членств", 12.0),
        ("взнос", "членств", 8.0),
        ("реестр", "реестр", 12.0),
        ("компенсационн", "кф", 14.0),
        ("возмещения вреда", "кф", 12.0),
        ("страхован", "страхован", 12.0),
        ("уведомлен", "уведомлен", 14.0),
        ("обмен", "обмен", 12.0),
        ("устав", "устав", 14.0),
        ("открытост", "открытост", 12.0),
        ("стандарт", "стандарт", 10.0),
        ("кф одо", "кф обеспечен", 14.0),
        ("договорных обязательств", "кф обеспечен", 12.0),
        ("анализ деятельн", "анализ", 14.0),
        ("отчет", "анализ", 18.0),
        ("отчёт", "анализ", 18.0),
        ("предоставления отчет", "анализ", 20.0),
        ("предоставления отчёт", "анализ", 20.0),
        ("порядок предоставления", "анализ", 16.0),
    )
    for q_key, title_key, bonus in title_boosts:
        if q_key in question_norm and title_key in title_n:
            score += bonus
    # Не тащить «контроль», если вопрос явно про другой документ
    if "жалоб" in question_norm and "жалоб" not in title_n and "контрол" in title_n:
        score -= 15.0
    if "уведомлен" in question_norm and "уведомлен" not in title_n and "контрол" in title_n:
        score -= 15.0
    if "дисциплинар" in question_norm and "дисциплинар" not in title_n and "контрол" in title_n:
        score -= 12.0
    if ("членств" in question_norm or "вступительн" in question_norm) and "членств" not in title_n and "контрол" in title_n:
        score -= 12.0
    # «отчёты членов» — это анализ деятельности, не контроль
    if (
        ("отчет" in question_norm or "отчёт" in question_norm)
        and "анализ" not in title_n
        and "контрол" in title_n
    ):
        score -= 18.0
    if (
        ("отчет" in question_norm or "отчёт" in question_norm)
        and ("предоставления" in question_norm or "порядок" in question_norm)
        and "анализ" in title_n
    ):
        score += 12.0
    # буст куска, где есть заголовок нужного раздела
    if (
        ("отчет" in question_norm or "отчёт" in question_norm)
        and "порядок предоставления отчет" in norm
    ):
        score += 20.0
    if (
        ("состав" in question_norm or "сведен" in question_norm)
        and "реестр" in question_norm
        and "реестр" not in title_n
        and "контрол" in title_n
    ):
        score -= 18.0
    if (
        ("состав" in question_norm or "сведен" in question_norm)
        and "реестр" in question_norm
        and "реестр" in title_n
    ):
        score += 16.0
    return score


def question_prefers_documents(question: str) -> bool:
    """Вопрос про формулировки из положений/кодекса, а не «дай ссылку на раздел сайта»."""
    qn = _normalize(expand_doc_query(question))
    markers = (
        "состав сведений",
        "состав данн",
        "перечень сведений",
        "какие сведения",
        "какие данн",
        "что должно содержаться",
        "должен содержаться",
        "должны содержаться",
        "по положению",
        "из положения",
        "согласно положен",
        "в соответствии с положен",
        "меры дисциплинар",
        "порядок рассмотрения жалоб",
        "размер вступительн",
        "размер членск",
        "компенсационн фонд",
        "статья ",
        "пункт ",
        "глава ",
    )
    if any(m in qn for m in markers):
        return True
    # «состав … реестра» / «сведения реестра членов»
    if "реестр" in qn and ("состав" in qn or "сведен" in qn):
        return True
    return False


def try_doc_fallback_offer(question: str, chat_id: int | None = None, sro_id: str | None = None) -> dict | None:
    """Если в docs_qa сильный кусок — оффер «хотите короткий из документа?»."""
    if not (question or "").strip():
        return None
    hit = probe_document_hit(question, sro_id=sro_id)
    if not hit.get("hit"):
        return None
    if chat_id is not None:
        set_doc_fallback_pending(chat_id, question)
    return {
        "ok": True,
        "doc_fallback": True,
        "text": hit.get("offer_text") or "",
    }


def find_relevant_scored(
    question: str,
    top_k: int = 6,
    min_score: float = 0.0,
    sro_id: str | None = None,
) -> list[tuple[float, dict]]:
    chunks = _filter_chunks_by_sro(_load_chunks(), sro_id)
    family = detect_doc_family(question)
    if family in ("grk", "polozhenie"):
        chunks = [c for c in chunks if c.get("family") == family]
    qn = _normalize(question)
    tokens = [t for t in qn.split() if len(t) >= 3]
    if "регламент" in qn:
        tokens.extend(["градостроительный", "регламент", "землепользования", "застройки"])
    scored = [(_score_chunk(c, tokens, qn), c) for c in chunks]
    scored.sort(key=lambda x: x[0], reverse=True)
    top = [(s, c) for s, c in scored if s > min_score][:top_k]
    if not top and min_score <= 0:
        for s, c in scored:
            if any(t in _normalize(c["text"]) for t in tokens if len(t) >= 5):
                top.append((s, c))
            if len(top) >= top_k:
                break
    # auto: не смешивать ГрК и положения в одном ответе — берём семейство лучшего хита
    if family == "auto" and top:
        best_fam = top[0][1].get("family") or ""
        if best_fam:
            same = [(s, c) for s, c in scored if c.get("family") == best_fam and s > min_score]
            if same:
                top = same[:top_k]
    return top[:top_k]


def find_relevant_chunks(
    question: str, top_k: int = 6, sro_id: str | None = None
) -> list[dict]:
    return [
        c
        for _s, c in find_relevant_scored(
            question, top_k=top_k, min_score=0.0, sro_id=sro_id
        )
    ]


def probe_document_hit(
    question: str,
    top_k: int = 3,
    min_score: float = DOC_FALLBACK_MIN_SCORE,
    sro_id: str | None = None,
) -> dict:
    """Быстрая проверка: есть ли в docs_qa куски по вопросу (без вызова ИИ)."""
    search_q = expand_doc_query(question)
    try:
        scored = find_relevant_scored(
            search_q, top_k=top_k, min_score=min_score, sro_id=sro_id
        )
    except Exception:
        return {"hit": False, "titles": [], "offer_text": ""}

    if not scored:
        return {"hit": False, "titles": [], "offer_text": ""}

    titles = list(dict.fromkeys(c["title"] for _s, c in scored))
    titles_line = ", ".join(titles)
    sid = (sro_id or "").strip().upper() or None
    name = DOC_QA_SRO_TEXTS.get(sid or "")
    if name:
        scope_note = f"<i>Ответ по текстам {name} (+ ГрК при необходимости).</i>"
    elif sid:
        scope_note = "<i>Положений вашего СРО в боте нет — только ГрК.</i>"
    else:
        scope_note = (
            f"<i>Тексты положений: {', '.join(DOC_QA_SRO_TEXTS.values())} "
            f"— лучше выбрать СРО в контексте.</i>"
        )
    offer_text = (
        f"📕 По вопросу «<b>{question}</b>» в документе есть формулировка:\n"
        f"<b>{titles_line}</b>\n\n"
        "Хотите короткий ответ <b>по тексту документа</b> "
        "(не только ссылку на раздел сайта)?\n\n"
        f"{scope_note}\n"
        f"{DOC_QA_DISCLAIMER}"
    )
    return {
        "hit": True,
        "titles": titles,
        "offer_text": offer_text,
        "top_score": scored[0][0],
    }


def _chat_completion(messages: list[dict], max_tokens: int = 900) -> str:
    or_key = (_OR_KEY or "").strip()
    model = (_OR_MODEL or OPENROUTER_DEFAULT_MODEL).strip() or OPENROUTER_DEFAULT_MODEL
    if or_key:
        try:
            r = requests.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {or_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://www.srogen.ru",
                    "X-Title": "SRO GOLD DocQA",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": 0.1,
                    "max_tokens": max_tokens,
                },
                timeout=60,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception:
            pass

    if _gigachat_ok():
        try:
            return _gigachat_chat(
                messages, max_tokens=max_tokens, temperature=0.1
            )
        except Exception:
            pass

    groq = (_GROQ or "").strip()
    if not groq:
        raise RuntimeError("no_llm_key")
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {groq}",
            "Content-Type": "application/json",
        },
        json={
            "model": "llama-3.1-8b-instant",
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": max_tokens,
        },
        timeout=45,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def answer_from_document(question: str, sro_id: str | None = None) -> dict:
    """Ответ только по найденным кускам загруженных документов."""
    search_q = expand_doc_query(question)
    sid = (sro_id or "").strip().upper() or None
    # Без СРО не ищем «молча» только в ГрК и не пишем «не нашлось в кодексе»
    # по вопросам про отчёты/членство — просим выбрать организацию.
    if not sid and detect_doc_family(search_q) != "grk":
        return {
            "ok": True,
            "text": (
                "📕 Чтобы искать в <b>положениях СРО</b> (отчёты, членство, контроль, КФ…), "
                "сначала выберите организацию: ИНН на /start "
                "или кнопка «🔄 Другой ИНН / без ИНН».\n\n"
                "Без выбранного СРО можно спросить только по "
                "<b>Градостроительному кодексу РФ</b> "
                "(добавьте в вопрос «по градкодексу»).\n"
                f"{DOC_QA_RETRY_HINT}"
            ),
        }
    try:
        chunks = find_relevant_chunks(search_q, top_k=8, sro_id=sro_id)
        name = DOC_QA_SRO_TEXTS.get(sid or "")
        if name:
            loaded = [t for t in list_loaded_docs() if name in t or "кодекс" in t.lower()]
        else:
            loaded = [t for t in list_loaded_docs() if "кодекс" in t.lower()]
    except FileNotFoundError as e:
        return {"ok": False, "text": f"⚠️ {e}"}
    except Exception as e:
        return {"ok": False, "text": f"⚠️ Не удалось прочитать документы: {e}"}

    if not chunks:
        docs = ", ".join(loaded) if loaded else "база пуста"
        return {
            "ok": True,
            "text": (
                f"📕 По вопросу «<b>{question}</b>» в документах "
                f"({docs}) не нашлось близких фрагментов.\n\n"
                "Попробуйте другими словами или уточните документ/статью."
                f"{DOC_QA_RETRY_HINT}"
            ),
        }

    parts = []
    sources = []
    for c in chunks[:8]:
        sources.append(c["title"])
        parts.append(f"[{c['title']}]\n{c['text']}")
    context = "\n\n---\n\n".join(parts)
    if len(context) > 14000:
        context = context[:14000] + "\n…"

    uniq_sources = list(dict.fromkeys(sources))
    family = detect_doc_family(search_q)
    sro_name = DOC_QA_SRO_TEXTS.get((sro_id or "").strip().upper() or "", "")
    if family == "grk":
        scope = "только Градостроительный кодекс РФ"
    elif family == "polozhenie":
        if sro_name:
            scope = f"только положения {sro_name}, не кодекс и не другие СРО"
        else:
            scope = "только положения СРО из найденных фрагментов, не кодекс"
    else:
        scope = "один выбранный документ (ГрК или положение), без смешивания"
    system = (
        "Ты помощник по официальным документам СРО. "
        f"Сейчас отвечай {scope}. "
        "Отвечай ТОЛЬКО по приведённым фрагментам. Не выдумывай. "
        "Если во фрагментах есть конкретные пункты (сроки, формы, перечень сведений) — "
        "перечисли их по делу, со ссылкой на пункты. "
        "Не пиши, что «полного описания нет», если в фрагментах уже есть частичный "
        "порядок — сначала выдай то, что есть. "
        "Укажи название документа и номера пунктов/статей. "
        "Пиши по-русски, кратко и понятно. "
        "В конце одной строкой: «Ориентир по тексту · не замена юристу.»"
    )
    user = (
        f"Вопрос пользователя:\n{search_q}\n\n"
        f"Фрагменты из документов:\n{context}"
    )
    try:
        answer = _chat_completion(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        )
    except RuntimeError:
        return {
            "ok": False,
            "text": (
                "⚠️ Нет ключа ИИ.\n"
                "Вставьте OPENROUTER_API_KEY, GIGACHAT_CREDENTIALS (Сбер) "
                "или GROQ_API_KEY в config_keys.py."
            ),
        }
    except Exception:
        return {
            "ok": False,
            "text": "⚠️ ИИ временно недоступен. Попробуйте ещё раз через минуту.",
        }

    safe = (
        answer.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    if (_OR_KEY or "").strip():
        backend = "OpenRouter"
    elif _gigachat_ok():
        backend = "GigaChat"
    else:
        backend = "Groq"
    src_line = ", ".join(uniq_sources)
    return {
        "ok": True,
        "text": (
            f"📕 <b>Поиск по документам</b>\n"
            f"<i>источники: {src_line}</i>\n"
            f"<i>модель: {backend}</i>\n\n"
            f"❓ <b>{question}</b>\n\n"
            f"{safe}"
            f"{DOC_QA_RETRY_HINT}"
        ),
    }


def warmup() -> str:
    """Прогрев кэша кусков (при старте бота)."""
    n = len(_load_chunks())
    docs = list_loaded_docs()
    return f"doc_qa chunks={n} docs={len(docs)} ({', '.join(docs)})"
