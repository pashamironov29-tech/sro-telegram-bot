# -*- coding: utf-8 -*-
"""СРО-бот в MAX. Telegram не трогаем: отдельный процесс и токен.

Меню — только inline (в MAX нет ReplyKeyboard).
Личка адресуется по user_id. Long polling — для разработки, пока нет HTTPS webhook.
"""
from __future__ import annotations

import html
import logging
import os
import sys
import time
import types as pytypes
from pathlib import Path

# Облако Mail (O:\Рабочие) часто ломает Path.resolve() — WinError 1005.
_orig_resolve = Path.resolve


def _safe_resolve(self, strict=False):
    try:
        return _orig_resolve(self, strict=strict)
    except OSError:
        return Path(os.path.abspath(str(self)))


Path.resolve = _safe_resolve  # type: ignore[method-assign]

from docx import Document

from config_keys import GROQ_API_KEY, SRO_FILES_DIR
from ai_assistant import (
    AI_BUTTON,
    AI_MODE_HINT,
    enter_ai_mode,
    enter_faq_mode,
    enter_search_mode,
    exit_ai_mode,
    exit_faq_mode,
    exit_search_mode,
    get_ai_response,
    is_ai_mode,
    is_faq_mode,
    is_search_mode,
)
from blanki_sro import BLANKI_MENU_ITEMS, blanki_file_path, blanki_source_label, resolve_blanki_sro_id
from bot_disclaimers import FAQ_LINK_FOOTER, OFFICIAL_SOURCE_DISCLAIMER
from faq_menu_content import DOCUMENTS_LIST_TEXT, FAQ_LINKS, FAQ_TEXTS
from checko_client import (
    SECTIONS as CHECKO_SECTIONS,
    checko_configured,
    format_section as format_checko_section,
    site_url as checko_site_url,
)
from controller_access import (
    can_use_checko,
    enter_controller_work_mode,
    exit_controller_work_mode,
    is_controller,
    is_controller_work_mode,
)
from controller_ai import (
    CAI_AUDIO_EXTS,
    CAI_FILE_EXTS,
    CAI_IMAGE_EXTS,
    CAI_MAX_UPLOAD_BYTES,
    CONTROLLER_AI_BUTTON,
    CONTROLLER_AI_HINT,
    answer_about_upload,
    controller_free_chat,
    enter_controller_ai_mode,
    exit_controller_ai_mode,
    extract_text_from_bytes,
    extract_text_from_image,
    get_upload_context,
    is_controller_ai_mode,
    looks_like_doc_followup,
    remember_upload,
    safe_filename,
    summarize_upload_for_controller,
    transcribe_voice,
)
from nrs_search_links import (
    NRS_LINK_BUTTON,
    enter_nrs_link_mode,
    exit_nrs_link_mode,
    format_nrs_link_intro,
    format_nrs_link_reply,
    is_nrs_link_mode,
    nrs_registry_link_buttons,
)
from max_api import (
    MaxApi,
    MaxApiError,
    attachments_from_update,
    callback_id,
    callback_payload,
    dest_from_update,
    inline_keyboard,
    callback_button,
    link_button,
    sender_name,
    text_from_update,
)
from partners_data import get_partners_full_text
from reestr_sync import (
    enrich_reestr_entry,
    format_company_card,
    get_org_memberships,
    load_reestr_cache,
    membership_needs_detail_fetch,
    plany_key_from_filename,
)
from sro_about import (
    format_about_association,
    format_how_to_join_text,
    format_sroki_vstupleniya_text,
    sro_has_lichniy_kabinet,
)
from sro_context import (
    JOINER_ACTIVITY_CHOICES,
    RESTART_ORG_BUTTON,
    SKIP_ONBOARDING_BUTTON,
    apply_context_from_memberships,
    begin_await_inn,
    begin_joiner_activity_pick,
    begin_joiner_sro_pick,
    clear_await_inn,
    clear_joiner_activity_await,
    clear_nav_mode_flags,
    clear_onboarding_flags,
    clear_user_sro,
    consume_open_main_after_sro,
    context_button_label,
    context_picker_hint,
    get_user_context,
    get_user_profile,
    get_user_sro_id,
    is_awaiting_inn,
    is_awaiting_joiner_activity,
    joiner_activity_hint,
    joiner_sro_pick_hint,
    mark_open_main_after_sro,
    membership_ids_for_sro_pick,
    pending_sro_ids,
    set_user_sro,
)
from sro_fees import format_fees_message
from sro_profiles import ACTIVITY_LABEL, assert_prod_sro_ready, get_sro_profile
from trusted_members import format_trusted_members_message
from users_log import touch_user, users_count

assert_prod_sro_ready()

logging.basicConfig(
    filename="bot_max_errors.log",
    level=logging.ERROR,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

SRO_SITE = "https://www.srogen.ru"
SEARCH_ORG = "🔍 Поиск организации"
BACK_MENU = "⬅️ Назад в меню"
NAME_SEARCH_MIN_LEN = 4
NAME_SEARCH_LIST_MAX = 10
NAME_SEARCH_TOO_MANY = 15
NAME_SEARCH_COLLECT_CAP = 20
CARD_LOADING_TEXT = (
    "⏳ <b>Ищу данные по организации...</b>\n\n"
    "<i>Загружаю проверки с сайта СРО. Обычно 5–15 секунд. "
    "Пожалуйста, подождите — не нажимайте кнопки повторно.</i>"
)
HELP_TEXT = """ℹ️ <b>Справка по боту</b>

<b>Команды</b> (кнопка меню слева от поля ввода, если MAX её показывает, или введите вручную):
/start — главное меню
/help — справка
/search — поиск организации
/info — FAQ и бланки
/controller — меню контролёра СРО

В MAX нет нижней клавиатуры Telegram: кнопки — <b>под сообщением</b>.

🔍 Поиск — ИНН или часть названия по 15 СРО
❓ Полезная информация — FAQ и бланки
💬 ИИ-помощник — ориентир и ссылки на сайты СРО

<i>Можно сразу ввести ИНН или название компании.</i>"""

api: MaxApi | None = None
sro_database: dict[str, dict] = {}
reestr_database: dict[str, dict] = {}
folder_path = SRO_FILES_DIR


def html_esc(text: str) -> str:
    return html.escape(str(text or ""), quote=False)


def _token() -> str:
    try:
        from config_keys import MAX_BOT_TOKEN
    except ImportError:
        return ""
    return (MAX_BOT_TOKEN or "").strip()


def kb(*rows: list[dict]) -> list[dict]:
    return [inline_keyboard(list(rows))]


def row(*buttons: dict) -> list[dict]:
    return list(buttons)


def main_keyboard(user_id: int) -> list[dict]:
    if is_controller_work_mode(user_id):
        return controller_keyboard(user_id)
    rows = [
        row(callback_button(SEARCH_ORG, "menu:search")),
        row(
            callback_button("❓ Полезная информация", "menu:info"),
            callback_button(AI_BUTTON, "menu:ai"),
        ),
    ]
    if get_user_sro_id(user_id) or get_user_context(user_id):
        rows.append(row(callback_button(RESTART_ORG_BUTTON, "menu:restart")))
    if is_controller(user_id):
        rows.append(row(callback_button("👋 Меню контролёра", "menu:controller")))
    rows.append(row(callback_button("ℹ️ Справка", "menu:help")))
    return kb(*rows)


def controller_keyboard(user_id: int | None = None) -> list[dict]:
    rows = [
        row(
            callback_button(SEARCH_ORG, "menu:search"),
            callback_button(NRS_LINK_BUTTON, "menu:nrs"),
        ),
        row(
            callback_button("❓ Полезная информация", "menu:info"),
            callback_button(CONTROLLER_AI_BUTTON, "menu:cai"),
        ),
    ]
    if user_id is not None and get_user_sro_id(user_id):
        rows.append(row(callback_button(RESTART_ORG_BUTTON, "menu:restart")))
    rows.append(row(callback_button("ℹ️ Справка", "menu:help")))
    return kb(*rows)


def controller_menu_text() -> str:
    return (
        "👋 <b>Меню контролёра СРО</b>\n\n"
        f"🔍 <b>{SEARCH_ORG}</b> — ИНН или название по всем 15 СРО\n"
        "   └ после поиска: реестр СРО или <b>полная информация</b> (Checko)\n"
        f"👤 <b>{NRS_LINK_BUTTON}</b> — ФИО или номер в НОСТРОЙ / НОПРИЗ\n"
        "❓ <b>Полезная информация</b> — бланки, документы для проверки\n"
        f"🎙 <b>{CONTROLLER_AI_BUTTON}</b> — текст, голос, PDF/Word, фото документа\n\n"
        "<i>Обычное меню члена СРО — /start (без Checko).</i>\n\n"
        f"{OFFICIAL_SOURCE_DISCLAIMER}"
    )


def checko_fork_keyboard(inn: str, *, in_reestr: bool) -> list[dict]:
    rows = []
    if in_reestr:
        rows.append(row(callback_button("📦 Карточка реестра СРО", f"chk:r:{inn}")))
    rows.append(row(callback_button("🔎 Полная информация (Checko)", f"chk:f:{inn}")))
    rows.append(row(link_button("🌐 На checko.ru", checko_site_url(inn))))
    rows.append(back_main_row())
    return kb(*rows)


def checko_sections_keyboard(inn: str) -> list[dict]:
    rows = []
    pair: list[dict] = []
    for code, label, _method in CHECKO_SECTIONS:
        pair.append(callback_button(label, f"chk:s:{code}:{inn}"))
        if len(pair) == 2:
            rows.append(row(*pair))
            pair = []
    if pair:
        rows.append(row(*pair))
    if org_in_local_reestr(inn):
        rows.append(row(callback_button("📦 В реестре СРО", f"chk:r:{inn}")))
    rows.append(row(link_button("🌐 На checko.ru", checko_site_url(inn))))
    rows.append(back_main_row())
    return kb(*rows)


def onboarding_keyboard(user_id: int | None = None) -> list[dict]:
    rows = [
        row(callback_button(SEARCH_ORG, "menu:search")),
        row(callback_button(SKIP_ONBOARDING_BUTTON, "menu:skip")),
    ]
    if user_id is not None and is_controller(user_id):
        rows.append(row(callback_button("👋 Меню контролёра", "menu:controller")))
    rows.append(row(callback_button("ℹ️ Справка", "menu:help")))
    return kb(*rows)


def back_main_row() -> list[dict]:
    return row(callback_button(BACK_MENU, "menu:main"))


def info_keyboard() -> list[dict]:
    return kb(
        row(callback_button("❓ Часто задаваемые вопросы", "faq:root")),
        row(callback_button("📋 Проверяемые документы", "info:docs")),
        row(callback_button("💬 Спросить ИИ", "menu:ai")),
        back_main_row(),
    )


def faq_root_keyboard() -> list[dict]:
    return kb(
        row(callback_button("🏗 Для вступающих", "faq:join")),
        row(
            callback_button("👔 Действующим членам", "faq:members"),
            callback_button("🎓 Специалисты и НОК", "faq:nok"),
        ),
        row(callback_button("💰 Размеры взносов (КФ)", "faq:fees")),
        row(callback_button("🏢 Ассоциация и партнёры", "faq:assoc")),
        row(callback_button("❓ Назад в Полезное", "menu:info")),
    )


def faq_join_keyboard() -> list[dict]:
    return kb(
        row(callback_button("📝 Как вступить в СРО?", "faq:how")),
        row(callback_button("📄 Документы для вступления", "faq:join_docs")),
        row(callback_button("🏢 Требования к специалистам", "faq:specs")),
        row(callback_button("⏱ Сроки вступления", "faq:terms")),
        row(callback_button("🏠 Строительство для себя", "faq:own")),
        row(callback_button("⬅️ Назад в FAQ", "faq:root")),
    )


def faq_members_keyboard(user_id: int) -> list[dict]:
    rows = []
    sro_id = get_user_sro_id(user_id) or (get_user_profile(user_id) or {}).get("id")
    if sro_has_lichniy_kabinet(sro_id or "OGPS"):
        rows.append(row(callback_button("🔐 Личный кабинет", "faq:lk")))
    rows.extend(
        [
            row(
                callback_button("📄 Выписка", "faq:extract"),
                callback_button("🔄 Изменения в Реестр", "faq:changes"),
            ),
            row(
                callback_button("🔍 Расписание проверок", "faq:schedule"),
                callback_button("🛠 Устранение нарушений", "faq:violations"),
            ),
            row(callback_button("⚖️ База законов СРО", "faq:laws")),
            row(callback_button("💰 Возврат взноса", "faq:refund")),
            row(callback_button("⬅️ Назад в FAQ", "faq:root")),
        ]
    )
    return kb(*rows)


def faq_nok_keyboard() -> list[dict]:
    return kb(
        row(
            callback_button("📋 Документы в НРС", "faq:nrs_docs"),
            callback_button("👤 Кураторы НРС", "faq:nrs_cur"),
        ),
        row(
            callback_button("🎓 Правила НОК", "faq:nok_rules"),
            callback_button("🎓 Подготовка к НОК", "faq:nok_prep"),
        ),
        row(callback_button("⬅️ Назад в FAQ", "faq:root")),
    )


def faq_assoc_keyboard() -> list[dict]:
    return kb(
        row(callback_button("🏢 Об Ассоциации СРО", "faq:about")),
        row(callback_button("⭐ Доверенные члены", "faq:trusted")),
        row(
            callback_button("🌍 Филиалы СРО", "faq:regions"),
            callback_button("🤝 Партнеры и НО", "faq:partners"),
        ),
        row(
            callback_button("📩 Жалобы", "faq:feedback"),
            callback_button("❤️ Благотворительность", "faq:charity"),
        ),
        row(callback_button("⬅️ Назад в FAQ", "faq:root")),
    )


def blanki_keyboard(user_id: int) -> list[dict]:
    rows = []
    for key, label, _cap in BLANKI_MENU_ITEMS:
        rows.append(row(callback_button(label, f"blank:{key}")))
    rows.append(row(callback_button("❓ Назад в Полезное", "menu:info")))
    return kb(*rows)


def activity_keyboard() -> list[dict]:
    rows = [row(callback_button(label, f"act:{code}")) for label, code in JOINER_ACTIVITY_CHOICES]
    rows.append(row(callback_button(RESTART_ORG_BUTTON, "menu:restart")))
    return kb(*rows)


def sro_pick_keyboard(sro_ids: list[str], *, back_to_direction: bool = False) -> list[dict]:
    rows = [row(callback_button(context_button_label(sid), f"sro:{sid}")) for sid in sro_ids]
    if back_to_direction:
        rows.append(row(callback_button("⬅️ Назад к направлению", "menu:skip")))
    rows.append(row(callback_button(RESTART_ORG_BUTTON, "menu:restart")))
    rows.append(back_main_row())
    return kb(*rows)


def name_results_keyboard(results: list[tuple[str, str]]) -> list[dict]:
    rows = []
    for inn, name in results[:NAME_SEARCH_LIST_MAX]:
        title = (name or inn)[:60]
        rows.append(row(callback_button(f"{title} · {inn}", f"inn:{inn}")))
    rows.append(back_main_row())
    return kb(*rows)


def _site_for(user_id: int) -> str:
    prof = get_user_profile(user_id) or get_sro_profile("OGPS") or {}
    return (prof.get("site") or SRO_SITE).rstrip("/")


def _sro_id_for(user_id: int) -> str:
    return get_user_sro_id(user_id) or (get_user_profile(user_id) or {}).get("id") or "OGPS"


def faq_link_atts(user_id: int, topic: str) -> list[dict] | None:
    spec = FAQ_LINKS.get(topic)
    if not spec:
        return main_keyboard(user_id)
    path, label = spec
    url = _site_for(user_id) + path
    return kb(row(link_button(label, url)), back_main_row())


def send(user_id: int, text: str, attachments: list[dict] | None = None) -> None:
    assert api is not None
    api.send_message(user_id=user_id, text=text, attachments=attachments)


def answer_cb(update: dict, notification: str | None = None) -> None:
    cid = callback_id(update)
    if not cid or api is None:
        return
    try:
        api.answer_callback(cid, notification=notification or "OK")
    except Exception:
        logging.warning("answer_callback failed", exc_info=True)


def fake_message(user_id: int, update: dict):
    first, last, username = sender_name(update)
    user = pytypes.SimpleNamespace(
        id=user_id, first_name=first, last_name=last, username=username
    )
    chat = pytypes.SimpleNamespace(id=user_id)
    return pytypes.SimpleNamespace(from_user=user, chat=chat)


def load_plany() -> None:
    plany_path = os.path.join(folder_path, "plany")
    print("⏳ Сканирую планы проверок (plany)...", flush=True)
    try:
        files = [f for f in os.listdir(plany_path) if f.endswith(".docx")]
    except FileNotFoundError:
        print(f"⚠️ Нет папки plany: {plany_path}", flush=True)
        return
    for file_name in files:
        full_path = os.path.join(plany_path, file_name)
        sro_key = plany_key_from_filename(file_name)
        try:
            doc = Document(full_path)
        except Exception as exc:
            print(f"⚠️ Не прочитан {file_name}: {exc}", flush=True)
            continue
        for table in doc.tables:
            for row_i, tbl_row in enumerate(table.rows):
                if row_i == 0:
                    continue
                cells = [c.text.strip() for c in tbl_row.cells]
                inn = next((c.replace(" ", "") for c in cells if c.replace(" ", "").isdigit() and 9 <= len(c.replace(" ", "")) <= 12), "")
                if not inn:
                    continue
                name = next((c for c in cells if c and not c.replace(" ", "").isdigit() and len(c) > 3), "") or inn
                month = next((c for c in cells if c and any(ch.isalpha() for ch in c) and len(c) < 40 and c != name), "")
                rec = sro_database.setdefault(inn, {"name": name, "plans": {}, "sro_type": sro_key, "month": ""})
                if name and (not rec.get("name") or rec["name"] == inn):
                    rec["name"] = name
                if sro_key and month:
                    rec.setdefault("plans", {})[sro_key] = month
                rec["sro_type"] = ", ".join(rec.get("plans") or {sro_key: ""}.keys())
                rec["month"] = ", ".join((rec.get("plans") or {}).values())
    print(f"✅ Планы в памяти: {len(sro_database)} организаций", flush=True)


def format_company_card_html(inn: str, plany_data, reestr_data) -> str:
    text = format_company_card(inn, plany_data, reestr_data)
    lines = text.split("\n")
    if lines and lines[0].startswith("✅ "):
        lines[0] = f"✅ <b>{lines[0][2:]}</b>"
    return "\n".join(lines)


def build_company_response(inn: str) -> str | None:
    plany_data = sro_database.get(inn)
    reestr_data = reestr_database.get(inn)
    if not plany_data and not reestr_data:
        return None
    return format_company_card_html(inn, plany_data, reestr_data)


def looks_like_inn(text: str) -> bool:
    clean = text.replace(" ", "").replace("\xa0", "")
    return clean.isdigit() and 9 <= len(clean) <= 12


def normalize_inn(text: str) -> str:
    return text.replace(" ", "").replace("\xa0", "")


def _looks_like_address(text: str) -> bool:
    lower = (text or "").lower()
    return any(m in lower for m in ("г.", "ул.", "д.", "пр-кт", "область", "край", "район"))


def org_in_local_reestr(inn: str) -> bool:
    return inn in reestr_database or inn in sro_database


def search_companies_by_name(query: str) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _clean_name(name: str) -> str:
        return name.replace('"', "").replace("«", "").replace("»", "").lower()

    def _display_from_reestr(inn: str, reestr_data: dict) -> str:
        for membership in get_org_memberships(reestr_data).values():
            for field in ("short_name", "title", "full_name"):
                name = (membership.get(field) or "").strip()
                if name and not _looks_like_address(name):
                    return name
        title = (reestr_data.get("title") or "").strip()
        if title and not _looks_like_address(title):
            return title
        return ""

    def _add(inn: str, display: str) -> bool:
        if inn in seen or not display:
            return len(results) >= NAME_SEARCH_COLLECT_CAP
        results.append((inn, display))
        seen.add(inn)
        return len(results) >= NAME_SEARCH_COLLECT_CAP

    for inn, reestr_data in reestr_database.items():
        hit = False
        for membership in get_org_memberships(reestr_data).values():
            for field in ("short_name", "title", "full_name"):
                name = membership.get(field, "") or ""
                if name and query in _clean_name(name) and not _looks_like_address(name):
                    hit = True
                    break
            if hit:
                break
        if not hit:
            title = reestr_data.get("title") or ""
            if title and query in _clean_name(title) and not _looks_like_address(title):
                hit = True
        if hit:
            display = _display_from_reestr(inn, reestr_data) or (reestr_data.get("title") or "")
            if _add(inn, display):
                return results

    for inn, company in sro_database.items():
        company_name = (company.get("name") or "").strip()
        if not company_name or query not in _clean_name(company_name):
            continue
        display = company_name
        reestr_data = reestr_database.get(inn)
        if reestr_data:
            better = _display_from_reestr(inn, reestr_data)
            if better:
                display = better
        if _add(inn, display):
            return results
    return results


def send_org_not_found(user_id: int, query: str | None = None) -> None:
    if query and looks_like_inn(query):
        lead = (
            f"❌ Организация с ИНН <code>{normalize_inn(query)}</code> "
            "не найдена в базе бота."
        )
    elif query:
        lead = f"❌ По запросу «<b>{html_esc(query)}</b>» организация в базе не найдена."
    else:
        lead = "❌ Организация не найдена в базе бота."
    send(
        user_id,
        (
            f"{lead}\n\n"
            "Проверьте ИНН или название и попробуйте снова.\n\n"
            "Если организация должна быть в реестре, но не находится — "
            "обратитесь в Ассоциацию:\n"
            "📞 <code>+7 (495) 775-81-11</code>\n"
            "📧 <code>info@srogen.ru</code>\n"
            "🔗 https://www.srogen.ru/"
        ),
        main_keyboard(user_id),
    )


def send_company_card(user_id: int, inn: str) -> bool:
    reestr_data = reestr_database.get(inn)
    memberships = get_org_memberships(reestr_data)
    needs_detail = bool(
        memberships and any(membership_needs_detail_fetch(m) for m in memberships.values())
    )
    loading_id = None
    if needs_detail and api is not None:
        try:
            msg = api.send_message(user_id=user_id, text=CARD_LOADING_TEXT)
            body = (msg.get("message") or {}).get("body") or {}
            loading_id = body.get("mid") or body.get("seq")
        except Exception:
            loading_id = None
        try:
            enrich_reestr_entry(inn, reestr_database, timeout=25.0)
        except Exception:
            logging.warning("Не удалось догрузить карточку %s", inn, exc_info=True)

    response_text = build_company_response(inn)
    if not response_text:
        send(user_id, "❌ Не удалось загрузить карточку организации. Попробуйте позже.", main_keyboard(user_id))
        return False

    reestr_data = reestr_database.get(inn) or {}
    prev = get_user_context(user_id)
    if prev and prev.get("inn") != inn:
        clear_user_sro(user_id)
    memberships = get_org_memberships(reestr_data)
    membership_ids = membership_ids_for_sro_pick(memberships)
    response_text += apply_context_from_memberships(user_id, inn, membership_ids)

    pick_ids = pending_sro_ids(user_id)
    atts = sro_pick_keyboard(pick_ids) if pick_ids and len(pick_ids) >= 2 else main_keyboard(user_id)
    if loading_id and api is not None:
        try:
            api.edit_message(str(loading_id), text=response_text, attachments=atts)
        except Exception:
            send(user_id, response_text, atts)
    else:
        send(user_id, response_text, atts)
    if pick_ids and len(pick_ids) >= 2:
        hint = context_picker_hint(user_id)
        if hint:
            send(user_id, hint)
    return True


def context_ready_text(user_id: int) -> str:
    prof = get_user_profile(user_id)
    if not prof:
        return (
            "✅ Можно пользоваться меню.\n\n"
            "Чтобы бланки и план проверок были <b>вашего</b> СРО — "
            "введите ИНН через «🔍 Поиск организации»."
        )
    act = ACTIVITY_LABEL.get(prof["activity"], "")
    return (
        f"✅ Контекст: <b>{prof['short_title']}</b> ({act})\n\n"
        "Вопросы ИИ и план проверок — <b>по вашему СРО</b>."
    )


def welcome_text() -> str:
    return f"""👋 <b>Добро пожаловать в чат-бот реестра и сервисов СРО!</b>

🕐 Работает <b>24/7</b> для членов и кураторов <b>15 партнёрских СРО</b>.

📌 <b>Уже член СРО?</b> Введите <b>ИНН</b> организации — найдём карточку в реестре.

🔍 Или нажмите <b>{SEARCH_ORG}</b> — поиск по ИНН/названию без выбора СРО.

🆕 <b>Только вступаете?</b> Нажмите <b>Пропустить</b> → направление → конкретное СРО.

{OFFICIAL_SOURCE_DISCLAIMER}"""


def send_welcome(user_id: int, update: dict) -> None:
    touch_user(fake_message(user_id, update), event="start")
    exit_ai_mode(user_id)
    exit_faq_mode(user_id)
    exit_search_mode(user_id)
    exit_nrs_link_mode(user_id)
    exit_controller_ai_mode(user_id)
    exit_controller_work_mode(user_id)
    clear_onboarding_flags(user_id)
    begin_await_inn(user_id)
    hint = ""
    if is_controller(user_id):
        hint = "<i>Контролёрам: служебное меню — /controller</i>\n\n"
    send(user_id, hint + welcome_text(), onboarding_keyboard(user_id))


def open_controller_menu(user_id: int) -> None:
    exit_ai_mode(user_id)
    exit_controller_ai_mode(user_id)
    exit_faq_mode(user_id)
    exit_search_mode(user_id)
    exit_nrs_link_mode(user_id)
    clear_await_inn(user_id)
    enter_controller_work_mode(user_id)
    send(user_id, controller_menu_text(), controller_keyboard(user_id))


def open_nrs(user_id: int) -> None:
    exit_ai_mode(user_id)
    exit_search_mode(user_id)
    enter_nrs_link_mode(user_id)
    send(user_id, format_nrs_link_intro(), kb(back_main_row()))


def nrs_result_keyboard(query: str) -> list[dict]:
    """Каждая кнопка — свой реестр: НОСТРОЙ или НОПРИЗ."""
    rows = [row(link_button(label, url)) for label, url in nrs_registry_link_buttons(query)]
    rows.append(back_main_row())
    return kb(*rows)


def open_controller_ai(user_id: int) -> None:
    exit_search_mode(user_id)
    exit_nrs_link_mode(user_id)
    enter_controller_ai_mode(user_id)
    send(user_id, CONTROLLER_AI_HINT, kb(back_main_row()))


def present_found_organization(user_id: int, inn: str) -> str | None:
    """card / fork / None — как в Telegram для контролёра."""
    clean = normalize_inn(inn) if looks_like_inn(inn) else str(inn).strip()
    in_reestr = org_in_local_reestr(clean)
    if can_use_checko(user_id) and checko_configured() and not is_awaiting_inn(user_id):
        enter_search_mode(user_id)
        if in_reestr:
            send(
                user_id,
                f"✅ Организация найдена (ИНН <code>{clean}</code>)\n\n"
                "<b>Где смотреть?</b>\n"
                "<i>Можно сразу ввести другой ИНН — поиск ещё открыт.</i>",
                checko_fork_keyboard(clean, in_reestr=True),
            )
            return "fork"
        send(
            user_id,
            f"ИНН <code>{clean}</code> в реестре 15 СРО не найден.\n"
            "Можно открыть <b>полную информацию</b> (Checko).",
            checko_fork_keyboard(clean, in_reestr=False),
        )
        return "fork"
    if in_reestr and send_company_card(user_id, clean):
        return "card"
    return None


def open_main(user_id: int, text: str | None = None) -> None:
    exit_ai_mode(user_id)
    exit_controller_ai_mode(user_id)
    exit_faq_mode(user_id)
    exit_search_mode(user_id)
    exit_nrs_link_mode(user_id)
    clear_nav_mode_flags(user_id)
    if is_controller_work_mode(user_id):
        open_controller_menu(user_id)
        return
    send(user_id, text or "📋 <b>Главное меню</b> — выберите раздел:", main_keyboard(user_id))


def open_search(user_id: int) -> None:
    exit_ai_mode(user_id)
    exit_controller_ai_mode(user_id)
    exit_faq_mode(user_id)
    exit_nrs_link_mode(user_id)
    clear_await_inn(user_id)
    clear_joiner_activity_await(user_id)
    enter_search_mode(user_id)
    send(
        user_id,
        "🏢 <b>Универсальный поиск</b>\n\n"
        "Введите <b>ИНН</b> (только цифры) или часть названия "
        f"(минимум {NAME_SEARCH_MIN_LEN} символа) по <b>всем 15 СРО</b>.",
        kb(back_main_row()),
    )


def open_ai(user_id: int) -> None:
    exit_search_mode(user_id)
    enter_ai_mode(user_id)
    send(user_id, AI_MODE_HINT, kb(back_main_row()))


def handle_universal_search(user_id: int, user_text: str) -> None:
    if looks_like_inn(user_text):
        clean = normalize_inn(user_text)
        outcome = present_found_organization(user_id, clean)
        if outcome == "card":
            exit_search_mode(user_id)
            return
        if outcome == "fork":
            return
        send_org_not_found(user_id, user_text)
        return
    query = user_text.strip()
    if len(query) < NAME_SEARCH_MIN_LEN:
        send(
            user_id,
            f"Введите <b>ИНН</b> (9–12 цифр) или минимум <b>{NAME_SEARCH_MIN_LEN} символа</b> названия.",
            kb(back_main_row()),
        )
        return
    q = query.replace('"', "").replace("«", "").replace("»", "").lower().strip()
    results = search_companies_by_name(q)
    print(f"🔍 name search q={q!r} hits={len(results)}", flush=True)
    if len(results) == 1:
        outcome = present_found_organization(user_id, results[0][0])
        if outcome == "card":
            exit_search_mode(user_id)
        return
    if len(results) > NAME_SEARCH_TOO_MANY:
        send(
            user_id,
            f"🔍 По запросу «<b>{html_esc(user_text)}</b>» слишком много совпадений "
            f"(больше {NAME_SEARCH_TOO_MANY}). Уточните название или введите ИНН.",
            kb(back_main_row()),
        )
        return
    if len(results) > 1:
        send(
            user_id,
            f"🔍 Найдено <b>{len(results)}</b> организаций. Выберите кнопку:",
            name_results_keyboard(results),
        )
        return
    if can_use_checko(user_id) and checko_configured() and looks_like_inn(user_text):
        present_found_organization(user_id, user_text)
        return
    send_org_not_found(user_id, user_text)
    query = user_text.strip()
    if len(query) < NAME_SEARCH_MIN_LEN:
        send(
            user_id,
            f"Введите <b>ИНН</b> (9–12 цифр) или минимум <b>{NAME_SEARCH_MIN_LEN} символа</b> названия.",
            kb(back_main_row()),
        )
        return
    q = query.replace('"', "").replace("«", "").replace("»", "").lower().strip()
    results = search_companies_by_name(q)
    print(f"🔍 name search q={q!r} hits={len(results)}", flush=True)
    if len(results) == 1:
        send_company_card(user_id, results[0][0])
        exit_search_mode(user_id)
        return
    if len(results) > NAME_SEARCH_TOO_MANY:
        send(
            user_id,
            f"🔍 По запросу «<b>{html_esc(user_text)}</b>» слишком много совпадений "
            f"(больше {NAME_SEARCH_TOO_MANY}). Уточните название или введите ИНН.",
            kb(back_main_row()),
        )
        return
    if len(results) > 1:
        send(
            user_id,
            f"🔍 Найдено <b>{len(results)}</b> организаций. Выберите кнопку:",
            name_results_keyboard(results),
        )
        return
    send_org_not_found(user_id, user_text)


def send_faq_topic(user_id: int, topic: str) -> None:
    enter_faq_mode(user_id)
    sro_id = _sro_id_for(user_id)
    if topic == "how":
        text = format_how_to_join_text(sro_id)
    elif topic == "terms":
        text = format_sroki_vstupleniya_text(sro_id)
    elif topic == "fees":
        text = format_fees_message(sro_id)
    elif topic == "about":
        text = format_about_association(sro_id)
    elif topic == "trusted":
        text = format_trusted_members_message()
    elif topic == "partners":
        text = get_partners_full_text()
    elif topic == "lk":
        profile = get_user_profile(user_id) or get_sro_profile(sro_id) or {}
        if not sro_has_lichniy_kabinet(sro_id):
            text = (
                f"🔐 <b>Личный кабинет</b>\n\n"
                f"На сайте <b>{profile.get('short_title') or 'СРО'}</b> отдельной страницы ЛК нет.\n"
                f"Напишите на <code>info@srogen.ru</code> — название, ИНН, рег. номер."
            )
        else:
            email = "partner@srogen.ru" if sro_id == "OGPS" else "info@srogen.ru"
            text = (
                f"🔐 <b>Доступ к личному кабинету</b>\n\n"
                f"Для логина и пароля напишите на <code>{email}</code>\n"
                f"Укажите название, ИНН, адрес и рег. номер СРО."
            )
    else:
        text = FAQ_TEXTS.get(topic)
        if not text:
            send(user_id, "Раздел готовится. Пока смотрите меню FAQ.", faq_root_keyboard())
            return
    if topic != "trusted":
        text = text + FAQ_LINK_FOOTER
    send(user_id, text, faq_link_atts(user_id, topic))


def send_blanki(user_id: int, key: str) -> None:
    sro_id = resolve_blanki_sro_id(get_user_sro_id(user_id))
    path = blanki_file_path(folder_path, sro_id, key)
    caption = next((c for k, _l, c in BLANKI_MENU_ITEMS if k == key), "Бланк")
    caption += f"\n\nИсточник: {blanki_source_label(sro_id)}"
    if not path or not os.path.isfile(path) or api is None:
        send(
            user_id,
            "❌ Файл бланка не найден на этом компьютере. "
            "Проверьте папку sro files/blanki или скачайте с сайта.",
            blanki_keyboard(user_id),
        )
        return
    try:
        api.upload_and_send_file(
            path,
            user_id=user_id,
            caption=caption,
            attachments_extra=blanki_keyboard(user_id),
        )
    except MaxApiError as exc:
        logging.error("blanki send failed: %s", exc)
        send(user_id, f"❌ Не удалось отправить файл: {html_esc(str(exc)[:200])}", blanki_keyboard(user_id))


def handle_checko(user_id: int, payload: str) -> None:
    if not can_use_checko(user_id):
        send(user_id, "Checko доступен в /controller.", main_keyboard(user_id))
        return
    parts = payload.split(":")
    if len(parts) < 3:
        send(user_id, "Устаревшая кнопка Checko.", main_keyboard(user_id))
        return
    kind = parts[1]
    if kind == "r" and len(parts) >= 3:
        inn = parts[2]
        if not org_in_local_reestr(inn):
            send(user_id, "❌ В реестре 15 СРО этой организации нет.")
            return
        if send_company_card(user_id, inn):
            exit_search_mode(user_id)
        return
    if kind == "f" and len(parts) >= 3:
        inn = parts[2]
        try:
            text = format_checko_section("general", inn)
        except Exception as exc:
            logging.warning("Checko general: %s", exc)
            text = (
                f"🔎 <b>Полная информация</b> (ИНН <code>{inn}</code>)\n\n"
                "Не удалось загрузить краткие данные. Выберите раздел или сайт."
            )
        send(user_id, text, checko_sections_keyboard(inn))
        return
    if kind == "s" and len(parts) >= 4:
        section, inn = parts[2], parts[3]
        try:
            text = format_checko_section(section, inn)
        except Exception as exc:
            text = f"⚠️ Не удалось загрузить раздел: {html_esc(str(exc)[:200])}"
        send(user_id, text, checko_sections_keyboard(inn))
        return
    send(user_id, "Неизвестная команда Checko.", controller_keyboard(user_id))


def handle_callback(user_id: int, payload: str, update: dict) -> None:
    answer_cb(update)
    if payload == "menu:main":
        open_main(user_id)
        return
    if payload == "menu:search":
        open_search(user_id)
        return
    if payload == "menu:info":
        enter_faq_mode(user_id)
        send(user_id, "📁 <b>Полезная информация</b>\n\nВыберите раздел:", info_keyboard())
        return
    if payload == "menu:ai":
        open_ai(user_id)
        return
    if payload == "menu:help":
        send(user_id, HELP_TEXT, main_keyboard(user_id))
        return
    if payload == "menu:controller":
        if not is_controller(user_id):
            send(
                user_id,
                "⛔ Команда <code>/controller</code> — только для сотрудников контроля СРО.\n\n"
                "Обычное меню: /start",
                main_keyboard(user_id),
            )
            return
        open_controller_menu(user_id)
        return
    if payload == "menu:nrs":
        open_nrs(user_id)
        return
    if payload == "menu:cai":
        open_controller_ai(user_id)
        return
    if payload == "menu:restart":
        clear_user_sro(user_id)
        send_welcome(user_id, update)
        return
    if payload == "menu:skip":
        begin_joiner_activity_pick(user_id)
        send(user_id, joiner_activity_hint(), activity_keyboard())
        return
    if payload.startswith("act:"):
        activity = payload.split(":", 1)[1]
        sro_ids = begin_joiner_sro_pick(user_id, activity)
        send(
            user_id,
            joiner_sro_pick_hint(activity),
            sro_pick_keyboard(sro_ids, back_to_direction=True),
        )
        return
    if payload.startswith("sro:"):
        sid = payload.split(":", 1)[1]
        prev = get_user_context(user_id)
        inn = prev.get("inn") if prev else None
        set_user_sro(user_id, sid, inn=inn)
        clear_await_inn(user_id)
        clear_joiner_activity_await(user_id)
        consume_open_main_after_sro(user_id)
        prof = get_sro_profile(sid)
        act = ACTIVITY_LABEL.get(prof["activity"], "") if prof else ""
        title = prof["short_title"] if prof else sid
        send(
            user_id,
            f"✅ Выбрано: <b>{title}</b> ({act})\n\n{context_ready_text(user_id)}",
            main_keyboard(user_id),
        )
        return
    if payload.startswith("inn:"):
        inn = payload.split(":", 1)[1]
        outcome = present_found_organization(user_id, inn)
        if outcome == "card":
            exit_search_mode(user_id)
            clear_await_inn(user_id)
        return
    if payload.startswith("chk:"):
        handle_checko(user_id, payload)
        return
    if payload.startswith("blank:"):
        send_blanki(user_id, payload.split(":", 1)[1])
        return
    if payload == "info:docs":
        enter_faq_mode(user_id)
        send(user_id, DOCUMENTS_LIST_TEXT, faq_link_atts(user_id, "docs"))
        send(
            user_id,
            f"📄 <b>Бланки</b> ({blanki_source_label(get_user_sro_id(user_id))}). Выберите файл:",
            blanki_keyboard(user_id),
        )
        return
    if payload == "faq:root":
        enter_faq_mode(user_id)
        send(user_id, "📁 <b>FAQ</b> — выберите раздел:", faq_root_keyboard())
        return
    if payload == "faq:join":
        send(user_id, "🏗 <b>Для вступающих</b>", faq_join_keyboard())
        return
    if payload == "faq:members":
        send(user_id, "👔 <b>Действующим членам</b>", faq_members_keyboard(user_id))
        return
    if payload == "faq:nok":
        send(user_id, "🎓 <b>Специалисты и НОК</b>", faq_nok_keyboard())
        return
    if payload == "faq:assoc":
        send(user_id, "🏢 <b>Ассоциация и партнёры</b>", faq_assoc_keyboard())
        return
    if payload.startswith("faq:"):
        send_faq_topic(user_id, payload.split(":", 1)[1])
        return
    send(user_id, "Неизвестная кнопка. Откройте меню.", main_keyboard(user_id))




def _cai_kb() -> list[dict]:
    return kb(back_main_row())


def _seems_about_last_doc(q: str) -> bool:
    ql = (q or "").lower()
    return any(
        w in ql
        for w in (
            "этот",
            "этого",
            "здесь",
            "выше",
            "прислал",
            "загрузил",
            "файл",
            "документ",
            "фото",
            "скан",
        )
    )


def _send_controller_ai_text(user_id: int, question: str) -> None:
    q = (question or "").strip()
    if not q:
        send(user_id, "Пустой запрос — надиктуйте или напишите ещё раз.", _cai_kb())
        return
    doc_text, _name = get_upload_context(user_id)
    if doc_text and (looks_like_doc_followup(q) or _seems_about_last_doc(q)):
        send(user_id, answer_about_upload(q, user_id), _cai_kb())
        return
    send(user_id, controller_free_chat(q), _cai_kb())


def _att_payload(att: dict) -> dict:
    payload = att.get("payload")
    return payload if isinstance(payload, dict) else {}


def _att_url(att: dict) -> str:
    p = _att_payload(att)
    return (p.get("url") or att.get("url") or "").strip()


def _att_filename(att: dict, default: str) -> str:
    p = _att_payload(att)
    raw = p.get("filename") or p.get("file_name") or p.get("name") or att.get("filename") or default
    return safe_filename(str(raw))


def _download_att(att: dict) -> bytes:
    assert api is not None
    url = _att_url(att)
    if not url:
        p = _att_payload(att)
        logging.warning("MAX attachment without url: type=%s payload_keys=%s", att.get("type"), list(p))
        raise MaxApiError("У вложения нет url")
    return api.download_bytes(url)


def _handle_cai_audio(user_id: int, att: dict) -> None:
    send(user_id, "🎧 Распознаю голос…", _cai_kb())
    data = _download_att(att)
    fname = _att_filename(att, "voice.ogg")
    text = transcribe_voice(data, fname)
    if not text:
        send(
            user_id,
            "Не разобрал речь. Повторите голосовое громче/чётче или напишите текстом.",
            _cai_kb(),
        )
        return
    send(user_id, f"🗣 <b>Распознано:</b>\n{html_esc(text)}")
    _send_controller_ai_text(user_id, text)


def _handle_cai_image(user_id: int, att: dict) -> None:
    send(user_id, "🖼 Смотрю фото документа…", _cai_kb())
    data = _download_att(att)
    fname = _att_filename(att, "photo.jpg")
    mime = "image/png" if fname.lower().endswith(".png") else "image/jpeg"
    raw = extract_text_from_image(data, mime=mime)
    remember_upload(user_id, raw, "фото документа")
    summary = summarize_upload_for_controller(raw, "фото документа")
    send(user_id, f"🖼 <b>фото документа</b>\n\n{summary}", _cai_kb())


def handle_controller_ai_attachments(user_id: int, update: dict) -> bool:
    """True — вложения обработаны (или дан отказ)."""
    atts = [a for a in attachments_from_update(update) if isinstance(a, dict)]
    media = [
        a
        for a in atts
        if (a.get("type") or "").lower() in ("file", "audio", "image", "voice")
    ]
    if not media:
        return False
    if not is_controller(user_id):
        return False
    if not is_controller_ai_mode(user_id):
        if is_controller_work_mode(user_id):
            send(
                user_id,
                "Сначала откройте <b>🎙 ИИ-помощник</b>, затем пришлите голос, файл или фото.",
                controller_keyboard(user_id),
            )
            return True
        return False

    caption = text_from_update(update)
    handled = False
    for att in media:
        kind = (att.get("type") or "").lower()
        fname = _att_filename(att, "document")
        lower = fname.lower()
        try:
            if kind in ("audio", "voice") or any(lower.endswith(ext) for ext in CAI_AUDIO_EXTS):
                _handle_cai_audio(user_id, att)
                handled = True
                continue

            if kind == "image" or any(lower.endswith(ext) for ext in CAI_IMAGE_EXTS):
                _handle_cai_image(user_id, att)
                handled = True
                continue

            if not any(lower.endswith(ext) for ext in CAI_FILE_EXTS):
                send(
                    user_id,
                    "Пока принимаю PDF, Word (.doc и .docx), TXT и Excel (.xlsx).\n"
                    "Можно также прислать <b>фото</b> документа.",
                    _cai_kb(),
                )
                handled = True
                continue
            send(user_id, f"📄 Читаю «{html_esc(fname)}»…", _cai_kb())
            data = _download_att(att)
            if len(data) > CAI_MAX_UPLOAD_BYTES:
                send(
                    user_id,
                    "Файл слишком большой (лимит ~18 МБ). Пришлите короче или фото ключевых страниц.",
                    _cai_kb(),
                )
                handled = True
                continue
            raw = extract_text_from_bytes(data, fname)
            if not (raw or "").strip():
                send(
                    user_id,
                    "⚠️ Не удалось прочитать файл (нет текста и OCR не сработал).\n"
                    "Пришлите фото страниц крупнее или Word/PDF с текстовым слоем.",
                    _cai_kb(),
                )
                handled = True
                continue
            remember_upload(user_id, raw, fname)
            summary = summarize_upload_for_controller(raw, fname)
            send(user_id, f"📄 <b>{html_esc(fname)}</b>\n\n{summary}", _cai_kb())
            handled = True
        except RuntimeError as exc:
            msg = str(exc).lower()
            if "openrouter" in msg or "vision" in msg or "no_openrouter" in msg:
                send(
                    user_id,
                    "⚠️ Нужен OPENROUTER_API_KEY — распознавание голоса/фото недоступно.\n"
                    "Напишите текстом или пришлите PDF/Word.",
                    _cai_kb(),
                )
            else:
                logging.exception("controller AI attachment failed")
                send(user_id, "⚠️ Не удалось разобрать вложение. Попробуйте ещё раз.", _cai_kb())
            return True
        except Exception:
            logging.exception("controller AI attachment failed")
            send(user_id, "⚠️ Ошибка разбора файла. Пришлите PDF/Word или напишите текстом.", _cai_kb())
            return True

    if handled and caption and len(caption) >= 3:
        _send_controller_ai_text(user_id, caption)
        return True
    return handled


def handle_text(user_id: int, user_text: str, update: dict) -> None:
    touch_user(fake_message(user_id, update), event="message")
    low = user_text.strip().lower().replace("ё", "е")
    if low in ("/start", "start", "старт"):
        send_welcome(user_id, update)
        return
    if low in ("/help", "help", "помощь", "справка"):
        send(user_id, HELP_TEXT, main_keyboard(user_id))
        return
    if low in ("/search", "search"):
        open_search(user_id)
        return
    if low in ("/info", "info"):
        enter_faq_mode(user_id)
        send(user_id, "📁 <b>Полезная информация</b>", info_keyboard())
        return
    if low in ("/controller", "controller", "контролер", "контролёр"):
        if not is_controller(user_id):
            send(
                user_id,
                "⛔ Команда <code>/controller</code> — только для сотрудников контроля СРО.\n\n"
                "Обычное меню: /start",
                main_keyboard(user_id),
            )
            return
        open_controller_menu(user_id)
        return
    if low in ("/menu", "меню", "menu") or user_text == BACK_MENU:
        open_main(user_id)
        return

    # Явно открытый поиск — раньше НРС/ИИ, иначе ИНН уходит «в специалиста»
    if is_search_mode(user_id):
        handle_universal_search(user_id, user_text)
        return

    if is_ai_mode(user_id):
        result = get_ai_response(user_text, GROQ_API_KEY, chat_id=user_id)
        answer = result.get("text") or "Не удалось получить ответ. Попробуйте ещё раз."
        send(user_id, answer, kb(back_main_row()))
        return

    if is_controller_ai_mode(user_id):
        _send_controller_ai_text(user_id, user_text)
        return

    if is_nrs_link_mode(user_id):
        send(
            user_id,
            format_nrs_link_reply(user_text, chat_id=user_id),
            nrs_result_keyboard(user_text),
        )
        return

    if is_awaiting_joiner_activity(user_id):
        send(user_id, "📌 Выберите направление кнопкой ниже.", activity_keyboard())
        return

    if looks_like_inn(user_text) and (is_awaiting_inn(user_id) or is_search_mode(user_id) or True):
        # ИНН всегда пробуем как поиск — так удобнее, чем ждать кнопку.
        if is_awaiting_inn(user_id) or is_search_mode(user_id) or not is_faq_mode(user_id):
            clean = normalize_inn(user_text)
            mark_open_main_after_sro(user_id)
            outcome = present_found_organization(user_id, clean)
            if outcome == "fork":
                clear_await_inn(user_id)
                return
            if outcome == "card":
                clear_await_inn(user_id)
                exit_search_mode(user_id)
                if not pending_sro_ids(user_id):
                    consume_open_main_after_sro(user_id)
                    send(user_id, context_ready_text(user_id), main_keyboard(user_id))
                return
            if is_awaiting_inn(user_id):
                send(
                    user_id,
                    "❌ Организация не найдена в реестре.\n\n"
                    "• Проверьте ИНН\n"
                    f"• Если только вступаете — нажмите «{SKIP_ONBOARDING_BUTTON}».",
                    onboarding_keyboard(user_id),
                )
                return
            send_org_not_found(user_id, user_text)
            return

    if len(user_text.strip()) >= NAME_SEARCH_MIN_LEN and not user_text.startswith("/"):
        handle_universal_search(user_id, user_text)
        return

    send(
        user_id,
        "Напишите <b>ИНН</b> или название организации — или откройте меню кнопками.",
        main_keyboard(user_id),
    )


def dispatch(update: dict) -> None:
    utype = update.get("update_type") or ""
    user_id, _chat_id = dest_from_update(update)
    if not user_id:
        print(f"⚠️ update без user_id: {utype}", flush=True)
        return
    if utype == "bot_started":
        send_welcome(int(user_id), update)
        return
    if utype == "message_callback":
        handle_callback(int(user_id), callback_payload(update), update)
        return
    if utype == "message_created":
        uid = int(user_id)
        media_done = handle_controller_ai_attachments(uid, update)
        text = text_from_update(update)
        if media_done:
            return
        if text:
            handle_text(uid, text, update)
        return


def setup_commands() -> None:
    assert api is not None
    try:
        api.set_commands(
            [
                {"name": "start", "description": "Главное меню"},
                {"name": "help", "description": "Справка по боту"},
                {"name": "search", "description": "Поиск организации по ИНН"},
                {"name": "info", "description": "FAQ и бланки документов"},
                {"name": "controller", "description": "Меню контролёра СРО"},
            ]
        )
    except Exception as exc:
        print(f"⚠️ Команды MAX не обновлены: {exc}", flush=True)


def main() -> None:
    global api, reestr_database
    token = _token()
    if not token:
        print(
            "Нет MAX_BOT_TOKEN.\n"
            "1) Дождитесь статуса «создан» после модерации.\n"
            "2) Вставьте токен в локальный config_keys.py (в чат не присылать).\n"
            "3) Тексты заявки — файл MAX_ZAYAVKA.txt\n",
            flush=True,
        )
        sys.exit(1)

    load_plany()
    reestr_database = load_reestr_cache()
    if reestr_database:
        print(f"📋 Реестр: {len(reestr_database)} организаций", flush=True)
    else:
        print("⚠️ reestr_cache.json пуст или не найден", flush=True)

    api = MaxApi(token)
    try:
        me = api.get_me()
        print(
            f"✅ MAX API: {me.get('name') or me.get('username') or me} "
            f"(id={me.get('user_id')})",
            flush=True,
        )
    except MaxApiError as exc:
        print(f"❌ GET /me не прошёл: {exc}", flush=True)
        sys.exit(1)

    setup_commands()
    try:
        from prevent_sleep import install_for_bot

        if install_for_bot():
            print("💤 Автосон Windows отключён, пока бот запущен.", flush=True)
    except Exception:
        pass

    print(f"🚀 MAX-бот polling... пользователей в журнале: {users_count()}", flush=True)
    print("Telegram-бота этот процесс не запускает.", flush=True)

    marker = None
    while True:
        try:
            page = api.get_updates(marker=marker, timeout=30)
            updates = page.get("updates") or []
            if page.get("marker") is not None:
                marker = page["marker"]
            for upd in updates:
                try:
                    dispatch(upd)
                except Exception:
                    logging.error("dispatch failed", exc_info=True)
                    print("⚠️ Ошибка обработки апдейта, см. bot_max_errors.log", flush=True)
        except KeyboardInterrupt:
            print("Остановлен.", flush=True)
            break
        except MaxApiError as exc:
            logging.error("polling: %s", exc, exc_info=True)
            print(f"⚠️ MAX API: {exc}. Пауза 5 сек.", flush=True)
            time.sleep(5)
        except Exception as exc:
            logging.error("polling crash", exc_info=True)
            print(f"⚠️ Сбой polling: {exc}. Пауза 5 сек.", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    try:
        os.chdir(Path(__file__).resolve().parent)
    except OSError:
        os.chdir(Path(__file__).parent)
    main()
