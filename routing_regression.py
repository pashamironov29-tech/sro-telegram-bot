# -*- coding: utf-8 -*-
"""
Локальная регрессия маршрутизации (без Telegram).
Запуск из папки GOLD:  python routing_regression.py
"""

from __future__ import annotations

from ai_assistant import local_ai_route_kind, match_topic_local, should_route_to_ai
from contacts_search import looks_like_directory_person_query, should_global_directory_intercept
from partners_data import match_partner_query
from sro_site_qa import match_sro_site_qa
from voprosy_faq import match_voprosy_faq


def _ai_path(text: str) -> bool:
    """Должен уйти в ИИ/сайт/FAQ, а не в справочник и не в ложного партнёра."""
    if looks_like_directory_person_query(text):
        return False
    if match_partner_query(text):
        return False
    if should_route_to_ai(text):
        return True
    if match_sro_site_qa(text) or match_voprosy_faq(text):
        return True
    if match_topic_local(text)[0]:
        return True
    return False


def _directory_path(text: str) -> bool:
    return should_global_directory_intercept(text) and not should_route_to_ai(text)


def _not_global_directory(text: str) -> bool:
    return looks_like_directory_person_query(text) and not should_global_directory_intercept(text)


CASES = [
    # справочник
    ("Филина", "directory", _directory_path),
    ("телефон Миронова", "directory", _directory_path),
    ("Берестовская", "directory", _directory_path),
    ("Малинина Ольга Николаевна", "not_global_dir", _not_global_directory),
    # сайт / ИИ
    ("где устав", "ai", _ai_path),
    ("устав", "ai", _ai_path),
    ("комфонд", "ai", _ai_path),
    ("стандарты и правила СРО", "ai", _ai_path),
    ("база законов", "ai", _ai_path),
    ("техрегулирование", "ai", _ai_path),
    ("размеры взносов", "ai", _ai_path),
    ("еврокоды что это", "ai", _ai_path),
    # партнёры — только явные запросы
    ("размеры взносов", "no_partner", lambda t: match_partner_query(t) is None),
    ("носо", "partner", lambda t: match_partner_query(t) is not None),
    ("партнеры", "partner", lambda t: match_partner_query(t) is not None),
    # тема взносов
    ("размеры взносов", "topic_vznosy", lambda t: match_topic_local(t)[0] == "vznosy"),
    # FAQ еврокоды
    (
        "еврокоды что это",
        "faq_eurocodes",
        lambda t: (m := match_voprosy_faq(t))
        and not m.get("_scope_blocked")
        and "еврокод" in m["label"].lower(),
    ),
]

# Вопросы с демо-скриншотов: должен быть раздел voprosy (с «Кратко»), не ссылка и не «СРО ГЕН»
SCREENSHOT_ROUTES = [
    "Какие меры дисциплинарного воздействия бывают в СРО?",
    "Можно ли на УСН уменьшить доход на взнос в компфонд?",
    "Нужно ли вносить сведения о членстве в СРО в Федресурс?",
    "Можно ли учесть взносы в СРО в расходах по налогу на прибыль?",
    "Нужно ли генподрядчику допуск на работы, которые выполняет субподрядчик?",
    "Зачем вообще нужно вступать в СРО?",
    "По каким основаниям исключают из членов СРО?",
    "Всегда ли нужно членство в СРО для проектной документации?",
    "Какая СРО платит по вреду — генподрядчика или субподрядчика?",
    "Когда применяют исключение из СРО как меру дисциплинарного воздействия?",
    "Какой документ СРО подтверждает взнос в КФ для налогового учёта?",
    "Нужно ли членство в СРО для обследования строительных конструкций?",
    "Можно ли проценты по компфонду направить на снижение членских взносов?",
    "Как получить выписку из реестра с указанием видов работ?",
    "Как изменилось техническое регулирование после техрегламента зданий?",
]


def main() -> int:
    failed = 0
    for text, tag, check in CASES:
        try:
            ok = bool(check(text))
        except Exception as exc:
            ok = False
            err = str(exc)
        else:
            err = ""
        status = "OK" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"{status}  [{tag}]  {text!r}" + (f"  ({err})" if err else ""))

    for text in SCREENSHOT_ROUTES:
        try:
            route = local_ai_route_kind(text)
            ok = route == "voprosy"
        except Exception as exc:
            ok = False
            route = str(exc)
        status = "OK" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"{status}  [screenshot-voprosy]  {route!r}  {text[:60]!r}...")
    print()
    total = len(CASES) + len(SCREENSHOT_ROUTES)
    if failed:
        print(f"Провалено: {failed} из {total}")
        return 1
    print(f"Все {total} проверок пройдены.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
