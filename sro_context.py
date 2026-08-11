"""Контекст СРО пользователя (пилот): привязка к ИНН и типу деятельности для ИИ/FAQ."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from sro_profiles import ACTIVITY_LABEL, format_activity_line, get_sro_profile

# chat_id -> {"sro_id": str, "inn": str | None}
_user_context: dict[int, dict] = {}

# chat_id -> list[sro_id] — ждём выбор, если членств несколько
_pending_sro_pick: dict[int, list[str]] = {}

# chat_id -> list[sro_id] — доступные СРО для кнопки «Назад к выбору СРО»
# (не сбрасывается при выборе конкретного СРО)
_pickable_sro_cache: dict[int, list[str]] = {}

_CONTEXT_FILE = Path(__file__).resolve().parent / "user_sro_context.json"
_ctx_lock = threading.Lock()


def _load_persisted_context() -> None:
    """Восстановить выбранное СРО после рестарта бота (иначе DocQA видит только ГрК)."""
    if not _CONTEXT_FILE.is_file():
        return
    try:
        raw = json.loads(_CONTEXT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return
    users = raw.get("users") if isinstance(raw, dict) else None
    if not isinstance(users, dict):
        return
    for key, row in users.items():
        if not isinstance(row, dict):
            continue
        try:
            chat_id = int(key)
        except (TypeError, ValueError):
            continue
        sro_id = (row.get("sro_id") or "").strip().upper()
        if not sro_id:
            continue
        inn = row.get("inn")
        _user_context[chat_id] = {
            "sro_id": sro_id,
            "inn": str(inn).strip() if inn else None,
        }


def _persist_context() -> None:
    payload = {
        "users": {
            str(cid): {"sro_id": ctx.get("sro_id"), "inn": ctx.get("inn")}
            for cid, ctx in _user_context.items()
            if isinstance(ctx, dict) and ctx.get("sro_id")
        }
    }
    try:
        with _ctx_lock:
            _CONTEXT_FILE.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    except Exception:
        pass


_load_persisted_context()

CTX_BUTTON_PREFIX = "📄 СРО — "
BACK_TO_SRO_PICK_BUTTON = "⬅️ Назад к выбору организации"
BACK_TO_DIRECTION_BUTTON = "⬅️ Назад к направлению"
# Старые подписи кнопки (если клавиатура ещё не обновилась)
_BACK_TO_SRO_PICK_ALIASES = frozenset(
    {
        BACK_TO_SRO_PICK_BUTTON,
        "⬅️ Назад к выбору СРО",
    }
)
SKIP_ONBOARDING_BUTTON = "▶️ Пропустить (вступаю / без ИНН)"
# Сброс контекста: снова ввести ИНН или пойти без ИНН (чистые бланки)
RESTART_ORG_BUTTON = "🔄 Другой ИНН / без ИНН"

# Вступающий без ИНН: сначала направление, потом конкретное СРО
JOINER_ACTIVITY_CHOICES: list[tuple[str, str]] = [
    ("🏗 Строители", "stroy"),
    ("📐 Проектировщики", "proekt"),
    ("🗺 Изыскания", "izysk"),
]

# Порядок кнопок внутри направления
_JOINER_SRO_ORDER: dict[str, list[str]] = {
    "stroy": ["OGPS", "MOTS", "OSO", "NOSO", "OSOES", "OSOT", "SOVS", "GPS"],
    "proekt": ["OGPP", "OGPO", "SPROF", "OPP"],
    "izysk": ["GEOIND", "MGEO", "PRIIS"],
}

# chat_id ждёт ИНН при /start
_await_inn: set[int] = set()
# после выбора СРО открыть главное меню (онбординг), а не только бланки
_open_main_after_sro: set[int] = set()
# ждём выбор направления (строй / проект / изыскания) после «Пропустить»
_await_joiner_activity: set[int] = set()
# chat_id → activity (stroy/proekt/izysk) на шаге выбора СРО без ИНН
_joiner_activity_by_chat: dict[int, str] = {}


def begin_await_inn(chat_id: int) -> None:
    _await_inn.add(chat_id)
    _open_main_after_sro.add(chat_id)
    _await_joiner_activity.discard(chat_id)
    _joiner_activity_by_chat.pop(chat_id, None)


def clear_await_inn(chat_id: int) -> None:
    _await_inn.discard(chat_id)


def is_awaiting_inn(chat_id: int) -> bool:
    return chat_id in _await_inn


def mark_open_main_after_sro(chat_id: int) -> None:
    _open_main_after_sro.add(chat_id)


def consume_open_main_after_sro(chat_id: int) -> bool:
    if chat_id in _open_main_after_sro:
        _open_main_after_sro.discard(chat_id)
        return True
    return False


def clear_onboarding_flags(chat_id: int) -> None:
    """Полный сброс онбординга (/start, смена организации)."""
    _await_inn.discard(chat_id)
    _open_main_after_sro.discard(chat_id)
    _await_joiner_activity.discard(chat_id)
    _joiner_activity_by_chat.pop(chat_id, None)


def clear_nav_mode_flags(chat_id: int) -> None:
    """Выход из FAQ/поиска в меню — не трогаем выбор направления без ИНН."""
    _await_inn.discard(chat_id)
    _open_main_after_sro.discard(chat_id)
    _await_joiner_activity.discard(chat_id)


def sro_ids_for_joiner_activity(activity: str) -> list[str]:
    """СРО направления для выбора без ИНН."""
    from sro_profiles import SRO_ACTIVITY

    ordered = _JOINER_SRO_ORDER.get(activity) or []
    known = {sid for sid, act in SRO_ACTIVITY.items() if act == activity}
    result = [sid for sid in ordered if sid in known]
    for sid in SRO_ACTIVITY:
        if SRO_ACTIVITY[sid] == activity and sid not in result:
            result.append(sid)
    return result


def begin_joiner_activity_pick(chat_id: int) -> None:
    """После «Пропустить»: выбрать направление (строй / проект / изыскания)."""
    _await_inn.discard(chat_id)
    _await_joiner_activity.add(chat_id)
    _open_main_after_sro.add(chat_id)
    _joiner_activity_by_chat.pop(chat_id, None)
    _pending_sro_pick.pop(chat_id, None)
    _pickable_sro_cache.pop(chat_id, None)
    _user_context.pop(chat_id, None)


def begin_joiner_sro_pick(chat_id: int, activity: str) -> list[str]:
    """После направления — список СРО этого типа."""
    ids = sro_ids_for_joiner_activity(activity)
    _await_joiner_activity.discard(chat_id)
    _joiner_activity_by_chat[chat_id] = activity
    _open_main_after_sro.add(chat_id)
    _pending_sro_pick[chat_id] = list(ids)
    _pickable_sro_cache[chat_id] = list(ids)
    return ids


def is_awaiting_joiner_activity(chat_id: int) -> bool:
    return chat_id in _await_joiner_activity


def clear_joiner_activity_await(chat_id: int) -> None:
    _await_joiner_activity.discard(chat_id)


def is_joiner_flow(chat_id: int) -> bool:
    """Онбординг без ИНН: выбор направления или СРО внутри направления."""
    if chat_id in _await_joiner_activity or chat_id in _joiner_activity_by_chat:
        return True
    return infer_joiner_activity_from_ids(_pickable_sro_cache.get(chat_id)) is not None


def get_joiner_activity(chat_id: int) -> str | None:
    act = _joiner_activity_by_chat.get(chat_id)
    if act:
        return act
    return infer_joiner_activity_from_ids(_pickable_sro_cache.get(chat_id))


def infer_joiner_activity_from_ids(sro_ids: list[str] | None) -> str | None:
    """Если список СРО совпадает с направлением без ИНН — вернуть stroy/proekt/izysk."""
    if not sro_ids or len(sro_ids) < 2:
        return None
    got = set(sro_ids)
    for activity in _JOINER_SRO_ORDER:
        if got == set(sro_ids_for_joiner_activity(activity)):
            return activity
    return None


def parse_joiner_activity_button(text: str) -> str | None:
    """Кнопка направления → stroy / proekt / izysk."""
    for label, activity in JOINER_ACTIVITY_CHOICES:
        if text == label:
            return activity
    return None


def joiner_activity_hint() -> str:
    return (
        "🆕 <b>Вы вступаете или смотрите без ИНН</b>\n\n"
        "Шаг 1. Выберите <b>направление</b>:\n\n"
        "• <b>Строители</b> — СРО НОСТРОЙ\n"
        "• <b>Проектировщики</b> — СРО НОПРИЗ (проектирование)\n"
        "• <b>Изыскания</b> — СРО НОПРИЗ (изыскания)\n\n"
        "Дальше выберете <b>конкретное СРО</b> — от этого зависят "
        "ответы ИИ, план проверок и бланки.\n\n"
        "<i>Когда станете членом — снова /start и введите ИНН: "
        "подставится ваше СРО автоматически.</i>"
    )


def joiner_sro_pick_hint(activity: str | None) -> str:
    act = ACTIVITY_LABEL.get(activity or "", activity or "СРО")
    return (
        f"📄 <b>Шаг 2. Выберите своё СРО</b> ({act})\n\n"
        "От выбора зависят ответы ИИ, ссылки, план проверок и бланки.\n"
        "Строителей, проектировщиков и изыскателей не смешиваем.\n\n"
        f"<i>Кнопка «{BACK_TO_DIRECTION_BUTTON}» — сменить направление. "
        f"«{RESTART_ORG_BUTTON}» — снова ИНН или без ИНН. "
        "Когда станете членом — /start и ИНН.</i>"
    )


def get_user_context(chat_id: int) -> dict | None:
    return _user_context.get(chat_id)


def get_user_sro_id(chat_id: int) -> str | None:
    ctx = _user_context.get(chat_id)
    return ctx.get("sro_id") if ctx else None


def get_user_profile(chat_id: int):
    return get_sro_profile(get_user_sro_id(chat_id))


def get_user_activity(chat_id: int) -> str | None:
    profile = get_user_profile(chat_id)
    return profile["activity"] if profile else None


def set_user_sro(chat_id: int, sro_id: str, *, inn: str | None = None) -> None:
    _user_context[chat_id] = {"sro_id": sro_id, "inn": inn}
    _pending_sro_pick.pop(chat_id, None)
    _persist_context()


def _set_default_sro_context(chat_id: int, sro_id: str, *, inn: str | None = None) -> None:
    """Временный контекст по умолчанию, не снимая ожидание выбора СРО."""
    _user_context[chat_id] = {"sro_id": sro_id, "inn": inn}
    _persist_context()


def clear_user_sro(chat_id: int) -> None:
    _user_context.pop(chat_id, None)
    _pending_sro_pick.pop(chat_id, None)
    _pickable_sro_cache.pop(chat_id, None)
    clear_onboarding_flags(chat_id)
    _persist_context()


def pending_sro_ids(chat_id: int) -> list[str] | None:
    ids = _pending_sro_pick.get(chat_id)
    return list(ids) if ids else None


def restore_pending_sro_pick(chat_id: int, sro_ids: list[str]) -> None:
    """Вернуть экран выбора СРО (после «Назад к выбору СРО»)."""
    if sro_ids:
        _pending_sro_pick[chat_id] = list(sro_ids)
        _pickable_sro_cache[chat_id] = list(sro_ids)


def cached_pickable_sro_ids(chat_id: int) -> list[str] | None:
    """СРО для повторного выбора (кнопка «Назад к выбору организации»)."""
    ids = _pickable_sro_cache.get(chat_id)
    if ids and len(ids) >= 2:
        return list(ids)
    # Joiner: кэш мог сброситься — собрать список заново по направлению
    act = _joiner_activity_by_chat.get(chat_id)
    if not act:
        act = infer_joiner_activity_from_ids(ids)
    if act:
        rebuilt = sro_ids_for_joiner_activity(act)
        if len(rebuilt) >= 2:
            _pickable_sro_cache[chat_id] = list(rebuilt)
            return list(rebuilt)
    return None


def is_back_to_sro_pick_button(text: str) -> bool:
    return (text or "").strip() in _BACK_TO_SRO_PICK_ALIASES


def is_restart_org_button(text: str) -> bool:
    return (text or "").strip() == RESTART_ORG_BUTTON


def context_button_label(sro_id: str) -> str:
    profile = get_sro_profile(sro_id)
    if not profile:
        return f"{CTX_BUTTON_PREFIX}{sro_id}"
    act = ACTIVITY_LABEL.get(profile["activity"], "")
    if act:
        return f"{CTX_BUTTON_PREFIX}{profile['name']} ({act})"
    return f"{CTX_BUTTON_PREFIX}{profile['name']}"


def parse_context_button(text: str) -> str | None:
    if not text.startswith(CTX_BUTTON_PREFIX):
        return None
    rest = text[len(CTX_BUTTON_PREFIX) :].strip()
    if " (" in rest:
        rest = rest.split(" (", 1)[0].strip()
    from sro_profiles import list_known_sro_ids

    for sid in list_known_sro_ids():
        p = get_sro_profile(sid)
        if p and p["name"] == rest:
            return sid
    return None


def _pickable_sro_ids(membership_ids: list[str]) -> list[str]:
    """
    СРО, между которыми нужен выбор: несколько комплектов бланков
    или разная деятельность (строй / проект / изыскания).
    """
    from blanki_sro import BLANKI_SRO_IDS

    blanki_members = [s for s in membership_ids if s in BLANKI_SRO_IDS]
    if len(blanki_members) >= 2:
        return blanki_members

    by_activity: dict[str, str] = {}
    for sro_id in membership_ids:
        profile = get_sro_profile(sro_id)
        if not profile:
            continue
        act = profile["activity"]
        if act not in by_activity or sro_id in BLANKI_SRO_IDS:
            by_activity[act] = sro_id
    if len(by_activity) >= 2:
        return list(by_activity.values())
    return []


def membership_ids_for_sro_pick(
    memberships: dict[str, dict],
) -> list[str]:
    """
    Какие СРО участвуют в выборе контекста/бланков.
    Только действующие «Член СРО» — исключённые в кнопки не попадают.
    Если действующих нет — fallback по всем записям на карточке.
    """
    if not memberships:
        return []
    active = [
        sid
        for sid, m in memberships.items()
        if (m.get("status") or "").startswith("Член")
    ]
    if len(active) >= 2:
        pickable = _pickable_sro_ids(active)
        return pickable if len(pickable) >= 2 else active
    if len(active) == 1:
        return active
    all_ids = list(memberships.keys())
    if len(all_ids) >= 2:
        pickable = _pickable_sro_ids(all_ids)
        if len(pickable) >= 2:
            return pickable
    return all_ids


def multi_sro_picker_hint(sro_ids: list[str]) -> str:
    lines: list[str] = []
    for sro_id in sro_ids:
        profile = get_sro_profile(sro_id)
        if not profile:
            continue
        act = ACTIVITY_LABEL.get(profile["activity"], profile["activity"])
        lines.append(f"• <b>{profile['short_title']}</b> — {act}")
    listing = "\n".join(lines) if lines else "—"
    return (
        "📄 <b>Организация в нескольких СРО</b>\n\n"
        f"{listing}\n\n"
        "Выберите <b>своё СРО</b> кнопкой ниже — от этого зависят "
        "ответы ИИ, план проверок и бланки.\n"
        "Строителей и проектировщиков не смешиваем.\n\n"
        "<i>После выбора откроется главное меню "
        f"(«{BACK_TO_SRO_PICK_BUTTON}» — сменить СРО этой организации; "
        f"«{RESTART_ORG_BUTTON}» — другой ИНН или без ИНН). "
        "Бланки — когда понадобятся: «Полезная информация» → «Проверяемые документы».</i>"
    )


def apply_context_from_memberships(chat_id: int, inn: str, membership_ids: list[str]) -> str:
    """
    Устанавливает контекст по членствам из реестра.
    Возвращает HTML-футер для карточки или пустую строку.
    """
    # Реальный ИНН — выходим из режима «без ИНН / направление»
    _await_joiner_activity.discard(chat_id)
    _joiner_activity_by_chat.pop(chat_id, None)

    if len(membership_ids) >= 2:
        _pickable_sro_cache[chat_id] = list(membership_ids)
        prev = get_user_context(chat_id)
        current_sro = (prev or {}).get("sro_id")
        if (
            current_sro
            and current_sro in membership_ids
            and (prev or {}).get("inn") == inn
        ):
            set_user_sro(chat_id, current_sro, inn=inn)
            line = format_activity_line(get_sro_profile(current_sro))
            return f"\n\n🤖 <i>Контекст ИИ и бланки: {line}</i>"

        _pending_sro_pick[chat_id] = list(membership_ids)
        _user_context[chat_id] = {"sro_id": None, "inn": inn}
        return (
            "\n\n⚠️ <b>Организация состоит в нескольких СРО.</b>\n"
            "Сначала выберите <b>своё СРО</b> кнопкой ниже — от этого зависят "
            "бланки, план проверок и ответы ИИ."
        )

    _pending_sro_pick.pop(chat_id, None)
    _pickable_sro_cache.pop(chat_id, None)
    if membership_ids:
        fallback = membership_ids[0]
        if get_sro_profile(fallback):
            set_user_sro(chat_id, fallback, inn=inn)
            line = format_activity_line(get_sro_profile(fallback))
            return f"\n\n🤖 <i>Контекст ИИ и бланки: {line}</i>"
    return ""


def context_picker_hint(chat_id: int) -> str | None:
    ids = pending_sro_ids(chat_id)
    if not ids or len(ids) < 2:
        return None
    return multi_sro_picker_hint(ids)


def ai_context_banner(chat_id: int) -> str:
    profile = get_user_profile(chat_id)
    if not profile:
        return (
            "\n\n<i>Контекст СРО не задан. Введите <b>ИНН</b> организации — "
            "бот подставит ваше СРО. Пока ответы как для Ассоциации «ГЕН».</i>"
        )
    act = ACTIVITY_LABEL.get(profile["activity"], "")
    return f"\n\n<i>Контекст: {profile['short_title']} ({act})</i>"
