"""Поиск сотрудников в телефонном справочнике (для ИИ-помощника и др.)."""

from __future__ import annotations

import re

try:
    from contacts_data import CONTACTS, CONTACT_BUTTONS
except ImportError:
    CONTACTS = {}
    CONTACT_BUTTONS = []

_PERSON_SPLIT = re.compile(r"(?=👤\s*<b>)")
_NAME_LINE = re.compile(
    r"👤\s*<b>([^<]+)</b>\s*(?:\(([^)]*)\))?\s*\n(.*)",
    re.DOTALL,
)

_DIRECTORY_HINTS = (
    "телефон",
    "телефона",
    "телефону",
    "тел",
    "контакт",
    "контакты",
    "контакта",
    "email",
    "e-mail",
    "почта",
    "почту",
    "почты",
    "добавочный",
    "добавоч",
    "мобильный",
    "мобиль",
    "моб",
    "найти",
    "кто",
    "такой",
    "такая",
    "сотрудник",
    "сотрудника",
    "справочник",
    "позвонить",
    "номер",
    "наберите",
    "связаться",
    "внутренний",
    "внутр",
    "звонок",
)


def _strip_directory_hints(q: str) -> str:
    for hint in sorted(_DIRECTORY_HINTS, key=len, reverse=True):
        q = re.sub(rf"\b{re.escape(hint)}\b", " ", q, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", q).strip()


def _surname_candidates(token: str) -> set[str]:
    """Варианты фамилии: именительный падеж и типичные склонения."""
    t = token.lower().replace("ё", "е").strip()
    if len(t) < 2:
        return {t} if t else set()

    candidates = {t}

    if t.endswith("ой") and len(t) > 4:
        stem = t[:-2]
        candidates.update({stem, stem + "а", stem + "ов", stem + "ев", stem + "ин"})

    if t.endswith("ою") and len(t) > 4:
        stem = t[:-2]
        candidates.update({stem + "а", stem + "ов", stem + "ев"})

    if t.endswith("а") and len(t) > 3:
        candidates.add(t[:-1])
        if t.endswith("ова"):
            candidates.add(t[:-1] + "в")
            candidates.add(t[:-3] + "ов")
        if t.endswith("ева"):
            candidates.add(t[:-3] + "ев")
        if t.endswith("ина"):
            candidates.add(t[:-1])
            candidates.add(t[:-3] + "ин")

    if t.endswith("у") and len(t) > 3:
        candidates.add(t[:-1])

    if t.endswith("е") and len(t) > 4:
        candidates.add(t[:-1])

    if t.endswith("ы") and len(t) > 4:
        candidates.add(t[:-1])

    return {c for c in candidates if len(c) >= 2}


def _surnames_match(query_token: str, person_surname: str) -> bool:
    if not query_token or not person_surname:
        return False
    q = query_token.lower().replace("ё", "е")
    p = person_surname.lower().replace("ё", "е")
    if q == p:
        return True
    q_set = _surname_candidates(q)
    p_set = _surname_candidates(p)
    if q_set & p_set:
        return True
    for a in q_set:
        for b in p_set:
            if a == b:
                return True
    # Короткий ввод («Глеб», «Сизо») — префикс фамилии
    shorter, longer = (q, p) if len(q) <= len(p) else (p, q)
    if len(shorter) <= 5 and len(shorter) >= 3 and longer.startswith(shorter):
        return True
    # Одинаковый корень (≥6 символов), не «бере» у Берендаков/Берестовская
    for a in q_set:
        for b in p_set:
            if len(a) >= 6 and len(b) >= 6 and a[:6] == b[:6]:
                return True
    return False

_NO_ACCESS_TEXT = (
    "🔒 <b>У вас нет доступа к телефонному справочнику.</b>\n\n"
    "Чтобы искать сотрудников по ФИО, откройте «📞 Контакты отделов» в главном меню "
    "и введите пароль, который выдаёт Ассоциация.\n\n"
    "Если пароля нет — обратитесь в СРО:\n"
    "📞 <code>+7 (495) 775-81-11</code>\n"
    "📧 <code>info@srogen.ru</code>"
)


def no_access_message() -> str:
    return _NO_ACCESS_TEXT


def _normalize(text: str) -> str:
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[^a-zа-я0-9.\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_full_name(full_name: str) -> tuple[str, str, str, str]:
    """Фамилия, имя, отчество, строка для поиска."""
    clean = re.sub(r"\s+", " ", full_name.strip())
    parts = clean.split()
    surname = parts[0].lower() if parts else ""
    first = parts[1].lower() if len(parts) > 1 else ""
    patronymic = parts[2].lower() if len(parts) > 2 else ""
    return surname, first, patronymic, _normalize(clean)


def _parse_query(query: str) -> dict:
    q = _strip_directory_hints(_normalize(query))

    words = [w for w in q.split() if w and re.search(r"[а-я]", w)]
    first_initial = ""
    patronymic_initial = ""

    if not words:
        return {"surname": "", "first_i": "", "patronymic_i": "", "raw": q}

    # Самое длинное слово — чаще всего фамилия («телефон Сизовой» → сизовой)
    words_by_len = sorted(words, key=lambda w: (-len(re.sub(r"[^а-я]", "", w)), words.index(w)))
    surname = words_by_len[0]

    for word in words:
        if word == surname:
            continue
        compact = word.replace(" ", "")
        bits = re.findall(r"[а-я]", compact.lower())
        if re.fullmatch(r"[а-я]\.[а-я]\.?", compact, flags=re.IGNORECASE) or (
            len(bits) == 2 and "." in compact
        ):
            first_initial, patronymic_initial = bits[0], bits[1]
            break
        bare = word.replace(".", "")
        if len(bare) == 1:
            first_initial = bare
        elif len(bare) == 2 and bare.isalpha():
            first_initial, patronymic_initial = bare[0], bare[1]
        elif len(bare) >= 2 and not _surnames_match(bare, surname):
            first_initial = bare[0]

    return {
        "surname": surname,
        "first_i": first_initial,
        "patronymic_i": patronymic_initial,
        "raw": q,
    }


def _iter_persons():
    for department, html in CONTACTS.items():
        for chunk in _PERSON_SPLIT.split(html):
            chunk = chunk.strip()
            if not chunk.startswith("👤"):
                continue
            match = _NAME_LINE.match(chunk)
            if not match:
                continue
            full_name, role, body = match.group(1), (match.group(2) or "").strip(), match.group(3).strip()
            block = f"👤 <b>{full_name}</b>" + (f" ({role})" if role else "") + f"\n{body}"
            yield department, full_name, role, block


def _score_person(query: dict, full_name: str) -> float:
    surname, first, patronymic, normalized_full = _parse_full_name(full_name)
    if not query["surname"]:
        return 0.0

    if not _surnames_match(query["surname"], surname):
        if query["raw"] and query["raw"] in normalized_full:
            return 0.85
        return 0.0

    score = 1.0
    if query["first_i"]:
        if not first or first[0] != query["first_i"]:
            return 0.0
        score += 0.2
    if query["patronymic_i"]:
        if not patronymic or patronymic[0] != query["patronymic_i"]:
            return 0.0
        score += 0.2
    return score


def looks_like_directory_person_query(text: str) -> bool:
    """Запрос похож на поиск человека в справочнике, а не на вопрос про сайт."""
    raw = text.strip()
    if len(raw) < 3 or "?" in raw:
        return False

    if raw in CONTACT_BUTTONS or raw in CONTACTS:
        return False

    lower = raw.lower().replace("ё", "е")
    has_directory_hint = any(
        re.search(rf"\b{re.escape(hint)}\b", lower) for hint in _DIRECTORY_HINTS
    )

    question_starts = (
        "где ", "как ", "что ", "что такое ", "когда ", "зачем ", "почему ",
        "можно ", "нужно ", "есть ли ", "сколько ", "какой ", "какая ", "какие ",
        "расскаж", "подскаж", "объясни ", "найти на сайте", "на сайте ",
    )

    if has_directory_hint:
        return bool(re.search(r"[а-яё]{2,}", lower))

    if not re.fullmatch(r"[а-яёА-ЯЁ.\s\-]+", raw):
        return False

    words = [w for w in re.split(r"\s+", raw) if w]
    if not words or len(words) > 4:
        return False

    if len(words) == 1:
        letters = re.sub(r"[^а-яё]", "", words[0].lower())
        if len(letters) >= 4:
            try:
                from ai_assistant import is_non_directory_site_query

                if is_non_directory_site_query(text):
                    return False
            except ImportError:
                pass
            return True
        return False

    if any(lower.startswith(q) for q in question_starts):
        return False
    try:
        from ai_assistant import is_non_directory_site_query

        if is_non_directory_site_query(text):
            return False
    except ImportError:
        pass

    w0, w1 = words[0], words[1]
    if re.match(r"^[А-ЯЁа-яё]\.\s*[А-ЯЁа-яё]\.?$|^[А-ЯЁ]\.[А-ЯЁ]\.?$", w1.replace(" ", "")):
        return bool(re.match(r"^[А-ЯЁа-яё\-]{2,}", w0))
    if re.match(r"^[А-ЯЁ][а-яё\-]{2,}$", w0) and re.match(r"^[А-ЯЁ][а-яё]{2,}$", w1):
        return True

    return False


def is_explicit_directory_phrase(text: str) -> bool:
    """Фраза явно про поиск в справочнике (не пароль и не полное ФИО для НРС)."""
    return should_global_directory_intercept(text)


def should_global_directory_intercept(text: str) -> bool:
    """С главного меню: фамилия/инициалы/подсказки — да; полное ФИО (НРС) — нет."""
    if not looks_like_directory_person_query(text):
        return False
    raw = text.strip()
    lower = raw.lower()
    if any(re.search(rf"\b{re.escape(hint)}\b", lower) for hint in _DIRECTORY_HINTS):
        return True
    if "." in raw:
        return True
    words = [w for w in re.split(r"\s+", raw) if w]
    if len(words) >= 3:
        return False
    if len(words) == 2 and re.match(r"^[А-ЯЁ][а-яё]{2,}$", words[1]):
        return False
    return True


def search_directory_persons(query: str, *, limit: int = 5) -> list[dict]:
    parsed = _parse_query(query)
    if not parsed["surname"] and not parsed["raw"]:
        return []

    scored: list[tuple[float, dict]] = []
    for department, full_name, role, block in _iter_persons():
        score = _score_person(parsed, full_name)
        if score <= 0:
            continue
        scored.append(
            (
                score,
                {
                    "department": department,
                    "name": full_name,
                    "role": role,
                    "block": block.strip(),
                },
            )
        )

    scored.sort(key=lambda item: (-item[0], item[1]["name"]))
    seen = set()
    results = []
    for _, item in scored:
        key = item["name"]
        if key in seen:
            continue
        seen.add(key)
        results.append(item)
        if len(results) >= limit:
            break
    return results


def format_directory_search_results(query: str, results: list[dict]) -> str:
    if not results:
        return (
            f"🔍 По запросу «<b>{query}</b>» в телефонном справочнике никого не найдено.\n\n"
            "Попробуйте: «Глебов», «Глебова», «телефон Сизовой» или «Фамилия И.О.»\n"
            "Либо откройте «📞 Контакты отделов» и выберите отдел."
        )

    if len(results) == 1:
        item = results[0]
        dept = item["department"].replace("📞 ", "").replace("📋 ", "")
        return (
            f"📇 <b>Справочник СРО</b> — {item['name']}\n"
            f"<i>Отдел: {dept}</i>\n\n"
            f"{item['block']}"
        )

    lines = [
        f"📇 <b>Справочник СРО</b> — найдено: {len(results)}",
        f"<i>Запрос: {query}</i>\n",
    ]
    for item in results:
        dept = item["department"]
        role = f" ({item['role']})" if item["role"] else ""
        lines.append(f"———\n{item['block']}\n<i>Отдел: {dept}</i>")
    return "\n".join(lines)
