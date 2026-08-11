"""Узкие ответы про разделы сайта srogen.ru (без дублирования voprosy_faq и KEYWORD_RULES)."""

import re
from difflib import SequenceMatcher

from bot_disclaimers import OFFICIAL_SOURCE_DISCLAIMER

URL_DOCUMENTY_SRO = "https://www.srogen.ru/sro/documenty_sro/"
URL_ARKHIV = "https://www.srogen.ru/sro/arkhiv_dokumentov_sro/"
URL_O_SRO = "https://www.srogen.ru/sro/"
URL_PARTNERS = "https://www.srogen.ru/kontakty/partnery/"
URL_ZAKON = "https://www.srogen.ru/zakonodatelstvo/"
URL_ZAKON_DEISTV = "https://www.srogen.ru/zakonodatelstvo/deystvuyushchie_dokumenty/"

SRO_SITE_QA_ITEMS = [
    {
        "id": "documenty_sro_page",
        "label": "Где на сайте устав, стандарты и свидетельства СРО",
        "short": (
            "Актуальные учредительные документы, стандарты и правила, свидетельства "
            "и иные документы Ассоциации — в разделе «Документы СРО». "
            "Старые редакции — в «Архиве документов СРО»."
        ),
        "links": (
            ("Документы СРО", URL_DOCUMENTY_SRO),
            ("Архив документов СРО", URL_ARKHIV),
        ),
        "phrases": (
            "документы сро",
            "раздел документы сро",
            "где устав",
            "где найти устав",
            "где скачать устав",
            "устав",
            "устав сро",
            "устав ассоциац",
            "стандарты и правила",
            "стандарты сро",
            "стандарт деятельност",
            "свидетельств",
            "учредительн",
            "внутренние документы сро",
            "положение о членств",
        ),
        "keywords": ("устав", "стандарт", "свидетель", "положен", "учредит"),
        "min_hits": 2,
        "min_hits_if_phrase": 1,
    },
    {
        "id": "sro_gen_vs_partners",
        "label": "Что такое СРО «ГЕН» и чем она отличается от партнёрских СРО",
        "short": (
            "СРО «ГЕН» (Ассоциация саморегулируемых организаций «Генподряд») — "
            "объединение, в которое организации вступают как в основную СРО. "
            "Партнёрские СРО — отдельные саморегулируемые организации-партнёры "
            "Ассоциации (строители, проектировщики, изыскатели и др.); "
            "с ними сотрудничают через раздел «Партнёры и НО», это не замена членства в «ГЕН»."
        ),
        "links": (
            ("Об Ассоциации (СРО «ГЕН»)", URL_O_SRO),
            ("Партнёры и национальные объединения", URL_PARTNERS),
        ),
        "phrases": (
            "сро ген",
            "сро «ген",
            'сро "ген',
            "что такое сро ген",
            "чем отличается сро ген",
            "отличается от партнер",
            "отличается от партнёр",
            "партнерск сро",
            "партнёрск сро",
            "ассоциация ген",
            "ассоциация генподряд",
            "объединение генеральных подрядчиков",
        ),
        "keywords": ("ассоциац", "партнер", "партнёр", "объединен"),
        "min_hits": 2,
        "min_hits_if_phrase": 1,
        "require_any": ("сро ген", "сро «ген", "ассоциац", "партнерск", "партнёрск"),
    },
    {
        "id": "zakonodatelstvo_on_site",
        "label": "Где на сайте законы и нормативные акты",
        "short": (
            "Законодательство и нормативная база — в разделе «Законодательство»: "
            "действующие документы, проекты НПА и архив утративших силу актов. "
            "В боте есть кнопка «База законов» с той же ссылкой."
        ),
        "links": (("Законодательство", URL_ZAKON),),
        "phrases": (
            "база законов",
            "где законы",
            "где законодательство",
            "законы на сайте",
            "норматив на сайте",
            "градостроительный кодекс на сайте",
        ),
        "keywords": ("законодат", "закон", "норматив", "градостро"),
        "min_hits": 2,
        "min_hits_if_phrase": 1,
        "block_if": ("техрегул", "техническ реглам", "184-фз", "384-фз"),
    },
    {
        "id": "tehregulirovanie_on_site",
        "label": "Где на сайте техрегулирование и технические регламенты",
        "short": (
            "Материалы по техническому регулированию в строительстве — "
            "в разделе «Законодательство» → «Действующие документы», "
            "блок «Вопросы техрегулирования» (184-ФЗ, 384-ФЗ и связанные акты)."
        ),
        "links": (("Действующие документы (техрегулирование)", URL_ZAKON_DEISTV),),
        "phrases": (
            "техрегулирован",
            "техническ реглам",
            "вопросы техрегулирован",
            "184-фз",
            "384-фз",
            "где техрегул",
        ),
        "keywords": ("техрегул", "регламент", "184", "384"),
        "min_hits": 2,
        "min_hits_if_phrase": 1,
    },
]


def _normalize(text: str) -> str:
    text = text.lower().replace("ё", "e")
    return re.sub(r"\s+", " ", text.strip())


def _has_phrase(normalized: str, phrases: tuple) -> bool:
    return any(p in normalized for p in phrases)


def _should_block_item(normalized: str, item: dict) -> bool:
    for fragment in item.get("block_if", ()):
        if fragment in normalized:
            return True

    item_id = item["id"]
    if item_id == "documenty_sro_page":
        if "архив" in normalized and any(w in normalized for w in ("редакц", "стар", "стары")):
            return True
        if "нок" in normalized or ("независим" in normalized and "оценк" in normalized):
            return True
        if re.search(r"(?<![a-zа-я])нрс(?![a-zа-я])", normalized):
            return True
        if "вступ" in normalized and not any(
            w in normalized for w in ("устав", "стандарт", "свидетель", "учредит")
        ):
            return True
        if "документ" in normalized and "для" in normalized and "вступ" in normalized:
            return True

    if item_id == "sro_gen_vs_partners":
        if normalized in ("партнер", "партнёр", "партнеры", "партнёры"):
            return True
        if any(
            w in normalized
            for w in (
                "субподряд",
                "генподрядчик",
                "генподрядчика",
                "субподрядчик",
                "вред",
                "платит",
                "компенсацион",
                "компфонд",
                "допуск",
                "налог",
                "усн",
                "федресурс",
                "исключ",
                "дисциплинар",
                "выписк",
                "проектн",
                "обследован",
                "строительн",
                "контрол",
            )
        ):
            return True

    if item_id == "zakonodatelstvo_on_site":
        if any(w in normalized for w in ("техрегул", "техническ реглам")):
            return True

    return False


def _score_item(normalized: str, item: dict) -> float:
    if _should_block_item(normalized, item):
        return 0.0

    phrases = item.get("phrases", ())
    keywords = item.get("keywords", ())
    min_hits = item.get("min_hits", 2)
    phrase_hit = _has_phrase(normalized, phrases)

    require_any = item.get("require_any")
    if require_any and not any(r in normalized for r in require_any):
        return 0.0

    hits = sum(1 for kw in keywords if kw in normalized)
    if phrase_hit and hits >= item.get("min_hits_if_phrase", 1):
        return 0.96
    if hits >= min_hits:
        return 0.78 + hits / max(len(keywords), 1) * 0.2

    if phrase_hit:
        return 0.72

    return SequenceMatcher(None, normalized, _normalize(item["label"])).ratio() * 0.65


def match_sro_site_qa(question: str, min_score: float = 0.70):
    normalized = _normalize(question)
    if not normalized:
        return None

    best_item = None
    best_score = 0.0

    for item in SRO_SITE_QA_ITEMS:
        score = _score_item(normalized, item)
        if score > best_score:
            best_score = score
            best_item = item

    if best_item and best_score >= min_score:
        return best_item
    return None


def format_sro_site_qa_response(question: str, item: dict) -> dict:
    links_block = "\n".join(f"🔗 <b>{title}:</b> {url}" for title, url in item["links"])
    return {
        "ok": True,
        "text": (
            f"🤖 По вашему вопросу «<b>{question}</b>»:\n\n"
            f"💡 <b>Кратко:</b> {item['short']}\n\n"
            f"📄 <b>На сайте:</b>\n{links_block}\n\n"
            f"{OFFICIAL_SOURCE_DISCLAIMER}"
        ),
    }
