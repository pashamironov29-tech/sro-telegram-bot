"""Маршрутизация вопросов: кейсы из scripts/routing_regression.py."""

from __future__ import annotations

import pytest

from contacts_search import looks_like_directory_person_query, should_global_directory_intercept
from local_answers import local_route_kind, looks_like_question, match_topic_local
from partners_data import match_partner_query
from sro_site_qa import match_sro_site_qa
from voprosy_faq import match_voprosy_faq


def _question_path(text: str) -> bool:
    """Должен уйти в сайт/FAQ, а не в справочник и не в ложного партнёра."""
    if looks_like_directory_person_query(text):
        return False
    if match_partner_query(text):
        return False
    if looks_like_question(text):
        return True
    if match_sro_site_qa(text) or match_voprosy_faq(text):
        return True
    if match_topic_local(text)[0]:
        return True
    return False


def _directory_path(text: str) -> bool:
    return should_global_directory_intercept(text) and not looks_like_question(text)


def _not_global_directory(text: str) -> bool:
    return looks_like_directory_person_query(text) and not should_global_directory_intercept(text)


def _eurocodes_faq(text: str) -> bool:
    match = match_voprosy_faq(text)
    return bool(match) and not match.get("_scope_blocked") and "еврокод" in match["label"].lower()


CASES = [
    ("Филина", "directory", _directory_path),
    ("телефон Миронова", "directory", _directory_path),
    ("Берестовская", "directory", _directory_path),
    ("Малинина Ольга Николаевна", "not_global_dir", _not_global_directory),
    ("где устав", "question", _question_path),
    ("устав", "question", _question_path),
    ("комфонд", "question", _question_path),
    ("стандарты и правила СРО", "question", _question_path),
    ("база законов", "question", _question_path),
    ("техрегулирование", "question", _question_path),
    ("размеры взносов", "question", _question_path),
    ("еврокоды что это", "question", _question_path),
    ("размеры взносов", "no_partner", lambda t: match_partner_query(t) is None),
    ("носо", "partner", lambda t: match_partner_query(t) is not None),
    ("партнеры", "partner", lambda t: match_partner_query(t) is not None),
    ("размеры взносов", "topic_vznosy", lambda t: match_topic_local(t)[0] == "vznosy"),
    ("еврокоды что это", "faq_eurocodes", _eurocodes_faq),
]


@pytest.mark.parametrize(
    ("text", "check"),
    [pytest.param(text, check, id=f"{tag}:{text}") for text, tag, check in CASES],
)
def test_routing_case(text, check):
    assert check(text)


KNOWN_VOPROSY_MISS = "Зачем вообще нужно вступать в СРО?"

SCREENSHOT_ROUTES = [
    "Какие меры дисциплинарного воздействия бывают в СРО?",
    "Можно ли на УСН уменьшить доход на взнос в компфонд?",
    "Нужно ли вносить сведения о членстве в СРО в Федресурс?",
    "Можно ли учесть взносы в СРО в расходах по налогу на прибыль?",
    "Нужно ли генподрядчику допуск на работы, которые выполняет субподрядчик?",
    pytest.param(
        KNOWN_VOPROSY_MISS,
        marks=pytest.mark.xfail(
            strict=True,
            reason=(
                "Известный провал routing_regression: вопрос уходит в тему по словам "
                "(topic), а не в раздел «Вопрос-ответ». Не чиним в этой задаче."
            ),
        ),
    ),
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


@pytest.mark.parametrize("text", SCREENSHOT_ROUTES)
def test_screenshot_question_routes_to_voprosy(text):
    assert local_route_kind(text) == "voprosy"


def test_known_miss_routes_to_topic_today():
    """Фиксируем текущее поведение известного провала, чтобы заметить, если оно сменится."""
    assert local_route_kind(KNOWN_VOPROSY_MISS) == "topic"
