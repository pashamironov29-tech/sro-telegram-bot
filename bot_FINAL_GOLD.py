import telebot
from telebot import apihelper
from docx import Document
import os
from telebot import types
# Импортируем наш секретный токен из соседнего файла secrets.py
from config_keys import BOT_TOKEN, SRO_FILES_DIR, GROQ_API_KEY
from ai_assistant import (
    AI_BUTTON, AI_MODE_HINT, FAQ_AI_BUTTON, FAQ_AI_HINT, FAQ_NOT_FOUND_TEXT,
    get_ai_response, enter_ai_mode, exit_ai_mode, is_ai_mode,
    enter_faq_mode, exit_faq_mode, is_faq_mode, should_route_to_ai,
    enter_search_mode, exit_search_mode, is_search_mode,
    local_ai_route_kind,
)
from bot_disclaimers import DOC_QA_DISCLAIMER, FAQ_LINK_FOOTER, OFFICIAL_SOURCE_DISCLAIMER
from feedback_log import (
    FB_CALLBACK,
    append_feedback,
    begin_await_expected,
    cancel_await_expected,
    has_last_ai,
    is_awaiting_expected,
    is_feedback_phrase,
    remember_ai_reply,
)
from sro_context import (
    ai_context_banner,
    apply_context_from_memberships,
    BACK_TO_DIRECTION_BUTTON,
    BACK_TO_SRO_PICK_BUTTON,
    begin_await_inn,
    begin_joiner_activity_pick,
    begin_joiner_sro_pick,
    cached_pickable_sro_ids,
    is_back_to_sro_pick_button,
    is_restart_org_button,
    clear_await_inn,
    clear_joiner_activity_await,
    clear_onboarding_flags,
    clear_nav_mode_flags,
    clear_user_sro,
    consume_open_main_after_sro,
    context_button_label,
    context_picker_hint,
    get_user_context,
    get_user_profile,
    get_user_sro_id,
    get_joiner_activity,
    is_awaiting_inn,
    is_awaiting_joiner_activity,
    is_joiner_flow,
    JOINER_ACTIVITY_CHOICES,
    joiner_activity_hint,
    joiner_sro_pick_hint,
    mark_open_main_after_sro,
    membership_ids_for_sro_pick,
    multi_sro_picker_hint,
    parse_context_button,
    parse_joiner_activity_button,
    pending_sro_ids,
    restore_pending_sro_pick,
    RESTART_ORG_BUTTON,
    set_user_sro,
    SKIP_ONBOARDING_BUTTON,
)
from sro_profiles import ACTIVITY_LABEL, get_sro_profile, site_base_for_sro
from blanki_sro import BLANKI_MENU_ITEMS, blanki_dir_for_sro, blanki_file_path, blanki_source_label, resolve_blanki_sro_id
from info_list_fill import (
    INFO_LIST_FILL_SRO_IDS,
    ZAYAVLENIE_PROVERKA_FILL_SRO_IDS,
    DOVERENNOST_FILL_SRO_IDS,
    auto_fill_source_disclaimer,
    generate_info_list_for_inn,
    generate_zayavlenie_proverka_for_inn,
    generate_doverennost_for_inn,
)
from trusted_members import (
    TRUSTED_BUTTON,
    format_trusted_members_message,
    trusted_members_welcome_snippet,
)
from sro_about import (
    JOIN_FAQ_MARKERS,
    about_url_for_sro,
    format_about_association,
    format_how_to_join_text,
    format_sroki_vstupleniya_text,
    join_url_for_sro,
    rewrite_srogen_path_for_sro,
    sro_has_lichniy_kabinet,
)
from sro_fees import fees_doc_path, format_fees_message
from reestr_sync import (
    load_reestr_cache, format_company_card, enrich_reestr_entry,
    plany_key_from_filename, sro_display_name, get_org_memberships,
    membership_needs_detail_fetch,
)
from controller_access import (
    can_use_checko,
    controller_chat_ids,
    enter_controller_work_mode,
    exit_controller_work_mode,
    is_controller,
    is_controller_work_mode,
)
from checko_client import (
    SECTIONS as CHECKO_SECTIONS,
    checko_configured,
    format_section as format_checko_section,
    site_url as checko_site_url,
)
from partners_data import (
    PARTNERS_PAGE_URL,
    format_partner_response,
    get_partners_full_text,
    match_partner_query,
)
from sro_contacts import SRO_CONTACTS, format_sro_contacts, match_sro_contact_query
from users_log import format_users_report, is_bot_admin, touch_user, users_count
from nrs_search_links import (
    NRS_LINK_BUTTON,
    can_use_nrs_link_pilot,
    enter_nrs_link_mode,
    exit_nrs_link_mode,
    format_nrs_link_intro,
    format_nrs_link_reply,
    is_nrs_link_mode,
    looks_like_nrs_person_query,
)
from doc_qa import (
    DOC_FALLBACK_NO,
    DOC_FALLBACK_YES,
    DOC_QA_ASK_BUTTON,
    DOC_QA_BACK_BUTTON,
    DOC_QA_BUTTON,
    DOC_QA_HINT,
    DOC_QA_INTRO,
    answer_from_document,
    clear_doc_fallback_pending,
    enter_doc_ask_mode,
    exit_doc_ask_mode,
    format_doc_qa_hint,
    format_doc_qa_intro,
    is_doc_ask_mode,
    pop_doc_fallback_pending,
)
from voprosy_faq import (
    format_voprosy_faq_response,
    get_voprosy_site_item,
    get_voprosy_site_section,
    get_voprosy_site_sections,
    list_voprosy_site_topics,
    resolve_voprosy_site_section_button,
    resolve_voprosy_site_topic_button,
)
# 1. Добавляем встроенный модуль логирования
import logging
import re
import time
import requests

_TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


def tg_call(method: str, payload: dict, timeout: float = 30):
    try:
        resp = requests.post(f"{_TG_API}/{method}", json=payload, timeout=timeout)
        data = resp.json()
        if not data.get("ok"):
            logging.warning("Telegram %s: %s", method, data.get("description"))
            return None
        return data.get("result")
    except Exception as exc:
        logging.warning("Telegram %s failed: %s", method, exc)
        return None


def tg_upload_document(chat_id: int) -> None:
    tg_call("sendChatAction", {"chat_id": chat_id, "action": "upload_document"}, timeout=8)

# 2. Настраиваем, куда и как записывать ошибки
# Находим папку, где лежит сам скрипт test.py
current_dir = os.path.dirname(os.path.abspath(__file__))
log_file_path = os.path.join(current_dir, "bot_errors.log")
logging.basicConfig(
    filename=log_file_path,
    level=logging.ERROR,
    format="%(asctime)s %(levelname)s %(message)s",
)

apihelper.CONNECT_TIMEOUT = 30
apihelper.READ_TIMEOUT = 60

# === МНОГОПОТОЧНОСТЬ ===
# Бот берет токен из скрытого файла secrets.py и запускается для всех одновременно
bot = telebot.TeleBot(BOT_TOKEN, num_threads=4)

_last_admin_error_alert: dict[str, float] = {}
_ADMIN_ERROR_COOLDOWN_SEC = 45.0


def _bot_admin_chat_ids() -> list[int]:
    try:
        from config_keys import BOT_ADMIN_IDS
    except Exception:
        return []
    if BOT_ADMIN_IDS is None:
        return []
    if isinstance(BOT_ADMIN_IDS, (int, str)):
        try:
            return [int(BOT_ADMIN_IDS)]
        except (TypeError, ValueError):
            return []
    out: list[int] = []
    for x in BOT_ADMIN_IDS:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


def _event_chat_and_user(event):
    chat = getattr(event, "chat", None)
    if chat is None:
        msg = getattr(event, "message", None)
        chat = getattr(msg, "chat", None) if msg is not None else None
    user = getattr(event, "from_user", None)
    return chat, user


def _event_user_action(event) -> str:
    text = getattr(event, "text", None)
    if text:
        return str(text).strip()
    data = getattr(event, "data", None)
    if data:
        return f"callback:{data}"
    return "—"


def notify_admins_about_error(func_name: str, event, exc: BaseException) -> bool:
    """Письмо админам в Telegram: кто, что нажал, какая ошибка."""
    import html as html_lib
    import traceback as tb_mod

    chat, user = _event_chat_and_user(event)
    chat_id = getattr(chat, "id", None)
    action = _event_user_action(event)
    uname = ""
    if user is not None:
        uname = (getattr(user, "username", None) or "").strip()
        full = " ".join(
            x for x in (
                getattr(user, "first_name", None) or "",
                getattr(user, "last_name", None) or "",
            ) if x
        ).strip()
    else:
        full = ""

    sig = f"{func_name}:{type(exc).__name__}:{str(exc)[:120]}"
    now = time.monotonic()
    last = _last_admin_error_alert.get(sig, 0.0)
    if now - last < _ADMIN_ERROR_COOLDOWN_SEC:
        return False
    _last_admin_error_alert[sig] = now

    tb_short = "".join(tb_mod.format_exception(type(exc), exc, exc.__traceback__))
    if len(tb_short) > 1800:
        tb_short = "…\n" + tb_short[-1800:]

    who = html_lib.escape(full or "—")
    if uname:
        who += f" (@{html_lib.escape(uname)})"
    body = (
        "🚨 <b>Ошибка бота СРО</b>\n\n"
        f"Функция: <code>{html_lib.escape(func_name)}</code>\n"
        f"Пользователь: {who}\n"
        f"chat_id: <code>{chat_id}</code>\n"
        f"Нажал / написал:\n<code>{html_lib.escape(action[:500])}</code>\n\n"
        f"<b>{html_lib.escape(type(exc).__name__)}</b>: "
        f"{html_lib.escape(str(exc)[:400])}\n\n"
        f"<pre>{html_lib.escape(tb_short)}</pre>"
    )
    if len(body) > 4000:
        body = body[:3900] + "\n…</pre>"

    ok_any = False
    for admin_id in _bot_admin_chat_ids():
        try:
            bot.send_message(admin_id, body, parse_mode="HTML")
            ok_any = True
        except Exception:
            logging.error("Не удалось отправить алерт админу %s", admin_id, exc_info=True)
    return ok_any


def log_errors(func):
    """Щит: лог + алерт админам + мягкий ответ пользователю."""
    def wrapper(event, *args, **kwargs):
        try:
            return func(event, *args, **kwargs)
        except Exception as e:
            logging.error("Ошибка в функции %s", func.__name__, exc_info=True)
            print(f"⚠️ Ошибка в {func.__name__}: {type(e).__name__}: {e}", flush=True)
            notified = False
            try:
                notified = notify_admins_about_error(func.__name__, event, e)
            except Exception:
                logging.error("Сбой notify_admins_about_error", exc_info=True)
            chat, _user = _event_chat_and_user(event)
            chat_id = getattr(chat, "id", None)
            if chat_id is None:
                return None
            try:
                if notified:
                    user_msg = (
                        "⚠️ Произошла внутренняя ошибка. "
                        "Разработчик уже уведомлен — попробуйте позже или /start."
                    )
                else:
                    user_msg = (
                        "⚠️ Произошла внутренняя ошибка. "
                        "Попробуйте позже или /start. "
                        "Если повторится — напишите в поддержку Ассоциации."
                    )
                safe_send_message(chat_id, user_msg)
            except Exception:
                pass
            return None
    return wrapper


def _is_tg_transient(exc: BaseException) -> bool:
    name = type(exc).__name__
    msg = str(exc).lower()
    return (
        "Timeout" in name
        or "Connection" in name
        or "RemoteDisconnected" in name
        or "timed out" in msg
        or "connection aborted" in msg
        or "connection reset" in msg
    )


def safe_send_message(chat_id, text, *, retries: int = 3, **kwargs):
    """send_message с повтором при обрывах до api.telegram.org."""
    last_exc: BaseException | None = None
    parse_mode = kwargs.get("parse_mode")
    for attempt in range(max(1, retries)):
        try:
            return bot.send_message(chat_id, text, **kwargs)
        except Exception as exc:
            last_exc = exc
            # Битый HTML — один раз без parse_mode
            if parse_mode and attempt == 0 and not _is_tg_transient(exc):
                kwargs = dict(kwargs)
                kwargs.pop("parse_mode", None)
                parse_mode = None
                continue
            if attempt < retries - 1 and _is_tg_transient(exc):
                import time

                time.sleep(0.5 * (attempt + 1))
                continue
            break
    if last_exc:
        raise last_exc
    return None


def safe_answer_callback(call_id, text: str | None = None, **kwargs) -> None:
    try:
        if text is None:
            bot.answer_callback_query(call_id, **kwargs)
        else:
            bot.answer_callback_query(call_id, text, **kwargs)
    except Exception as exc:
        print(f"⚠️ answer_callback_query: {type(exc).__name__}: {exc}", flush=True)


# === БЕЗОПАСНОСТЬ: ТОКЕН БОТА ОЧИЩЕН ===
# Теперь в этом файле нет секретных данных! Его можно смело показывать всем.

sro_database = {}

# Бот автоматически берет скрытый путь из файла secrets.py
folder_path = SRO_FILES_DIR
plany_path = os.path.join(folder_path, "plany")

print("⏳ Начинаю сканирование подпапки plany...")

try:
    months_keywords = ["январь", "февраль", "март", "апрель", "май", "июнь", 
                       "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]

    files = [f for f in os.listdir(plany_path) if f.endswith('.docx')]
    
    for file_name in files:
        full_path = os.path.join(plany_path, file_name)
        sro_key = plany_key_from_filename(file_name)
        sro_label = sro_display_name(sro_key)
        doc = Document(full_path)
        current_month = "Не указан"

        for table in doc.tables:
            for row in table.rows:
                cells_text = []
                for cell in row.cells:
                    txt = cell.text.strip()
                    if txt and txt not in cells_text:
                        cells_text.append(txt)
                
                if len(cells_text) == 1 or (len(cells_text) == 2 and cells_text.isdigit()):
                    for t in cells_text:
                        if any(m in t.lower() for m in months_keywords):
                            current_month = t
                            break
                    continue

                if len(cells_text) >= 2:
                    inn = ""
                    inn_index = -1
                    
                    for idx, text in enumerate(cells_text):
                        clean_text = text.replace(" ", "").replace("\xa0", "")
                        if clean_text.isdigit() and (9 <= len(clean_text) <= 12):
                            inn = clean_text
                            inn_index = idx
                            break
                    
                    if inn:
                        name = "Организация СРО"
                        potential_names = [t for t in cells_text[:inn_index] if not t.replace(" ", "").isdigit() and len(t) > 3]
                        if potential_names:
                            name = max(potential_names, key=len)
                        else:
                            all_texts = [t for t in cells_text if t.replace(" ","").replace("\xa0", "") != inn and not t.replace(" ", "").isdigit() and len(t) > 3]
                            if all_texts:
                                name = all_texts[0] # Добавили, чтобы убрать квадратные скобки и адрес!

                           # УМНАЯ СКЛЕЙКА ДЛЯ ОРГАНИЗАЦИЙ В НЕСКОЛЬКИХ СРО
                        if inn in sro_database:
                            if sro_database[inn]["name"][0].isdigit() and not name[0].isdigit():
                                sro_database[inn]["name"] = name
                            plans = sro_database[inn].setdefault("plans", {})
                            if sro_key not in plans:
                                plans[sro_key] = current_month
                                sro_database[inn]["sro_type"] = ", ".join(
                                    sro_display_name(k) for k in plans
                                )
                                sro_database[inn]["month"] = ", ".join(plans.values())
                        else:
                            sro_database[inn] = {
                                "name": name,
                                "plans": {sro_key: current_month},
                                "month": current_month,
                                "sro_type": sro_label,
                            }
                        
    print(f"✅ ВСЕ БАЗЫ СИНХРОНИЗИРОВАНЫ! Всего в памяти: {len(sro_database)}")

except Exception as e:
    print(f"❌ Ошибка при чтении папки plany: {e}")

reestr_database = load_reestr_cache()
if reestr_database:
    print(f"📋 Реестр с сайта загружен: {len(reestr_database)} организаций")
else:
    print("⚠️ Реестр с сайта не загружен. Запустите: py reestr_sync.py")

def format_company_card_html(inn: str, plany_data: dict | None, reestr_data: dict | None) -> str:
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


def looks_like_org_name_query(text: str) -> bool:
    """Короткий запрос похож на название/аббревиатуру, а не на вопрос для ИИ."""
    if match_partner_query(text):
        return False
    if should_route_to_ai(text):
        return False
    query = text.strip()
    lower = query.lower()
    if any(marker in lower for marker in ("ооо", "ао", "пао", "зао", "фгуп", "ип ", "акционер")):
        return True
    return " " not in query and 2 <= len(query) <= 10


def send_org_not_found(chat_id: int, query: str | None = None) -> None:
    if query and looks_like_inn(query):
        lead = (
            f"❌ Организация с ИНН <code>{normalize_inn(query)}</code> "
            "не найдена в базе бота."
        )
    elif query:
        lead = f"❌ По запросу «<b>{query}</b>» организация в базе не найдена."
    else:
        lead = "❌ Организация не найдена в базе бота."

    bot.send_message(
        chat_id,
        (
            f"{lead}\n\n"
            "Проверьте ИНН или название и попробуйте снова.\n\n"
            "Если организация должна быть в реестре, но не находится — "
            "обратитесь в Ассоциацию (возможна ошибка в данных или сбой):\n"
            "📞 <code>+7 (495) 775-81-11</code>\n"
            "📧 <code>info@srogen.ru</code>\n"
            "🔗 https://www.srogen.ru/"
        ),
        parse_mode="HTML",
    )


def send_sro_contact_reply(chat_id: int, user_text: str) -> bool:
    """«Номер ОСОТ» / «связь с ОГПО» — контакты с сайта этого СРО."""
    sro_id = match_sro_contact_query(user_text)
    if not sro_id:
        return False
    text = format_sro_contacts(sro_id, question=user_text.strip())
    if not text:
        return False
    bot.send_message(chat_id, text, parse_mode="HTML")
    return True


def send_partner_reply(chat_id: int, user_text: str) -> bool:
    match = match_partner_query(user_text)
    if not match:
        return False
    result = format_partner_response(user_text, match)
    url, label = PARTNERS_PAGE_URL, "🌐 Все партнёры на сайте СРО"
    markup = site_link_markup(url, label)
    bot.send_message(chat_id, result["text"], parse_mode="HTML", reply_markup=markup)
    return True


def handle_universal_search(chat_id: int, user_text: str) -> bool:
    """Режим «Поиск организации»: только реестр, без ИИ и раздела партнёров."""
    if looks_like_inn(user_text):
        clean_inn = normalize_inn(user_text)
        outcome = present_found_organization(
            chat_id,
            clean_inn,
            reply_markup=get_main_keyboard(chat_id),
        )
        if outcome == "card":
            # Карточка реестра уже отдана — поиск можно закрыть.
            exit_search_mode(chat_id)
            return True
        if outcome == "fork":
            # Развилка Checko: режим поиска оставляем, чтобы можно было искать дальше.
            return True
        send_org_not_found(chat_id, user_text)
        return True

    query = user_text.strip()
    if len(query) < 2:
        bot.send_message(
            chat_id,
            "Введите ИНН (9–12 цифр) или минимум 2 символа названия организации.",
        )
        return True

    if handle_org_name_search(chat_id, user_text, force=True):
        return True

    send_org_not_found(chat_id, user_text)
    return True


def handle_org_name_search(chat_id: int, user_text: str, *, force: bool = False) -> bool:
    """Поиск по названию. True — запрос обработан (найдено или «не найдено»)."""
    query = user_text.replace('"', "").replace("«", "").replace("»", "").lower().strip()
    if len(query) < 2:
        return False

    results = search_companies_by_name(query)
    print(f"🔍 name search q={query!r} hits={len(results)}", flush=True)
    if len(results) == 1:
        outcome = present_found_organization(
            chat_id,
            results[0][0],
            reply_markup=get_main_keyboard(chat_id),
        )
        if outcome == "card" and is_search_mode(chat_id):
            exit_search_mode(chat_id)
        return bool(outcome)

    if len(results) > 1:
        inline_markup = types.InlineKeyboardMarkup()
        for inn, name in results[:10]:
            btn = types.InlineKeyboardButton(text=f"🏢 {name}", callback_data=f"search_inn:{inn}")
            inline_markup.add(btn)
        response_text = (
            f"🔍 По запросу «<b>{user_text}</b>» найдено организаций: {len(results)}\n"
            "<i>Выберите нужную компанию из списка ниже или уточните название:</i>"
        )
        if len(results) > 10:
            response_text += "\n\n⚠️ <i>Показаны первые 10. Уточните название для более точного поиска.</i>"
        bot.send_message(chat_id, response_text, parse_mode="HTML", reply_markup=inline_markup)
        return True

    if force or looks_like_org_name_query(user_text):
        send_org_not_found(chat_id, user_text)
        return True
    return False

CARD_LOADING_TEXT = (
    "⏳ <b>Ищу данные по организации...</b>\n\n"
    "<i>Загружаю проверки с сайта СРО. Обычно 5–15 секунд. "
    "Пожалуйста, подождите — не нажимайте кнопки повторно.</i>"
)


def org_in_local_reestr(inn: str) -> bool:
    return inn in reestr_database or inn in sro_database


CHECKO_SECTIONS_PAGE = 8  # все основные разделы на одном экране


def get_checko_fork_keyboard(inn: str, *, in_reestr: bool) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    if in_reestr:
        kb.add(
            types.InlineKeyboardButton(
                "📦 В реестре СРО",
                callback_data=f"chk:r:{inn}",
            )
        )
    kb.add(
        types.InlineKeyboardButton(
            "🔎 Полная информация",
            callback_data=f"chk:f:{inn}",
        )
    )
    return kb


def get_checko_sections_keyboard(inn: str, page: int = 0) -> types.InlineKeyboardMarkup:
    """Меню разделов страницами (по 6), не длинной простынёй."""
    total = len(CHECKO_SECTIONS)
    pages = max(1, (total + CHECKO_SECTIONS_PAGE - 1) // CHECKO_SECTIONS_PAGE)
    page = max(0, min(int(page), pages - 1))
    start = page * CHECKO_SECTIONS_PAGE
    chunk = CHECKO_SECTIONS[start : start + CHECKO_SECTIONS_PAGE]

    kb = types.InlineKeyboardMarkup(row_width=2)
    row: list[types.InlineKeyboardButton] = []
    for code, label, _method in chunk:
        # короче подписи на кнопках — меньше высота ряда
        short = label
        for prefix in ("📋 ", "🔥 ", "📄 ", "📞 ", "💼 ", "📈 ", "💰 ", "👤 ", "👥 ",
                       "🔗 ", "📜 ", "⭐ ", "🏛 ", "📅 ", "⚖️ ", "💵 ", "👷 ", "🕒 "):
            if short.startswith(prefix):
                short = short[len(prefix):]
                break
        if len(short) > 22:
            short = short[:20] + "…"
        row.append(
            types.InlineKeyboardButton(
                short,
                callback_data=f"chk:s:{code}:{inn}",
            )
        )
        if len(row) == 2:
            kb.row(*row)
            row = []
    if row:
        kb.row(*row)

    nav: list[types.InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            types.InlineKeyboardButton(
                "⬅️ Ещё разделы",
                callback_data=f"chk:m:{inn}:{page - 1}",
            )
        )
    if page < pages - 1:
        nav.append(
            types.InlineKeyboardButton(
                "Ещё разделы ➡️",
                callback_data=f"chk:m:{inn}:{page + 1}",
            )
        )
    if nav:
        kb.row(*nav)

    kb.add(
        types.InlineKeyboardButton(
            "🌐 На checko.ru",
            url=checko_site_url(inn),
        )
    )
    if org_in_local_reestr(inn):
        kb.add(
            types.InlineKeyboardButton(
                "📦 Карточка реестра СРО",
                callback_data=f"chk:r:{inn}",
            )
        )
    return kb


def get_checko_after_section_keyboard(inn: str) -> types.InlineKeyboardMarkup:
    """Под ответом раздела — только 2–3 кнопки, чтобы не задевать при скролле."""
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton(
            "📂 Другие разделы",
            callback_data=f"chk:m:{inn}:0",
        )
    )
    kb.add(
        types.InlineKeyboardButton(
            "🌐 На checko.ru",
            url=checko_site_url(inn),
        )
    )
    if org_in_local_reestr(inn):
        kb.add(
            types.InlineKeyboardButton(
                "📦 Карточка реестра СРО",
                callback_data=f"chk:r:{inn}",
            )
        )
    return kb


def present_found_organization(chat_id: int, inn: str, reply_markup=None) -> str | None:
    """
    Контролёр (не онбординг ИНН): развилка реестр СРО / Checko.
    Остальные и онбординг — сразу send_company_card.

    Returns:
        "fork" — показана развилка Checko (режим поиска не сбрасывать),
        "card" — отдана карточка реестра,
        None — организация не найдена в локальном реестре (и не Checko-fork).
    """
    clean = normalize_inn(inn) if looks_like_inn(inn) else str(inn).strip()
    in_reestr = org_in_local_reestr(clean)
    if (
        can_use_checko(chat_id)
        and not is_awaiting_inn(chat_id)
        and checko_configured()
    ):
        # Пока висит развилка — универсальный поиск остаётся активным.
        enter_search_mode(chat_id)
        if in_reestr:
            bot.send_message(
                chat_id,
                f"Организация найдена (ИНН <code>{clean}</code>).\n\n"
                "<b>Где смотреть?</b>\n"
                "<i>Можно сразу ввести другой ИНН или название — поиск ещё открыт.</i>",
                parse_mode="HTML",
                reply_markup=get_checko_fork_keyboard(clean, in_reestr=True),
            )
            return "fork"
        bot.send_message(
            chat_id,
            f"ИНН <code>{clean}</code> в реестре 15 СРО не найден.\n"
            "Можно открыть <b>полную информацию</b> (Checko).\n"
            "<i>Или введите другой ИНН / название — поиск ещё открыт.</i>",
            parse_mode="HTML",
            reply_markup=get_checko_fork_keyboard(clean, in_reestr=False),
        )
        return "fork"
    if in_reestr:
        if send_company_card(chat_id, clean, reply_markup=reply_markup):
            return "card"
        return None
    return None


def _deliver_company_card(chat_id: int, text: str, reply_markup=None, loading_msg=None) -> None:
    if loading_msg:
        try:
            bot.edit_message_text(
                text,
                chat_id,
                loading_msg.message_id,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
            return
        except Exception:
            try:
                bot.delete_message(chat_id, loading_msg.message_id)
            except Exception:
                pass
    bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=reply_markup)


def send_company_card(chat_id: int, inn: str, reply_markup=None) -> bool:
    reestr_data = reestr_database.get(inn)
    memberships = get_org_memberships(reestr_data)
    needs_detail_fetch = bool(
        memberships and any(membership_needs_detail_fetch(m) for m in memberships.values())
    )

    loading_msg = None
    if needs_detail_fetch:
        try:
            bot.send_chat_action(chat_id, "typing")
        except Exception:
            pass
        loading_msg = bot.send_message(chat_id, CARD_LOADING_TEXT, parse_mode="HTML")
        try:
            enrich_reestr_entry(inn, reestr_database, timeout=25.0)
        except Exception:
            logging.warning("Не удалось догрузить карточку организации %s", inn, exc_info=True)

    response_text = build_company_response(inn)
    if not response_text:
        if loading_msg:
            try:
                bot.edit_message_text(
                    "❌ Не удалось загрузить карточку организации. Попробуйте позже.",
                    chat_id,
                    loading_msg.message_id,
                    parse_mode="HTML",
                )
            except Exception:
                pass
        return False

    reestr_data = reestr_database.get(inn) or {}
    prev = get_user_context(chat_id)
    if prev and prev.get("inn") != inn:
        clear_user_sro(chat_id)
    memberships = get_org_memberships(reestr_data)
    membership_ids = membership_ids_for_sro_pick(memberships)
    response_text += apply_context_from_memberships(chat_id, inn, membership_ids)

    pick_ids = pending_sro_ids(chat_id)
    card_markup = reply_markup
    if pick_ids and len(pick_ids) >= 2:
        card_markup = get_sro_context_picker_keyboard(pick_ids)

    _deliver_company_card(chat_id, response_text, card_markup, loading_msg)

    if pick_ids and len(pick_ids) >= 2:
        hint = context_picker_hint(chat_id)
        if hint:
            bot.send_message(chat_id, hint, parse_mode="HTML")
    return True


def search_companies_by_name(query: str) -> list[tuple[str, str]]:
    results = []
    seen = set()

    for inn, company_data in sro_database.items():
        company_name = company_data.get("name", "")
        cleaned = company_name.replace('"', "").replace("«", "").replace("»", "").lower()
        if query in cleaned:
            results.append((inn, company_name))
            seen.add(inn)

    for inn, reestr_data in reestr_database.items():
        if inn in seen:
            continue
        for membership in get_org_memberships(reestr_data).values():
            for field in ("short_name", "title", "full_name"):
                name = membership.get(field, "") or ""
                cleaned = name.replace('"', "").replace("«", "").replace("»", "").lower()
                if query in cleaned:
                    results.append((inn, name))
                    seen.add(inn)
                    break
            if inn in seen:
                break
        if inn not in seen:
            title = reestr_data.get("title") or ""
            cleaned = title.replace('"', "").replace("«", "").replace("»", "").lower()
            if title and query in cleaned:
                results.append((inn, title))
                seen.add(inn)

    return results


# --- ОФИЦИАЛЬНЫЙ ТЕКСТ: КАК ВСТУПИТЬ В СРО ---
# Актуальный текст — format_how_to_join_text(sro_id); константа — fallback для ОГПС.
how_to_join_text = format_how_to_join_text("OGPS")

# --- ТЕКСТ ПЕРЕЧНЯ ПРОВЕРЯЕМЫХ ДОКУМЕНТОВ ---
documents_list_text = (
    "📋 <b>Основные документы, подлежащие проверке при контроле СРО:</b>\n\n"
    "1. <b>Доверенность</b> на право представлять интересы организации при проверке.\n"
    "2. <b>Информационный лист</b> с актуальными сведениями об организации на день проверки.\n"
    "3. <b>Учредительные документы</b> (Устав, Лист записи ЕГРЮЛ, ИНН) — в случае изменений.\n"
    "4. <b>Договор и Полис страхования</b> гражданской ответственности.\n"
    "5. <b>Документы на специалистов НРС</b> (Дипломы, УПК, Свидетельства НОК, Трудовые книжки, Должностные инструкции).\n"
    "6. <b>Документы по контролю качества</b> выполняемых работ.\n\n"
    "👇 <i>Вы можете скачать официальный перечень и бланки документов по кнопкам ниже:</i>"
)

def finish_button_reply(chat_id, text, reply_markup=None, parse_mode="HTML", **send_kwargs):
    last_exc = None
    for attempt in range(3):
        try:
            bot.send_message(
                chat_id,
                text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                **send_kwargs,
            )
            return
        except Exception as exc:
            last_exc = exc
            # Сеть/Telegram иногда рвёт соединение — не пугаем пользователя с первой попытки
            if attempt < 2 and (
                "Connection" in type(exc).__name__
                or "Timeout" in type(exc).__name__
                or "RemoteDisconnected" in type(exc).__name__
            ):
                import time

                time.sleep(0.6 * (attempt + 1))
                continue
            # Битый HTML — повтор без разметки
            if parse_mode and attempt == 0:
                try:
                    bot.send_message(chat_id, text, reply_markup=reply_markup, **send_kwargs)
                    return
                except Exception as exc2:
                    last_exc = exc2
            break
    if last_exc:
        raise last_exc


def _blanki_kit_footer(chat_id: int) -> str:
    return f"\n\n<i>Шаблон: {blanki_source_label(get_user_sro_id(chat_id))}</i>"


def send_blanki_file(chat_id: int, path_file: str, caption: str, error_text: str) -> None:
    try:
        tg_upload_document(chat_id)
        full_caption = caption + _blanki_kit_footer(chat_id)
        with open(path_file, "rb") as file:
            bot.send_document(chat_id, file, caption=full_caption, parse_mode="HTML")
    except Exception:
        bot.send_message(chat_id, error_text, parse_mode="HTML")


def _download_docs_intro(chat_id: int) -> str:
    label = blanki_source_label(get_user_sro_id(chat_id))
    if cached_pickable_sro_ids(chat_id):
        other = (
            f" Другое СРО этой организации — кнопка «{BACK_TO_SRO_PICK_BUTTON}»."
        )
    else:
        other = " Чтобы подставить формы другого СРО — найдите организацию по ИНН."
    return (
        "📋 <b>Выберите документ из перечня для скачивания бланка:</b>\n\n"
        f"ℹ️ <i>Комплект бланков: {label}.{other}</i>"
    )


def handle_blanki_menu_text(chat_id: int, user_text: str, sro_files_root: str) -> bool:
    """Кнопки скачивания бланков — не поиск организации (важно в режиме /search)."""
    # Сначала узнаём, нажали ли именно кнопку бланка. Иначе при незавершённом
    # выборе СРО любой текст (новый ИНН, поиск) ловился и снова показывал
    # старый «Организация в нескольких СРО» — баг контролёров/поиска.
    matched_item = None
    for index, (key, button_label, caption) in enumerate(BLANKI_MENU_ITEMS):
        if index == 0:
            matched = user_text == button_label
        else:
            short = button_label.split(". ", 1)[-1]
            matched = short in user_text
        if matched:
            matched_item = (key, button_label, caption)
            break
    if not matched_item:
        return False

    pick_ids = pending_sro_ids(chat_id)
    if pick_ids and len(pick_ids) >= 2:
        bot.send_message(
            chat_id,
            multi_sro_picker_hint(pick_ids),
            parse_mode="HTML",
            reply_markup=get_sro_context_picker_keyboard(pick_ids),
        )
        return True

    key, _button_label, caption = matched_item
    sro_id = get_user_sro_id(chat_id)
    sid = resolve_blanki_sro_id(sro_id)
    path = blanki_file_path(sro_files_root, sro_id, key)
    send_caption = caption
    ctx = get_user_context(chat_id)
    inn = (ctx or {}).get("inn")

    # Автозаполнение: инфолист, заявление на проверку, доверенность
    needs_autofill = (
        (key == "info_list" and sid in INFO_LIST_FILL_SRO_IDS)
        or (key == "zayavlenie_proverka" and sid in ZAYAVLENIE_PROVERKA_FILL_SRO_IDS)
        or (key == "doverennost" and sid in DOVERENNOST_FILL_SRO_IDS)
    )
    if needs_autofill and not inn:
        send_caption = (
            f"{caption}\n\n"
            "ℹ️ <i>Автозаполнение сработает после ввода <b>ИНН</b> организации "
            "(поиск или /start). Сейчас — пустой шаблон.</i>"
        )
    elif needs_autofill and inn:
        blanki_dir = blanki_dir_for_sro(sro_files_root, sid)
        filled_path = None
        form_data = None
        filled_flags = None
        disclaimer = None
        try:
            # Догрузить карточку (адрес, ОГРН, руководитель), если в кэше только список
            if inn in reestr_database:
                enrich_reestr_entry(inn, reestr_database, timeout=20.0)
            if key == "info_list":
                filled_path, form_data, filled_flags = generate_info_list_for_inn(
                    inn,
                    blanki_dir,
                    sro_database.get(inn),
                    reestr_database.get(inn),
                    preferred_sro_id=sid,
                )
                disclaimer = auto_fill_source_disclaimer(sid, doc_kind="info_list")
            elif key == "zayavlenie_proverka":
                filled_path, form_data, filled_flags = generate_zayavlenie_proverka_for_inn(
                    inn,
                    blanki_dir,
                    sro_database.get(inn),
                    reestr_database.get(inn),
                    preferred_sro_id=sid,
                )
                disclaimer = auto_fill_source_disclaimer(
                    sid, doc_kind="zayavlenie_proverka"
                )
            else:
                filled_path, form_data, filled_flags = generate_doverennost_for_inn(
                    inn,
                    blanki_dir,
                    sro_database.get(inn),
                    reestr_database.get(inn),
                    preferred_sro_id=sid,
                )
                disclaimer = auto_fill_source_disclaimer(sid, doc_kind="doverennost")
        except Exception:
            logging.warning(
                "Автозаполнение бланка %s для %s / %s не удалось",
                key,
                sid,
                inn,
                exc_info=True,
            )
            filled_path, form_data, filled_flags, disclaimer = None, None, None, None

        if filled_path and form_data and disclaimer:
            mems = get_org_memberships(reestr_database.get(inn))
            if sid in mems:
                for field in (
                    "reg_number",
                    "location",
                    "director",
                    "ogrn",
                    "insurance_company",
                    "insurance_sum",
                ):
                    if form_data.get(field):
                        mems[sid][field] = form_data[field]
            path = filled_path
            bits = [f"ИНН {form_data.get('inn')}"]
            if form_data.get("reg_number"):
                bits.append(f"рег. № {form_data['reg_number']}")
            send_caption = (
                f"{caption}\n\n{disclaimer}\n"
                f"<i>{' · '.join(bits)}</i>"
            )
            if key == "info_list":
                core_ok = bool(
                    filled_flags
                    and (filled_flags.get("reg_number") or filled_flags.get("inn_table"))
                )
            elif key == "zayavlenie_proverka":
                core_ok = bool(
                    filled_flags
                    and (
                        filled_flags.get("org_block")
                        or filled_flags.get("responsible_org")
                    )
                )
            else:
                core_ok = bool(
                    filled_flags
                    and (filled_flags.get("org_name") or filled_flags.get("director"))
                )
            if filled_flags and not core_ok:
                send_caption += (
                    "\n<i>Не все поля удалось вставить автоматически — "
                    "проверьте шаблон вручную.</i>"
                )
        else:
            send_caption = (
                f"{caption}\n\n"
                "⚠️ <i>Автозаполнение не удалось (нет данных в реестре или ошибка шаблона). "
                "Отправлен пустой бланк.</i>"
            )

    if not path:
        bot.send_message(
            chat_id,
            f"❌ Файл не найден в <code>blanki/{sid}/</code>.\n"
            "На сервере выполните: <code>py sync_blanki_from_sites.py</code>",
            parse_mode="HTML",
        )
        return True
    send_blanki_file(
        chat_id,
        path,
        send_caption,
        "❌ Не удалось отправить файл. Проверьте папку blanki на диске.",
    )
    return True


def get_sro_context_picker_keyboard(
    sro_ids: list[str],
    *,
    show_back_to_direction: bool = False,
):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for sro_id in sro_ids:
        if get_sro_profile(sro_id):
            markup.add(types.KeyboardButton(context_button_label(sro_id)))
    if show_back_to_direction:
        markup.add(types.KeyboardButton(BACK_TO_DIRECTION_BUTTON))
    markup.add(types.KeyboardButton(RESTART_ORG_BUTTON))
    markup.add(types.KeyboardButton("⬅️ Назад в меню"))
    return markup


def send_ai_reply(chat_id: int, question: str) -> None:
    try:
        bot.send_chat_action(chat_id, "typing")
    except Exception:
        pass

    cancel_await_expected(chat_id)
    ai_result = get_ai_response(question, GROQ_API_KEY, chat_id=chat_id)
    answer = ai_result.get("text") or ""
    remember_ai_reply(
        chat_id,
        question=question,
        answer_text=answer,
        route=local_ai_route_kind(question, chat_id=chat_id),
        sro_id=get_user_sro_id(chat_id),
    )
    markup = types.InlineKeyboardMarkup()
    if ai_result.get("doc_fallback"):
        markup.row(
            types.InlineKeyboardButton(
                "✅ Да, короткий ответ", callback_data=DOC_FALLBACK_YES
            ),
            types.InlineKeyboardButton("✖️ Нет", callback_data=DOC_FALLBACK_NO),
        )
    else:
        clear_doc_fallback_pending(chat_id)
        markup.add(
            types.InlineKeyboardButton("👎 Ответ не помог", callback_data=FB_CALLBACK)
        )
    bot.send_message(chat_id, answer, parse_mode="HTML", reply_markup=markup)


def prompt_feedback_expected(chat_id: int) -> None:
    if not begin_await_expected(chat_id):
        bot.send_message(
            chat_id,
            "Пока нет ответа ИИ для оценки. Задайте вопрос через «💬 ИИ-помощник».",
            parse_mode="HTML",
        )
        return
    bot.send_message(
        chat_id,
        "🙏 Подскажите, пожалуйста, <b>какой ответ вы ожидали</b> — "
        "одной фразой.\n\n"
        "Если не хотите уточнять — отправьте <code>/skip</code>.",
        parse_mode="HTML",
    )


def finish_feedback(chat_id: int, expected: str | None) -> None:
    if append_feedback(chat_id, expected):
        bot.send_message(
            chat_id,
            "✅ Спасибо! Мы записали замечание — это поможет сделать ответы полезнее.",
            parse_mode="HTML",
        )
    else:
        bot.send_message(
            chat_id,
            "Нечего сохранить — сначала получите ответ от ИИ.",
            parse_mode="HTML",
        )


def _is_reply_menu_button(user_text: str) -> bool:
    """Текст reply-кнопки меню — не запрос НРС/ИИ."""
    if user_text in (
        BACK_TO_MENU_BUTTON,
        SEARCH_ORG_BUTTON,
        NRS_LINK_BUTTON,
        DOC_QA_BUTTON,
        DOC_QA_ASK_BUTTON,
        DOC_QA_BACK_BUTTON,
        AI_BUTTON,
        FAQ_AI_BUTTON,
        "❓ Полезная информация",
        "❓ Назад в Полезное",
        BTN_FAQ_ASSOC_HUB,
        BTN_FAQ_SITE_QA,
        BTN_FAQ_SITE_BACK,
        SKIP_ONBOARDING_BUTTON,
        BACK_TO_SRO_PICK_BUTTON,
        BACK_TO_DIRECTION_BUTTON,
    ):
        return True
    return is_restart_org_button(user_text) or is_back_to_sro_pick_button(user_text)


def try_nrs_text_reply(chat_id: int, user_text: str) -> bool:
    """НРС: режим кнопки или автоматически по полному ФИО (не справочник)."""
    if _is_reply_menu_button(user_text):
        return False
    if not can_use_nrs_link_pilot(chat_id, get_user_sro_id(chat_id)):
        return False
    if is_nrs_link_mode(chat_id) or looks_like_nrs_person_query(user_text):
        # После ответа остаёмся в НРС: только «Назад в меню».
        # Раньше при авто-ФИО ставилось главное меню — легко задеть
        # «❓ Полезная информация» и получить экран FAQ «сам».
        exit_ai_mode(chat_id)
        exit_faq_mode(chat_id)
        exit_search_mode(chat_id)
        exit_doc_ask_mode(chat_id)
        enter_nrs_link_mode(chat_id)
        finish_button_reply(
            chat_id,
            format_nrs_link_reply(user_text, chat_id=chat_id),
            reply_markup=get_nrs_link_keyboard(),
            disable_web_page_preview=True,
        )
        return True
    return False


SRO_SITE = "https://www.srogen.ru"

BTN_FAQ_ASSOC_HUB = "🏢 Ассоциация и партнёры"
BTN_FAQ_SITE_QA = "📚 Вопрос-ответ (сайт)"
BTN_FAQ_SITE_BACK = "⬅️ Назад к разделам сайта"

# marker в тексте кнопки -> (url, подпись кнопки)
# Проверено по srogen.ru: все URL отдают 200
FAQ_SITE_LINKS = (
    ("Проверяемые документы", f"{SRO_SITE}/kontrol_sro/kontrolniy_komitet/perechen_documentov/", "🌐 Перечень на сайте СРО"),
    ("Перечень документов", f"{SRO_SITE}/vstuplenie_v_sro/", "🌐 Документы для вступления на сайте"),
    ("Требования к специалистам", f"{SRO_SITE}/vstuplenie_v_sro/vnesenie-v-reestr/", "🌐 Требования и НРС на сайте"),
    ("Сроки рассмотрения", f"{SRO_SITE}/vstuplenie_v_sro/", "🌐 Сроки вступления на сайте"),
    ("Сроки вступления", f"{SRO_SITE}/vstuplenie_v_sro/", "🌐 Сроки вступления на сайте"),
    ("Как вступить в СРО", f"{SRO_SITE}/vstuplenie_v_sro/", "🌐 Вступление на сайте СРО"),
    ("Размеры взносов", f"{SRO_SITE}/vstuplenie_v_sro/zayavka/", "🌐 Таблица взносов на сайте"),
    ("Подготовка к НОК", f"{SRO_SITE}/vstuplenie_v_sro/obuchenie/", "🌐 Подготовка к НОК на сайте"),
    ("Правила сдачи НОК", f"{SRO_SITE}/vstuplenie_v_sro/nok/", "🌐 НОК на сайте СРО"),
    ("Получение выписки", f"{SRO_SITE}/chlenam_sro/poluchenie_vypiski/", "🌐 Выписка на сайте СРО"),
    ("Личный кабинет", f"{SRO_SITE}/chlenam_sro/lichniy_kabinet/", "🌐 Личный кабинет на сайте СРО"),
    ("Расписание проверок", f"{SRO_SITE}/kontrol_sro/ob_organizacii/", "🌐 Организация контроля на сайте"),
    ("Изменения в Реестр", f"{SRO_SITE}/chlenam_sro/dlja_pereoformlenija/", "🌐 Изменения в реестре на сайте"),
    ("устранение нарушений", f"{SRO_SITE}/kontrol_sro/ustranenie_narusheniy/", "🌐 Устранение нарушений на сайте"),
    ("База законов", f"{SRO_SITE}/zakonodatelstvo/", "🌐 Законы на сайте СРО"),
    ("Документы в НРС", f"{SRO_SITE}/vstuplenie_v_sro/vnesenie-v-reestr/", "🌐 Документы НРС на сайте"),
    ("Кураторы НРС", f"{SRO_SITE}/vstuplenie_v_sro/vnesenie-v-reestr/", "🌐 НРС на сайте СРО"),
    ("Филиалы СРО", f"{SRO_SITE}/kontakty/predstavitelstva/", "🌐 Филиалы и представители на сайте"),
    ("Партнеры и НО", f"{SRO_SITE}/kontakty/partnery/", "🌐 Все партнёры на сайте СРО"),
    ("Благотворительность", f"{SRO_SITE}/sro/charity/", "🌐 Благотворительность на сайте"),
    ("Об Ассоциации", f"{SRO_SITE}/sro/o_partnerstve/", "🌐 Об Ассоциации на сайте"),
    ("Жалобы и предложения", f"{SRO_SITE}/kontakty/zhaloby_i_predlozheniya/", "🌐 Форма на сайте СРО"),
    ("Возврат взноса", f"{SRO_SITE}/voprosy/", "🌐 Вопрос-ответ на сайте СРО"),
    ("Строительство для себя", f"{SRO_SITE}/voprosy/", "🌐 Вопрос-ответ на сайте СРО"),
    ("КК (Контрольный комитет)", f"{SRO_SITE}/kontrol_sro/ob_organizacii/", "🌐 Контроль СРО на сайте"),
    ("АДК (Дисциплинарная комиссия)", f"{SRO_SITE}/kontrol_sro/ustranenie_narusheniy/", "🌐 Устранение нарушений на сайте"),
)


def faq_site_link_for(user_text: str, chat_id: int | None = None):
    lowered = user_text.lower()
    for marker, url, label in FAQ_SITE_LINKS:
        if marker.lower() in lowered:
            if chat_id is not None:
                profile = get_user_profile(chat_id)
                sro_id = (profile or {}).get("id") or get_user_sro_id(chat_id) or "OGPS"
                # «Об Ассоциации» — канонический URL по СРО
                if marker.lower() == "об ассоциации":
                    return about_url_for_sro(sro_id), label
                # Вступление / сроки / перечень — не путь ОГПС /vstuplenie_v_sro/
                if marker.lower() in JOIN_FAQ_MARKERS:
                    return join_url_for_sro(sro_id), label
                # Личный кабинет — только если страница есть на сайте СРО
                if marker.lower() == "личный кабинет" and not sro_has_lichniy_kabinet(sro_id):
                    return None, None
                site = (profile or {}).get("site") or site_base_for_sro(sro_id)
                if site:
                    from urllib.parse import urljoin, urlparse

                    path = rewrite_srogen_path_for_sro(sro_id, urlparse(url).path or "/")
                    url = urljoin(site.rstrip("/") + "/", path.lstrip("/"))
            return url, label
    return None, None


def site_link_markup(url: str, button_text: str):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(text=button_text, url=url))
    return markup


def fees_reply_markup(chat_id: int, sro_id: str):
    """Кнопки: скачать Положение (по желанию) + ссылка на сайт."""
    markup = types.InlineKeyboardMarkup()
    pol_path = fees_doc_path(sro_id)
    if pol_path and os.path.isfile(pol_path):
        markup.add(
            types.InlineKeyboardButton(
                "📥 Скачать Положение о членстве",
                callback_data=f"fees_doc:{sro_id}",
            )
        )
    url, label = faq_site_link_for("Размеры взносов", chat_id=chat_id)
    if url:
        markup.add(types.InlineKeyboardButton(text=label, url=url))
    return markup if markup.keyboard else None


def reply_faq_text(chat_id, text, user_text, *, add_footer=True):
    url, label = faq_site_link_for(user_text, chat_id=chat_id)
    markup = site_link_markup(url, label) if url else None
    if markup and add_footer:
        low = text.lower()
        # Не смотрим на любой «👇» в тексте — он часто про другое.
        # Добавляем дисклеймер, если его ещё нет.
        if "ориентир" not in low and "не консультация" not in low:
            text += FAQ_LINK_FOOTER
    finish_button_reply(chat_id, text, reply_markup=markup)

# --- КНОПОЧНЫЕ КЛАВИАТУРЫ ---

def _add_faq_ai_row(markup):
    markup.add(types.KeyboardButton(FAQ_AI_BUTTON))
    return markup


def get_faq_ai_inline():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💬 Спросить ИИ-помощника", callback_data="faq:ask_ai"))
    return markup


def start_faq_ai_chat(chat_id):
    exit_search_mode(chat_id)
    enter_ai_mode(chat_id)
    bot.send_message(chat_id, FAQ_AI_HINT + ai_context_banner(chat_id), parse_mode="HTML")


def send_faq_not_found(chat_id):
    bot.send_message(
        chat_id,
        FAQ_NOT_FOUND_TEXT,
        parse_mode="HTML",
        reply_markup=get_faq_ai_inline(),
    )

def setup_bot_commands():
    # Telegram: описание профиля — не длиннее 512 символов (иначе BOT_DESC_INVALID)
    bot_public_description = (
        "🕐 24/7 — помощь в любое время.\n\n"
        "Для членов 15 партнёрских СРО (ОГПС, ОГПП, ОСО, ОСОТ, ОГПО, СПРОФ…): "
        "реестр, бланки, НОК, ИИ.\n\n"
        "Ориентир по сайтам СРО · не консультация. Старт или Меню."
    )
    bot_short_description = (
        "15 СРО: реестр и бланки. Ориентир + ссылка. 24/7."
    )
    if len(bot_public_description) > 512:
        logging.warning("Описание бота %s символов > 512, обрезка", len(bot_public_description))
        bot_public_description = bot_public_description[:509] + "…"
    if len(bot_short_description) > 120:
        bot_short_description = bot_short_description[:117] + "…"
    try:
        bot.set_my_description(bot_public_description)
        bot.set_my_short_description(bot_short_description)
    except Exception as exc:
        logging.warning("Не удалось обновить описание бота: %s", exc)
        print(f"⚠️ Описание в профиле не обновлено: {exc}", flush=True)
    try:
        bot.set_my_commands(
            [
                types.BotCommand("start", "Главное меню"),
                types.BotCommand("help", "Справка по боту"),
                types.BotCommand("search", "Поиск организации по ИНН"),
                types.BotCommand("info", "FAQ и бланки документов"),
                types.BotCommand("controller", "Меню контролёра СРО"),
                types.BotCommand("users", "Список пользователей бота"),
                types.BotCommand(
                    "notify_update",
                    "Админ: превью/рассылка обновления",
                ),
            ]
        )
    except Exception as exc:
        logging.warning("Не удалось обновить команды Menu: %s", exc)
        print(f"⚠️ Команды Menu не обновлены (бот продолжит работу): {exc}", flush=True)


_NAV_ALIASES = {
    "start": "welcome",
    "старт": "welcome",
    "/start": "welcome",
    "menu": "menu",
    "меню": "menu",
    "/menu": "menu",
    "help": "help",
    "помощь": "help",
    "справка": "help",
    "/help": "help",
    "info": "info",
    "/info": "info",
    "controller": "controller",
    "контролер": "controller",
    "контролёр": "controller",
    "/controller": "controller",
}


def resolve_navigation_command(text: str) -> str | None:
    normalized = text.strip().lower().replace("ё", "е")
    return _NAV_ALIASES.get(normalized)


# Телефонный справочник отключён (конфликтовал с НРС и поиском).

SEARCH_ORG_BUTTON = "🔍 Поиск организации"
BACK_TO_MENU_BUTTON = "⬅️ Назад в меню"


def get_controller_keyboard(chat_id: int | None = None):
    """Меню контролёров: поиск и НРС — первыми, без кнопок вступающих."""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn_search = types.KeyboardButton(SEARCH_ORG_BUTTON)
    btn_nrs = types.KeyboardButton(NRS_LINK_BUTTON)
    btn_info = types.KeyboardButton("❓ Полезная информация")
    btn_ai = types.KeyboardButton(AI_BUTTON)
    keyboard.add(btn_search, btn_nrs)
    keyboard.add(btn_info, btn_ai)
    keyboard.add(types.KeyboardButton(DOC_QA_BUTTON))
    if chat_id is not None and get_user_sro_id(chat_id):
        keyboard.add(types.KeyboardButton(RESTART_ORG_BUTTON))
    return keyboard


def get_main_keyboard(chat_id: int | None = None):
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn_search = types.KeyboardButton(SEARCH_ORG_BUTTON)
    btn_nrs = types.KeyboardButton(NRS_LINK_BUTTON)
    btn_info = types.KeyboardButton("❓ Полезная информация")
    btn_ai = types.KeyboardButton(AI_BUTTON)
    show_nrs = chat_id is None or can_use_nrs_link_pilot(chat_id, get_user_sro_id(chat_id))
    if show_nrs:
        keyboard.add(btn_search, btn_nrs)
    else:
        keyboard.add(btn_search)
    keyboard.add(btn_info, btn_ai)
    if chat_id is not None:
        can_repick_org = bool(cached_pickable_sro_ids(chat_id)) or (
            bool(get_joiner_activity(chat_id)) and not is_awaiting_joiner_activity(chat_id)
        )
        if can_repick_org:
            keyboard.add(types.KeyboardButton(BACK_TO_SRO_PICK_BUTTON))
        if is_joiner_flow(chat_id):
            keyboard.add(types.KeyboardButton(BACK_TO_DIRECTION_BUTTON))
        if get_user_sro_id(chat_id) or can_repick_org or is_joiner_flow(chat_id):
            keyboard.add(types.KeyboardButton(RESTART_ORG_BUTTON))
        keyboard.add(types.KeyboardButton(DOC_QA_BUTTON))
    return keyboard


def controller_menu_text() -> str:
    return (
        f"👋 <b>Меню контролёра СРО</b>\n\n"
        f"🔍 <b>{SEARCH_ORG_BUTTON}</b> — ИНН или название по всем 15 СРО\n"
        f"   └ после поиска: реестр СРО или <b>полная информация</b> (Checko)\n"
        f"👤 <b>{NRS_LINK_BUTTON}</b> — ФИО или номер в реестрах НОСТРОЙ / НОПРИЗ\n"
        f"❓ <b>Полезная информация</b> — бланки, документы для проверки\n"
        f"💬 <b>{AI_BUTTON}</b> — ответы с учётом выбранного СРО (если нужен контекст бланков)\n\n"
        f"<i>Контекст СРО для бланков — по ИНН или «{RESTART_ORG_BUTTON}».</i>\n"
        f"<i>Обычное меню члена СРО — /start (без Checko).</i>\n\n"
        f"{OFFICIAL_SOURCE_DISCLAIMER}"
    )


def open_controller_menu(chat_id: int) -> None:
    exit_ai_mode(chat_id)
    exit_faq_mode(chat_id)
    exit_search_mode(chat_id)
    exit_doc_ask_mode(chat_id)
    exit_nrs_link_mode(chat_id)
    clear_await_inn(chat_id)
    clear_onboarding_flags(chat_id)
    enter_controller_work_mode(chat_id)
    finish_button_reply(
        chat_id,
        controller_menu_text(),
        reply_markup=get_controller_keyboard(chat_id),
    )


def get_nrs_link_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton(BACK_TO_MENU_BUTTON))
    return keyboard


def get_doc_qa_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton(DOC_QA_ASK_BUTTON))
    keyboard.add(types.KeyboardButton(DOC_QA_BACK_BUTTON))
    return keyboard


def get_onboarding_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton(SEARCH_ORG_BUTTON))
    keyboard.add(types.KeyboardButton(SKIP_ONBOARDING_BUTTON))
    return keyboard


def get_joiner_activity_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for label, _sro_id in JOINER_ACTIVITY_CHOICES:
        keyboard.add(types.KeyboardButton(label))
    keyboard.add(types.KeyboardButton(RESTART_ORG_BUTTON))
    return keyboard


def _context_ready_text(chat_id: int) -> str:
    prof = get_user_profile(chat_id)
    if not prof:
        return (
            "✅ Можно пользоваться меню.\n\n"
            "Чтобы бланки и план проверок были <b>вашего</b> СРО — "
            "введите ИНН через «🔍 Поиск организации»."
        )
    act = ACTIVITY_LABEL.get(prof["activity"], "")
    return (
        f"✅ Контекст: <b>{prof['short_title']}</b> ({act})\n\n"
        "Вопросы ИИ и план проверок — <b>по вашему СРО</b>.\n\n"
        "📋 Нужны бланки для проверки?\n"
        "«❓ Полезная информация» → «📋 Проверяемые документы»."
    )

def _open_org_search(chat_id: int, *, intro: str | None = None) -> None:
    exit_ai_mode(chat_id)
    exit_faq_mode(chat_id)
    clear_await_inn(chat_id)
    clear_joiner_activity_await(chat_id)
    enter_search_mode(chat_id)
    text = intro or (
        "🏢 <b>Универсальный поиск</b>\n\n"
        "Введите <b>ИНН</b> (только цифры) или часть названия организации "
        "по <b>всем 15 СРО</b> экосистемы (кавычки можно не ставить)."
    )
    kb = (
        get_controller_keyboard(chat_id)
        if is_controller_work_mode(chat_id)
        else get_main_keyboard(chat_id)
    )
    kb.add(types.KeyboardButton(BACK_TO_MENU_BUTTON))
    finish_button_reply(
        chat_id,
        text,
        reply_markup=kb,
    )


def get_info_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn_faq = types.KeyboardButton("❓ Часто задаваемые вопросы")
    btn_check_list = types.KeyboardButton("📋 Проверяемые документы")
    btn_back = types.KeyboardButton("⬅️ Назад в меню")
    keyboard.add(btn_faq)
    keyboard.add(btn_check_list)
    _add_faq_ai_row(keyboard)
    keyboard.add(btn_back)
    return keyboard

# 1. ГЛАВНЫЙ КОРЕНЬ FAQ
def get_faq_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn_folder1 = types.KeyboardButton("🏗 Для вступающих")
    btn_folder2 = types.KeyboardButton("👔 Действующим членам")
    btn_folder3 = types.KeyboardButton("🎓 Специалисты и НОК")
    btn_fees = types.KeyboardButton("💰 Размеры взносов (КФ)")
    btn_assoc_hub = types.KeyboardButton(BTN_FAQ_ASSOC_HUB)
    btn_back = types.KeyboardButton("❓ Назад в Полезное")

    markup.add(btn_folder1)
    markup.add(btn_folder2, btn_folder3)
    markup.add(btn_fees)
    markup.add(btn_assoc_hub)
    _add_faq_ai_row(markup)
    markup.add(btn_back)
    return markup


def get_assoc_hub_keyboard():
    """Подменю: об Ассоциации, филиалы, партнёры, жалобы, благотворительность."""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn_about = types.KeyboardButton("🏢 Об Ассоциации СРО")
    btn_trusted = types.KeyboardButton(TRUSTED_BUTTON)
    btn_regions = types.KeyboardButton("🌍 Филиалы СРО")
    btn_partners = types.KeyboardButton("🤝 Партнеры и НО")
    btn_feedback = types.KeyboardButton("📩 Жалобы и предложения")
    btn_charity = types.KeyboardButton("❤️ Благотворительность")
    btn_back_faq = types.KeyboardButton("⬅️ Назад в FAQ")

    markup.add(btn_about)
    markup.add(btn_trusted)
    markup.add(btn_regions, btn_partners)
    markup.add(btn_feedback, btn_charity)
    _add_faq_ai_row(markup)
    markup.add(btn_back_faq)
    return markup

# ПОДМЕНЮ: ДЛЯ ВСТУПАЮЩИХ (РАСШИРЕННОЕ)
def get_vstupayuschim_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    
    btn_how = types.KeyboardButton("📝 Как вступить в СРО?")
    
    # НАШИ НОВЫЕ КНОПКИ:
    btn_docs = types.KeyboardButton("📄 Перечень документов для вступления")
    btn_specs = types.KeyboardButton("🏢 Требования к специалистам")
    btn_terms = types.KeyboardButton("⏱ Сроки вступления")
    btn_own_needs = types.KeyboardButton("🏠 Строительство для себя")
    
    btn_back_faq = types.KeyboardButton("⬅️ Назад в FAQ")
    
    # Красивая раскладка (взносы — в корне FAQ; длинные подписи — каждая в свой ряд)
    markup.add(btn_how)
    markup.add(btn_docs)
    markup.add(btn_specs)
    markup.add(btn_terms)
    markup.add(btn_own_needs)
    _add_faq_ai_row(markup)
    markup.add(btn_back_faq)
    return markup


# 2. ПАПКА: ДЕЙСТВУЮЩИМ ЧЛЕНАМ
def get_chlenam_keyboard(chat_id: int | None = None):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)

    btn7 = types.KeyboardButton("📄 Получение выписки")
    btn_changes = types.KeyboardButton("🔄 Изменения в Реестр")
    btn3 = types.KeyboardButton("🔍 Расписание проверок")
    btn_violations = types.KeyboardButton("🛠 Устранение нарушений")
    btn_laws = types.KeyboardButton("⚖️ База законов СРО")

    # ВОЗВРАЩАЕМ ПРОПАВШИЕ КНОПКИ СЮДА:
    btn_refund = types.KeyboardButton("💰 Возврат взноса")

    btn_back_faq = types.KeyboardButton("⬅️ Назад в FAQ")

    sro_id = None
    if chat_id is not None:
        sro_id = get_user_sro_id(chat_id) or (get_user_profile(chat_id) or {}).get("id")
    if sro_has_lichniy_kabinet(sro_id or "OGPS"):
        markup.add(types.KeyboardButton("🔐 Личный кабинет"))
    markup.add(btn7, btn_changes)
    markup.add(btn3, btn_violations)
    markup.add(btn_laws)
    markup.add(btn_refund)
    _add_faq_ai_row(markup)
    markup.add(btn_back_faq)

    return markup


# 4. ПОДМЕНЮ: СПЕЦИАЛИСТЫ И НОК
def get_nok_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn5 = types.KeyboardButton("📋 Документы в НРС")
    btn6 = types.KeyboardButton("👤 Кураторы НРС")
    btn9 = types.KeyboardButton("🎓 Правила сдачи НОК")
    btn4 = types.KeyboardButton("🎓 Подготовка к НОК")
    btn_back_faq = types.KeyboardButton("⬅️ Назад в FAQ")
    
    markup.add(btn5, btn6)
    markup.add(btn9, btn4)
    _add_faq_ai_row(markup)
    markup.add(btn_back_faq)
    return markup


def _faq_site_profile(chat_id: int) -> dict:
    """Контекст СРО для раздела «Вопрос-ответ (сайт)»; без выбора — ОГПС."""
    return get_user_profile(chat_id) or get_sro_profile("OGPS") or {
        "id": "OGPS",
        "name": "ОГПС",
        "short_title": "Ассоциация «ГЕН» (ОГПС)",
        "activity": "stroy",
        "site": SRO_SITE,
        "voprosy_url": f"{SRO_SITE}/voprosy/",
    }


def get_voprosy_site_sections_keyboard(chat_id: int | None = None):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    profile = _faq_site_profile(chat_id) if chat_id is not None else None
    activity = (profile or {}).get("activity")
    for section in get_voprosy_site_sections():
        topics = list_voprosy_site_topics(section["id"], activity=activity)
        if activity and not topics:
            continue
        markup.add(types.KeyboardButton(section["button"]))
    _add_faq_ai_row(markup)
    markup.add(types.KeyboardButton("⬅️ Назад в FAQ"))
    return markup


def get_voprosy_site_topics_keyboard(section_id: str, chat_id: int | None = None):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    profile = _faq_site_profile(chat_id) if chat_id is not None else None
    activity = (profile or {}).get("activity")
    for _topic_id, button in list_voprosy_site_topics(section_id, activity=activity):
        markup.add(types.KeyboardButton(button))
    _add_faq_ai_row(markup)
    markup.add(types.KeyboardButton(BTN_FAQ_SITE_BACK))
    markup.add(types.KeyboardButton("⬅️ Назад в FAQ"))
    return markup

def get_download_docs_keyboard(chat_id: int | None = None):
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn1 = types.KeyboardButton("📄 1. Информационный лист")
    btn2 = types.KeyboardButton("📄 2. Заявление о внесении изменений")
    btn3 = types.KeyboardButton("📄 3. Заявление на проверку")
    btn4 = types.KeyboardButton("📄 4. Форма доверенности")
    btn5 = types.KeyboardButton("📄 5. Сведения о специалистах")
    btn6 = types.KeyboardButton("📄 6. Положения о контроле")
    btn7 = types.KeyboardButton("📄 7. Уведомление ОДО")
    btn_back = types.KeyboardButton("❓ Назад в Полезное")

    keyboard.add(btn1)
    keyboard.add(btn2, btn3)
    keyboard.add(btn4, btn5)
    keyboard.add(btn6, btn7)
    if chat_id is not None and cached_pickable_sro_ids(chat_id):
        keyboard.add(types.KeyboardButton(BACK_TO_SRO_PICK_BUTTON))
    keyboard.add(btn_back)
    return keyboard


# --- ЛОГИКА ОБРАБОТКИ СООБЩЕНИЙ ---
@bot.message_handler(commands=['start'])
@log_errors  # Наш защитный щит от ошибок тоже вешаем сюда!
def send_welcome(message):
    touch_user(message, event="start")
    exit_ai_mode(message.chat.id)
    exit_faq_mode(message.chat.id)
    exit_search_mode(message.chat.id)
    exit_doc_ask_mode(message.chat.id)
    exit_nrs_link_mode(message.chat.id)
    exit_controller_work_mode(message.chat.id)
    cancel_await_expected(message.chat.id)
    begin_await_inn(message.chat.id)

    controller_hint = ""
    if is_controller(message.chat.id):
        controller_hint = "<i>Контролёрам: служебное меню — /controller</i>\n\n"

    welcome_text = f"""👋 <b>Добро пожаловать в чат-бот реестра и сервисов СРО!</b>

🕐 Работает <b>24/7</b> для членов и кураторов <b>15 партнёрских СРО</b>.

📌 <b>Уже член СРО?</b> Введите <b>ИНН</b> организации:
1️⃣ Найдём карточку в реестре
2️⃣ Если СРО несколько — выберите кнопкой
3️⃣ Бланки, план проверок и ИИ — <b>по вашему СРО</b>

🔍 Или сразу нажмите <b>{SEARCH_ORG_BUTTON}</b> — поиск по ИНН/названию без выбора СРО.

🆕 <b>Только вступаете?</b> Чтобы пользоваться меню и бланками до приёма в СРО,
нажмите <b>Пропустить</b> → направление → <b>конкретное СРО</b>.
После приёма — снова /start и введите ИНН.

{controller_hint}{OFFICIAL_SOURCE_DISCLAIMER}"""

    bot.send_message(
        message.chat.id,
        welcome_text,
        parse_mode="HTML",
        reply_markup=get_onboarding_keyboard(),
    )


@bot.message_handler(commands=['controller'])
@log_errors
def send_controller_command(message):
    touch_user(message, event="controller")
    if not is_controller(message.chat.id):
        bot.send_message(
            message.chat.id,
            "⛔ Команда <code>/controller</code> — только для сотрудников контроля СРО.\n\n"
            "Обычное меню: /start",
            parse_mode="HTML",
            reply_markup=get_main_keyboard(message.chat.id),
        )
        return
    open_controller_menu(message.chat.id)


def restart_org_onboarding(chat_id: int) -> None:
    """Сброс контекста СРО → снова ввод ИНН или «Пропустить» без ИНН."""
    exit_ai_mode(chat_id)
    exit_faq_mode(chat_id)
    exit_search_mode(chat_id)
    exit_controller_work_mode(chat_id)
    cancel_await_expected(chat_id)
    clear_user_sro(chat_id)
    begin_await_inn(chat_id)
    finish_button_reply(
        chat_id,
        "🔄 <b>Смена организации</b>\n\n"
        "Введите <b>ИНН</b> другой организации — или нажмите кнопку "
        f"«{SKIP_ONBOARDING_BUTTON}», чтобы работать с бланками без ИНН "
        "(сначала направление, потом СРО).\n\n"
        "<i>Можно также /start — то же самое.</i>",
        reply_markup=get_onboarding_keyboard(),
    )


@bot.message_handler(commands=['users'])
@log_errors
def send_users_stats(message):
    if not is_bot_admin(message.chat.id):
        bot.send_message(
            message.chat.id,
            "⛔ Команда только для администратора бота.\n"
            "Список пользователей лежит в файле <code>bot_users.json</code> "
            "в папке GOLD на компьютере, где запущен бот.",
            parse_mode="HTML",
        )
        return
    bot.send_message(
        message.chat.id,
        format_users_report(limit=40),
        parse_mode="HTML",
    )


# Текст обновления 1.09 — рассылка только по явной команде админа с confirm.
UPDATE_NOTICE_VERSION = "1.09"
UPDATE_NOTICE_TEXT = (
    "🆕 <b>Обновление бота · версия 1.09</b>\n\n"
    "При поиске организации теперь можно получить <b>больше сведений</b>, "
    "чем есть в реестре СРО.\n\n"
    "После поиска (команда <code>/controller</code> → "
    f"«{SEARCH_ORG_BUTTON}») появится кнопка "
    "«🔎 Полная информация»:\n"
    "• где находится организация (адрес);\n"
    "• электронная почта — если в карточке СРО её нет;\n"
    "• номера телефонов.\n\n"
    "Как пользоваться: введите ИНН или название → "
    "выберите «Полная информация» → раздел «Контакты» "
    "(и другие блоки по необходимости).\n\n"
    "<i>Карточка реестра СРО по-прежнему доступна отдельно.</i>"
)


@bot.message_handler(commands=["notify_update"])
@log_errors
def send_update_notice_command(message):
    """Админ: без confirm — только превью; с confirm — рассылка контролёрам."""
    if not is_bot_admin(message.chat.id):
        bot.send_message(
            message.chat.id,
            "⛔ Команда только для администратора бота.",
        )
        return

    parts = (message.text or "").split()
    confirm = len(parts) > 1 and parts[1].strip().lower() in ("confirm", "да", "send")
    targets = controller_chat_ids()

    if not confirm:
        bot.send_message(
            message.chat.id,
            "📋 <b>Превью уведомления</b> (никому не отправлено)\n\n"
            f"Версия: <code>{UPDATE_NOTICE_VERSION}</code>\n"
            f"Получатели: <b>{len(targets)}</b> контролёр(ов) из "
            "<code>CONTROLLER_CHAT_IDS</code>\n\n"
            "——— текст ———\n"
            f"{UPDATE_NOTICE_TEXT}\n"
            "——— конец ———\n\n"
            "Чтобы отправить: <code>/notify_update confirm</code>",
            parse_mode="HTML",
        )
        return

    if not targets:
        bot.send_message(
            message.chat.id,
            "⚠️ Список контролёров пуст — отправлять некому.",
        )
        return

    ok = 0
    fail = 0
    for cid in targets:
        try:
            bot.send_message(cid, UPDATE_NOTICE_TEXT, parse_mode="HTML")
            ok += 1
        except Exception as exc:
            fail += 1
            print(f"⚠️ notify_update → {cid}: {exc}", flush=True)
    bot.send_message(
        message.chat.id,
        f"✅ Рассылка {UPDATE_NOTICE_VERSION}: доставлено <b>{ok}</b>, "
        f"ошибок <b>{fail}</b> (из {len(targets)}).",
        parse_mode="HTML",
    )


@bot.message_handler(commands=['help'])
@log_errors
def send_help(message):
    exit_ai_mode(message.chat.id)
    exit_faq_mode(message.chat.id)
    help_text = """ℹ️ <b>Справка по боту</b>

<b>Команды</b> (кнопка Menu слева от поля ввода):
/start — главное меню (ИНН или поиск)
/controller — меню контролёра (служебное)
/search — поиск организации
/info — FAQ и бланки
/help — эта справка

<b>Основные разделы на клавиатуре:</b>
🔍 Поиск организации — ИНН или название, план проверки и реестр
👤 Проверить в НРС — ФИО или номер в реестрах НОСТРОЙ / НОПРИЗ
❓ Полезная информация — выписка, НОК, изменения в реестре, FAQ
💬 ИИ-помощник — ответы с учётом вашего СРО и ссылки на официальные сайты
🔄 Другой ИНН / без ИНН — сбросить организацию и начать заново (как /start)

<i>Можно просто ввести ИНН или часть названия компании — бот найдёт организацию.</i>"""
    bot.send_message(
        message.chat.id,
        help_text,
        parse_mode="HTML",
        reply_markup=get_main_keyboard(message.chat.id),
    )


@bot.message_handler(commands=['search'])
@log_errors
def send_search_command(message):
    exit_ai_mode(message.chat.id)
    exit_faq_mode(message.chat.id)
    enter_search_mode(message.chat.id)
    bot.send_message(
        message.chat.id,
        "🏢 <b>Универсальный поиск</b>\n\nВведите ИНН (только цифры) или часть названия организации (кавычки можно не ставить):",
        parse_mode="HTML",
        reply_markup=get_main_keyboard(message.chat.id),
    )


@bot.message_handler(commands=['info'])
@log_errors
def send_info_command(message):
    exit_ai_mode(message.chat.id)
    enter_faq_mode(message.chat.id)
    bot.send_message(
        message.chat.id,
        "Здесь вы можете найти ответы на частые вопросы и скачать бланки:",
        reply_markup=get_info_keyboard(),
    )


@bot.message_handler(content_types=['text'])
@log_errors
def handle_text(message):
    touch_user(message, event="message")
    user_text = message.text.strip()

    if is_awaiting_expected(message.chat.id):
        if user_text.lower() in ("/skip", "skip", "пропустить"):
            finish_feedback(message.chat.id, None)
        else:
            finish_feedback(message.chat.id, user_text)
        return

    if is_feedback_phrase(user_text):
        prompt_feedback_expected(message.chat.id)
        return

    nav_action = resolve_navigation_command(user_text)
    if nav_action == "welcome":
        send_welcome(message)
        return
    if nav_action == "menu":
        exit_ai_mode(message.chat.id)
        exit_faq_mode(message.chat.id)
        exit_search_mode(message.chat.id)
        bot.send_message(
            message.chat.id,
            "📋 <b>Главное меню</b> — выберите раздел на клавиатуре ниже:",
            parse_mode="HTML",
            reply_markup=get_main_keyboard(message.chat.id),
        )
        return
    if nav_action == "help":
        send_help(message)
        return
    if nav_action == "info":
        send_info_command(message)
        return
    if nav_action == "controller":
        send_controller_command(message)
        return

    if user_text == BACK_TO_MENU_BUTTON:
        exit_ai_mode(message.chat.id)
        exit_faq_mode(message.chat.id)
        exit_search_mode(message.chat.id)
        exit_doc_ask_mode(message.chat.id)
        exit_nrs_link_mode(message.chat.id)
        clear_nav_mode_flags(message.chat.id)
        cancel_await_expected(message.chat.id)
        menu_kb = (
            get_controller_keyboard(message.chat.id)
            if is_controller_work_mode(message.chat.id)
            else get_main_keyboard(message.chat.id)
        )
        finish_button_reply(
            message.chat.id,
            "Вы вернулись в главное меню:",
            reply_markup=menu_kb,
        )
        return

    if try_nrs_text_reply(message.chat.id, user_text):
        return

    activity = parse_joiner_activity_button(user_text)
    if activity and is_awaiting_joiner_activity(message.chat.id):
        sro_ids = begin_joiner_sro_pick(message.chat.id, activity)
        finish_button_reply(
            message.chat.id,
            joiner_sro_pick_hint(activity),
            reply_markup=get_sro_context_picker_keyboard(
                sro_ids, show_back_to_direction=True
            ),
        )
        return

    picked_sro = parse_context_button(user_text)
    if picked_sro:
        prev = get_user_context(message.chat.id)
        inn = prev.get("inn") if prev else None
        set_user_sro(message.chat.id, picked_sro, inn=inn)
        clear_await_inn(message.chat.id)
        clear_joiner_activity_await(message.chat.id)
        consume_open_main_after_sro(message.chat.id)
        prof = get_sro_profile(picked_sro)
        act = ACTIVITY_LABEL.get(prof["activity"], "") if prof else ""
        title = prof["short_title"] if prof else picked_sro
        finish_button_reply(
            message.chat.id,
            f"✅ Выбрано: <b>{title}</b> ({act})\n\n{_context_ready_text(message.chat.id)}",
            reply_markup=get_main_keyboard(message.chat.id),
        )
        return

    if user_text == SKIP_ONBOARDING_BUTTON:
        begin_joiner_activity_pick(message.chat.id)
        finish_button_reply(
            message.chat.id,
            joiner_activity_hint(),
            reply_markup=get_joiner_activity_keyboard(),
        )
        return

    if user_text == SEARCH_ORG_BUTTON:
        _open_org_search(message.chat.id)
        return

    if is_restart_org_button(user_text):
        restart_org_onboarding(message.chat.id)
        return

    if user_text == BACK_TO_DIRECTION_BUTTON:
        begin_joiner_activity_pick(message.chat.id)
        finish_button_reply(
            message.chat.id,
            joiner_activity_hint(),
            reply_markup=get_joiner_activity_keyboard(),
        )
        return

    if is_awaiting_joiner_activity(message.chat.id):
        bot.send_message(
            message.chat.id,
            "📌 Выберите направление кнопкой ниже:\n"
            "🏗 Строители · 📐 Проектировщики · 🗺 Изыскания",
            reply_markup=get_joiner_activity_keyboard(),
        )
        return

    if is_awaiting_inn(message.chat.id):
        if looks_like_inn(user_text):
            clean_inn = normalize_inn(user_text)
            mark_open_main_after_sro(message.chat.id)
            if send_company_card(
                message.chat.id,
                clean_inn,
                reply_markup=get_main_keyboard(message.chat.id),
            ):
                clear_await_inn(message.chat.id)
                if not pending_sro_ids(message.chat.id):
                    consume_open_main_after_sro(message.chat.id)
                    finish_button_reply(
                        message.chat.id,
                        _context_ready_text(message.chat.id),
                        reply_markup=get_main_keyboard(message.chat.id),
                    )
                return
            bot.send_message(
                message.chat.id,
                "❌ Организация не найдена в реестре.\n\n"
                "• Проверьте ИНН\n"
                "• Если <b>только вступаете</b> — нажмите "
                f"«{SKIP_ONBOARDING_BUTTON}» и выберите направление "
                "(меню и бланки доступны до появления в реестре).",
                parse_mode="HTML",
                reply_markup=get_onboarding_keyboard(),
            )
            return
        if len(user_text.strip()) >= 2 and handle_org_name_search(message.chat.id, user_text, force=True):
            clear_await_inn(message.chat.id)
            pick_ids = pending_sro_ids(message.chat.id)
            if pick_ids and len(pick_ids) >= 2:
                mark_open_main_after_sro(message.chat.id)
                return
            enter_search_mode(message.chat.id)
            consume_open_main_after_sro(message.chat.id)
            finish_button_reply(
                message.chat.id,
                _context_ready_text(message.chat.id),
                reply_markup=get_main_keyboard(message.chat.id),
            )
            return
        bot.send_message(
            message.chat.id,
            "📌 Введите <b>ИНН</b> или название организации — "
            f"или нажмите <b>{SEARCH_ORG_BUTTON}</b> / "
            f"<b>{SKIP_ONBOARDING_BUTTON}</b>.",
            parse_mode="HTML",
            reply_markup=get_onboarding_keyboard(),
        )
        return

    if is_back_to_sro_pick_button(user_text):
        pick_ids = cached_pickable_sro_ids(message.chat.id)
        if not pick_ids and is_joiner_flow(message.chat.id):
            act = get_joiner_activity(message.chat.id)
            if act:
                pick_ids = begin_joiner_sro_pick(message.chat.id, act)
        if pick_ids:
            mark_open_main_after_sro(message.chat.id)
            restore_pending_sro_pick(message.chat.id, pick_ids)
            act = get_joiner_activity(message.chat.id)
            joiner = bool(act) or is_joiner_flow(message.chat.id)
            hint = joiner_sro_pick_hint(act) if joiner else multi_sro_picker_hint(pick_ids)
            finish_button_reply(
                message.chat.id,
                hint,
                reply_markup=get_sro_context_picker_keyboard(
                    pick_ids,
                    show_back_to_direction=joiner,
                ),
            )
        else:
            finish_button_reply(
                message.chat.id,
                "Сейчас нет списка организаций для выбора.\n"
                "Введите ИНН или нажмите «Пропустить» на /start.",
                reply_markup=get_main_keyboard(message.chat.id),
            )
        return
    
    if user_text == AI_BUTTON:
        exit_faq_mode(message.chat.id)
        exit_search_mode(message.chat.id)
        enter_ai_mode(message.chat.id)
        finish_button_reply(message.chat.id, AI_MODE_HINT + ai_context_banner(message.chat.id))
        return

    elif user_text == FAQ_AI_BUTTON:
        start_faq_ai_chat(message.chat.id)
        return

    if user_text == NRS_LINK_BUTTON:
        exit_ai_mode(message.chat.id)
        exit_faq_mode(message.chat.id)
        exit_search_mode(message.chat.id)
        exit_doc_ask_mode(message.chat.id)
        if not can_use_nrs_link_pilot(message.chat.id, get_user_sro_id(message.chat.id)):
            finish_button_reply(
                message.chat.id,
                "👤 Пилот НРС доступен только админу в контексте <b>ОГПС</b>.\n"
                "Выберите организацию ОГПС (ИНН) и откройте меню снова.",
                reply_markup=get_main_keyboard(message.chat.id),
            )
            return
        enter_nrs_link_mode(message.chat.id)
        finish_button_reply(
            message.chat.id,
            format_nrs_link_intro(),
            reply_markup=get_nrs_link_keyboard(),
        )
        return

    if user_text == DOC_QA_BUTTON:
        exit_ai_mode(message.chat.id)
        exit_faq_mode(message.chat.id)
        exit_search_mode(message.chat.id)
        enter_doc_ask_mode(message.chat.id)
        sro_id = get_user_sro_id(message.chat.id)
        finish_button_reply(
            message.chat.id,
            format_doc_qa_intro(sro_id),
            reply_markup=get_doc_qa_keyboard(),
        )
        return

    if user_text == DOC_QA_ASK_BUTTON:
        exit_ai_mode(message.chat.id)
        exit_faq_mode(message.chat.id)
        enter_doc_ask_mode(message.chat.id)
        sro_id = get_user_sro_id(message.chat.id)
        finish_button_reply(
            message.chat.id,
            format_doc_qa_hint(sro_id),
            reply_markup=get_doc_qa_keyboard(),
        )
        return

    if is_doc_ask_mode(message.chat.id):
        sro_id = get_user_sro_id(message.chat.id)
        if user_text in (DOC_QA_BUTTON, DOC_QA_ASK_BUTTON):
            finish_button_reply(
                message.chat.id,
                format_doc_qa_hint(sro_id),
                reply_markup=get_doc_qa_keyboard(),
            )
            return
        bot.send_message(message.chat.id, "⏳ Ищу в документах…")
        result = answer_from_document(user_text, sro_id=sro_id)
        bot.send_message(
            message.chat.id,
            result.get("text") or "⚠️ Пустой ответ.",
            parse_mode="HTML",
            reply_markup=get_doc_qa_keyboard(),
        )
        return

    if user_text == SEARCH_ORG_BUTTON:
        _open_org_search(message.chat.id)
        return

    if user_text == "❓ Полезная информация" or user_text == "❓ Назад в Полезное":
        exit_ai_mode(message.chat.id)
        enter_faq_mode(message.chat.id)
        finish_button_reply(
            message.chat.id,
            "Здесь вы можете найти ответы на частые вопросы и скачать бланки:",
            reply_markup=get_info_keyboard(),
        )
        return

    elif "Часто задаваемые вопросы" in user_text:
        enter_faq_mode(message.chat.id)
        finish_button_reply(
            message.chat.id,
            "Выберите интересующий вас раздел ниже:",
            reply_markup=get_faq_keyboard(),
        )
        return

    elif "Для вступающих" in user_text:
        enter_faq_mode(message.chat.id)
        finish_button_reply(
            message.chat.id,
            "📁 Раздел: <b>Для вступающих в СРО Ассоциации</b>\n\nВыберите интересующий вас пункт меню ниже:",
            reply_markup=get_vstupayuschim_keyboard(),
        )
        return

    elif "Действующим членам" in user_text:
        enter_faq_mode(message.chat.id)
        finish_button_reply(
            message.chat.id,
            "📁 Раздел: <b>Информация для действующих членов СРО</b>",
            reply_markup=get_chlenam_keyboard(message.chat.id),
        )
        return

    elif "Специалисты и НОК" in user_text:
        enter_faq_mode(message.chat.id)
        finish_button_reply(
            message.chat.id,
            "📁 Раздел: <b>Национальный реестр (НРС) и экзамены НОК</b>",
            reply_markup=get_nok_keyboard(),
        )
        return

    elif user_text == BTN_FAQ_SITE_QA:
        enter_faq_mode(message.chat.id)
        profile = _faq_site_profile(message.chat.id)
        sro_name = profile.get("short_title") or profile.get("name") or "вашего СРО"
        finish_button_reply(
            message.chat.id,
            "📚 <b>Вопрос-ответ (сайт)</b>\n\n"
            "Удобный раздел: выберите тему и вопрос — "
            "в чате получите <b>короткий ответ</b>, а полный текст "
            "с правовым обоснованием — <b>на официальном сайте</b> "
            "(кнопка под ответом).\n\n"
            f"Сейчас ответы и ссылки для: <b>{sro_name}</b>.\n"
            "<i>Другое СРО — введите ИНН и выберите его, затем откройте раздел снова.</i>\n\n"
            "Выберите тематический раздел ниже:",
            reply_markup=get_voprosy_site_sections_keyboard(message.chat.id),
        )
        return

    elif user_text == BTN_FAQ_SITE_BACK:
        profile = _faq_site_profile(message.chat.id)
        sro_name = profile.get("short_title") or profile.get("name") or "вашего СРО"
        finish_button_reply(
            message.chat.id,
            "📚 <b>Вопрос-ответ (сайт)</b>\n\n"
            "Выберите тему: <b>короткий ответ</b> в чате или "
            "<b>полный</b> — на сайте по кнопке под ответом.\n\n"
            f"<i>Контекст: {sro_name}</i>",
            reply_markup=get_voprosy_site_sections_keyboard(message.chat.id),
        )
        return

    elif resolve_voprosy_site_section_button(user_text):
        section_id = resolve_voprosy_site_section_button(user_text)
        section = get_voprosy_site_section(section_id)
        title = section["title"] if section else "Раздел сайта"
        profile = _faq_site_profile(message.chat.id)
        sro_name = profile.get("short_title") or profile.get("name") or "СРО"
        finish_button_reply(
            message.chat.id,
            f"📁 <b>{title}</b>\n\n"
            "Выберите вопрос: бот покажет короткий ответ и даст кнопку "
            f"на полный текст в разделе «Вопрос-ответ» на сайте <b>{sro_name}</b>.",
            reply_markup=get_voprosy_site_topics_keyboard(section_id, message.chat.id),
        )
        return

    elif resolve_voprosy_site_topic_button(user_text):
        topic_id = resolve_voprosy_site_topic_button(user_text)
        profile = _faq_site_profile(message.chat.id)
        sro_name = profile.get("short_title") or profile.get("name") or "СРО"
        site = (profile.get("site") or SRO_SITE).rstrip("/")
        voprosy_url = profile.get("voprosy_url") or f"{site}/voprosy/"

        if topic_id == "membership_terms":
            text = format_sroki_vstupleniya_text(profile.get("id"))
            text += f"\n\n<i>Контекст: {sro_name}</i>"
            markup = site_link_markup(
                join_url_for_sro(profile.get("id")),
                f"🌐 Сроки вступления на сайте ({profile.get('name') or 'СРО'})",
            )
            finish_button_reply(message.chat.id, text, reply_markup=markup)
            return

        item = get_voprosy_site_item(topic_id)
        if not item:
            finish_button_reply(
                message.chat.id,
                "❌ Не удалось найти этот вопрос в базе. Попробуйте соседнюю кнопку.",
                reply_markup=get_voprosy_site_sections_keyboard(message.chat.id),
            )
            return
        result = format_voprosy_faq_response(item["label"], item, profile=profile)
        markup = site_link_markup(
            voprosy_url,
            f"🌐 Полный ответ на сайте ({profile.get('name') or 'СРО'})",
        )
        finish_button_reply(
            message.chat.id,
            result["text"],
            reply_markup=markup,
        )
        return

    elif BTN_FAQ_ASSOC_HUB in user_text or user_text == "🏢 Ассоциация и партнеры":
        enter_faq_mode(message.chat.id)
        finish_button_reply(
            message.chat.id,
            "📁 <b>Ассоциация, партнёры, жалобы</b>\n\nВыберите раздел:",
            reply_markup=get_assoc_hub_keyboard(),
        )
        return

    elif user_text == "⬅️ Назад в FAQ":
        finish_button_reply(
            message.chat.id,
            "Вы вернулись в главное меню вопросов (FAQ):",
            reply_markup=get_faq_keyboard(),
        )
        return

    elif user_text == "💰 Возврат взноса":
        text = """💰 <b>Возврат взноса из компфонда</b>\n\n❌ <b>Нет, вернуть деньги нельзя.</b>\n\nСогласно Градостроительному кодексу РФ (ст. 55.7), если компания выбывает или исключается из СРО, уплаченные вступительные, членские взносы и взносы в компенсационный фонд <b>не возвращаются</b>."""
        reply_faq_text(message.chat.id, text, user_text)
        return

    elif user_text == "🏠 Строительство для себя":
        text = """🏠 <b>Строительство для собственных нужд</b>\n\n✅ <b>Как правило, членство в СРО не требуется.</b>\n\nОбязательное членство связано с выполнением работ <b>по договорам строительного подряда</b> — с застройщиком, техническим заказчиком и другими лицами, если сумма обязательств по договору превышает <code>10 000 000</code> руб., а также при участии в торгах.\n\nЕсли вы строите <b>на собственном объекте за свой счёт</b>, без такого договора с третьими лицами — вступать в СРО обычно не нужно.\n\n👇 Подробный разбор — в официальном разделе «Вопрос-ответ» на сайте Ассоциации."""
        reply_faq_text(message.chat.id, text, user_text)
        return
    
    elif user_text == "🎓 Подготовка к НОК":
        text = """🎓 <b>Что включает курс подготовки к НОК?</b>\n\nДля успешной сдачи независимой оценки квалификации на базе АНО ДПО «Учебный центр РСС» доступна программа подготовки, которая содержит:\n\n🔹 Порядок прохождения экзамена соискателем\n🔹 Полный лекционный материал\n🔹 Разбор практических задач, встречающихся на экзамене\n🔹 Более 480 тестовых вопросов (максимально близких к реальным)\n🔹 Симулятор экзамена в реальных условиях\n\n⚠️ <i>Напоминаем: отсутствие НОК является основанием для исключения специалиста из реестров НОСТРОЙ/НОПРИЗ!</i>"""
        reply_faq_text(message.chat.id, text, user_text)
        return
    
    elif user_text == "📄 Получение выписки":
        text = """📄 <b>Как получить выписку из реестра членов СРО?</b>\n\nВыписка подтверждает членство компании в СРО и её право выполнять строительные работы по договорам подряда.\n\n🛑 <b>Важные условия для выдачи выписки:</b>\n1️⃣ Отсутствие задолженностей по оплате членских взносов;\n2️⃣ Действующий и непрерывный договор страхования гражданской ответственности;\n3️⃣ Подтвержденный квалификационный состав (минимум 2 специалиста в НРС НОСТРОЙ).\n\n📩 <b>Куда отправлять запрос:</b>\nОфициальный запрос на получение выписки необходимо направить на электронную почту: <code>info@srogen.ru</code>\n\n<i>Email-адрес можно скопировать в один клик!</i>"""
        reply_faq_text(message.chat.id, text, user_text)
        return

    elif user_text == "🔐 Личный кабинет":
        profile = get_user_profile(message.chat.id) or get_sro_profile("OGPS") or {}
        sro_id = profile.get("id") or "OGPS"
        if not sro_has_lichniy_kabinet(sro_id):
            email = (SRO_CONTACTS.get(sro_id) or {}).get("email") or "info@srogen.ru"
            sro_name = profile.get("short_title") or profile.get("name") or "вашего СРО"
            finish_button_reply(
                message.chat.id,
                f"🔐 <b>Личный кабинет</b>\n\n"
                f"На сайте <b>{sro_name}</b> отдельной страницы личного кабинета нет.\n\n"
                f"По вопросам доступа к сервисам Ассоциации напишите на почту:\n"
                f"📧 <code>{email}</code>\n\n"
                f"В письме укажите название организации, ИНН и регистрационный номер в СРО.",
                reply_markup=get_chlenam_keyboard(message.chat.id),
            )
            return

        email = (SRO_CONTACTS.get(sro_id) or {}).get("email") or "partner@srogen.ru"
        # У ОГПС на сайте указан partner@srogen.ru для логина ЛК
        if sro_id == "OGPS":
            email = "partner@srogen.ru"
        sro_title = (
            profile.get("short_title")
            or profile.get("name")
            or "вашего СРО"
        )
        text = (
            f"🔐 <b>Доступ к личному кабинету члена СРО</b>\n\n"
            f"Если вы уже состоите в <b>{sro_title}</b>, для получения логина и пароля "
            f"напишите на почту:\n\n"
            f"📧 <code>{email}</code>\n\n"
            f"В письме укажите:\n"
            f"1️⃣ Название вашей организации\n"
            f"2️⃣ ИНН\n"
            f"3️⃣ Адрес места нахождения организации\n"
            f"4️⃣ Регистрационный номер допуска СРО\n\n"
            f"✉️ Логин и пароль будут отправлены вам в ответ на это письмо.\n\n"
            f"👇 Подробности — на официальной странице раздела «Членам СРО» по кнопке ниже."
        )
        reply_faq_text(message.chat.id, text, user_text)
        return
    
    elif user_text == "💰 Размеры взносов (КФ)":
        sro_id = get_user_sro_id(message.chat.id) or (
            (_faq_site_profile(message.chat.id) or {}).get("id")
        ) or "OGPS"
        text = format_fees_message(sro_id)
        markup = fees_reply_markup(message.chat.id, sro_id)
        if markup and "👇" not in text:
            text += (
                "\n\n👇 <i>Полная информация — на официальном сайте. "
                "Положение о членстве — только если нужен файл.</i>"
            )
        finish_button_reply(message.chat.id, text, reply_markup=markup)
        return
    
    elif user_text == "🎓 Правила сдачи НОК":
        text = """🎓 <b>Главные правила независимой оценки квалификации (НОК)</b>\n\n📌 <b>Как часто проходить?</b>\nЭкзамен сдается очно в Центре оценки квалификаций (ЦОК) <b>не реже одного раза в 5 лет</b>.\n\n🛑 <b>Что будет, если не сдать вовремя?</b>\n🔹 Специалистов исключают из НРС НОСТРОЙ/НОПРИЗ (повторный возврат только через 2 года).\n🔹 Для компаний на особо опасных объектов отсутствие НОК у техслужб — основание для <b>исключения из членов СРО</b>.\n\n🔍 <b>Где проверить свои сроки НОК?</b>\n🔗 Проверка НОСТРОЙ: <code>https://nostroy.ru</code>\n🔗 Проверка НОПРИЗ: <code>https://nopriz.ru</code>\n\n🏢 <b>Контакты экзаменационного центра (ЦОК):</b>\n🌐 Сайт: <code>www.kvalcenter.ru</code>\n📞 Тел: <code>+74951325033</code>\n📧 Email: <code>info@kvalcenter.ru</code>\n\n👤 <b>Куратор предэкзаменационной подготовки:</b>\n👨‍💼 Недоводеев Тимур Игорьевич\n📞 Тел: <code>+79857785570</code>\n📧 Email: <code>moscenternok@gmail.com</code>\n\n<i>Все ссылки, телефоны и email можно скопировать в один клик!</i>"""
        reply_faq_text(message.chat.id, text, user_text)
        return
    
    elif user_text == TRUSTED_BUTTON:
        reply_faq_text(
            message.chat.id,
            format_trusted_members_message(),
            user_text,
            add_footer=False,
        )
        return

    elif user_text == "🏢 Об Ассоциации СРО":
        sro_id = get_user_sro_id(message.chat.id) or "OGPS"
        text = format_about_association(sro_id)
        reply_faq_text(message.chat.id, text, user_text)
        return
    
    elif user_text == "📩 Жалобы и предложения":
        text = """📩 <b>Жалобы и предложения</b>

Ваше мнение важно для Ассоциации. Вы можете сообщить о проблеме или предложить идею по улучшению работы СРО.

📝 <b>Онлайн-форма на сайте</b>
Укажите ФИО, email, телефон и текст обращения — форма доступна на официальной странице.

☎️ <b>Телефон доверия:</b> <code>+7 (905) 757-66-99</code>
📧 <b>Email:</b> <code>info@srogen.ru</code>
📞 <b>Многоканальный:</b> <code>+7 (495) 775-81-11</code>

👇 Отправить жалобу или предложение через форму — по кнопке ниже."""
        reply_faq_text(message.chat.id, text, user_text)
        return

    elif user_text == "🔍 Расписание проверок":
        profile = get_user_profile(message.chat.id) or get_sro_profile("OGPS")
        site = (profile or {}).get("site") or SRO_SITE
        sro_name = (profile or {}).get("short_title") or "СРО"
        text = (
            "🔍 <b>Как часто СРО проверяет компании?</b>\n\n"
            "📅 <b>Не реже одного раза в год.</b>\n\n"
            "По закону плановая проверка каждого члена СРО проходит минимум раз в год. "
            "Внеплановые проверки могут быть назначены, если на организацию поступила жалоба.\n\n"
            f"👇 <i>Разделы для <b>{sro_name}</b> — кнопки ниже. "
            "Если другое СРО — сначала введите ИНН и выберите его.</i>"
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(
                "🌐 Организация контроля",
                url=f"{site}/kontrol_sro/ob_organizacii/",
            )
        )
        markup.add(
            types.InlineKeyboardButton(
                "📅 План проверок по месяцам",
                url=f"{site}/kontrol_sro/kontrolniy_komitet/plan_proverok/",
            )
        )
        finish_button_reply(message.chat.id, text, reply_markup=markup)
        return

    elif user_text == "📝 Как вступить в СРО?":
        sro_id = get_user_sro_id(message.chat.id) or "OGPS"
        reply_faq_text(message.chat.id, format_how_to_join_text(sro_id), user_text)
        return

    elif user_text == "📋 Проверяемые документы":
        enter_faq_mode(message.chat.id)
        reply_faq_text(message.chat.id, documents_list_text, user_text, add_footer=False)
        finish_button_reply(
            message.chat.id,
            _download_docs_intro(message.chat.id),
            reply_markup=get_download_docs_keyboard(message.chat.id),
        )
        return

    elif "Требования к специалистам" in user_text:
        text = """🏢 <b>Требования к специалистам для вступления в СРО:</b>

С 01.07.2017 действуют требования к специалистам, в функции которых входит организация строительства. По основному месту работы в штате должно быть <b>не менее 2 специалистов</b>, сведения о которых включены в <b>НРС НОСТРОЙ</b>.

📌 <b>Особо опасные, технически сложные и уникальные объекты</b> (ПП РФ № 338): в НРС должны быть внесены руководители из штата (гендиректор/директор, техдиректор, заместители, главный инженер):
• <b>не менее 2</b> — при договорах до 3 млрд ₽;
• <b>не менее 3</b> — при договорах свыше 3 млрд ₽.

📌 <b>К каждому специалисту:</b>
• Высшее профильное образование (перечень Минстроя).
• Стаж на инженерных должностях <b>не менее 3 лет</b> и общий стаж в строительстве <b>10 лет</b> (или <b>5 лет</b> при действующей НОК).
• Действующее свидетельство <b>НОК</b> (экзамен — каждые 5 лет).

📋 Полный перечень из <b>7 документов</b> для подачи в НРС — в кнопке «📋 Документы в НРС» в разделе «Специалисты и НОК».

⚠️ <i>При несоответствии специалистов в приеме компании или выдаче выписки будет отказано!</i>"""
        reply_faq_text(message.chat.id, text, user_text)
        return

    # Кнопка: Сроки рассмотрения / вступления
    elif "Сроки рассмотрения" in user_text or user_text == "⏱ Сроки вступления":
        sro_id = get_user_sro_id(message.chat.id) or "OGPS"
        text = format_sroki_vstupleniya_text(sro_id)
        reply_faq_text(message.chat.id, text, user_text)
        return

    # Кнопка: Изменения в Реестр
    elif "Изменения в Реестр" in user_text:
        text = """🔄 <b>Внесение изменений в Реестр членов СРО:</b>

Член СРО обязан уведомлять Ассоциацию об изменении сведений, внесённых в реестр (изменение адреса, директора, смена уровня ответственности и лимитов).

🛑 <b>Порядок действий:</b>
1️⃣ Заполните заявление установленного образца.
2️⃣ Подготовьте документы, подтверждающие изменения (листы записи ЕГРЮЛ, новые полисы страхования и т.д.).
3️⃣ Направьте пакет документов на электронную почту: <code>info@srogen.ru</code>

⚠️ <i>Срок рассмотрения документов составляет не более 3 рабочих дней с момента подачи полного пакета.</i>"""
        reply_faq_text(message.chat.id, text, user_text)
        return

    # Кнопка: Устранение нарушений
    elif "устранение нарушений" in user_text.lower():
        text = """🛠 <b>Устранение выявленных нарушений:</b>

Если в ходе проверки у вашей организации были выявлены нарушения, их необходимо устранить в установленный Дисциплинарной комиссией или КК срок.

📝 <b>Что нужно предоставить для снятия замечаний:</b>
• <b>Отчёт об устранении нарушений</b> (официальный бланк на имя руководителя).
• Документы, подтверждающие исправление (копии дипломов, договоров, ТК, платежек по взносам).

📩 Документы направляются строго на email вашего куратора или на общую почту: <code>info@srogen.ru</code>"""
        reply_faq_text(message.chat.id, text, user_text)
        return

    # Кнопка: База законов СРО
    elif "База законов СРО" in user_text:
        text = """⚖️ <b>Нормативно-правовая база саморегулирования (СРО):</b>

Деятельность строительных СРО и их членов жестко регламентируется законодательством РФ.

📚 <b>Основные документы:</b>
🔹 <b>Градостроительный кодекс РФ</b> (ГрК РФ) — Главы 6.1 и 6.2 (основной закон для СРО).
🔹 <b>Федеральный закон № 315-ФЗ</b> «О саморегулируемых организациях».
🔹 <b>Федеральный закон № 191-ФЗ</b> «О введении в действие Градостроительного кодекса РФ».

👇 <i>Вы можете ознакомиться с полными текстами законов и внутренними стандартами Ассоциации на официальном сайте в разделе «Документы».</i>"""
        reply_faq_text(message.chat.id, text, user_text)
        return

    # Кнопка: Документы в НРС (ОБНОВЛЕНО: СТРОГО 7 ПУНКТОВ С САЙТА)
    elif "Документы в НРС" in user_text:
        text = """📋 <b>Документы для внесения в НРС НОСТРОЙ:</b>

Для внесения специалиста в Национальный реестр в Ассоциацию необходимо представить заверенное у нотариуса Заявление о включении сведений, а также следующий комплект документов:

1️⃣ <b>Копия документа о высшем образовании</b> (нотариальная копия).
2️⃣ <b>Документы, подтверждающие стаж:</b> на инженерных должностях не менее 3 лет и общий стаж в строительстве не менее 10 лет (или не менее 5 лет при прохождении НОК).
3️⃣ <b>Копия свидетельства</b> о прохождении независимой оценки квалификации (НОК).
4️⃣ <b>Копия разрешения на работу или патент</b> (для лиц, не являющихся гражданами РФ).
5️⃣ <b>Справка об отсутствии судимости</b> (оригинал с синей печатью МВД или ЭЦП с Госуслуг, выданная не ранее 3 месяцев до дня подачи).
6️⃣ <b>Копия СНИЛС</b> (для лиц, не являющихся гражданами РФ – при наличии).
7️⃣ <b>Форма ознакомления</b> с условиями обработки персональных данных заявителя.

👇 <i>Для внесения изменений в сведения специалиста также необходимо направлять нотариально заверенное Заявление с подтверждающими документами.</i>"""
        reply_faq_text(message.chat.id, text, user_text)
        return

    # Кнопка: Кураторы НРС (ИСПРАВЛЕНО НА РЕАЛЬНЫХ СОТРУДНИКОВ)
    elif "Кураторы НРС" in user_text:
        text = """👤 <b>Кураторы по вопросам Национального реестра специалистов (НРС):</b>

Наши эксперты помогут вам проверить дипломы на соответствие перечню Минстроем и проконсультируют по пакету документов.

📞 <b>Контакты специалистов департамента:</b>
• <b>Вельвич Иван Иванович</b>
  Тел: <code>(495) 775-81-11</code> доб. <code>173</code>
  Email: <code>i.velvich@srogen.ru</code>

• <b>Петров Илья Александрович</b>
  Тел: <code>(495) 775-81-11</code> доб. <code>153</code>
  Email: <code>i.petrov@srogen.ru</code>

🌐 <i>Общий многоканальный телефон Ассоциации: +7 (495) 775-81-11</i>"""
        reply_faq_text(message.chat.id, text, user_text)
        return
    elif "Филиалы СРО" in user_text:
        text = """🌍 <b>Филиалы и представители СРО Ассоциации</b>

Ассоциация зарегистрирована в Москве. Для работы с компаниями из регионов действуют <b>2 филиала в Москве</b> и <b>представители в ряде субъектов РФ</b>.

📍 <b>Филиал по Северо-Западному ФО</b> (Москва)
👤 Новоселов Алексей Алексеевич
🏢 117292, Москва, ул. Ивана Бабушкина, д. 4, корп. 1
📞 <code>+7 (495) 730-53-63</code>, <code>+7 (495) 999-97-81</code>
📧 <code>a.novoselov@npmaap.ru</code>

📍 <b>Филиал «МонтажТеплоСпецстрой»</b> (Москва)
👤 Федин Андрей Федорович
🏢 109147, Москва, ул. Марксистская, д. 3, стр. 1
📞 <code>+7 (495) 777-23-27</code>, <code>+7 (916) 645-87-77</code>
📧 <code>sro_mts@mail.ru</code>

🏢 <b>Представители в регионах:</b>
🔹 <b>Новосибирск</b> — Устинов С.А.: <code>+7 (903) 900-20-09</code>
🔹 <b>Нижний Новгород</b> — Баранов В.М., Грибков Д.С.: <code>+7 (831) 419-92-82</code>
🔹 <b>Казань</b> — Кочетова О.Г.: <code>+7 (843) 200-99-22</code>
🔹 <b>Грозный</b> — Муцаев А.Х.: <code>8 (928) 887-66-63</code>
🔹 <b>Минск</b> — Примак Ю.Д.: <code>+7 (919) 050-11-12</code>

👇 Полный перечень представителей с адресами и email — на официальном сайте по кнопке ниже.

☎️ Центральный офис: <code>+7 (495) 775-81-11</code>, <code>info@srogen.ru</code>"""
        reply_faq_text(message.chat.id, text, user_text)
        return
    # Обработка кнопки Перечень документов для вступления
    elif "Перечень документов для вступления" in user_text or user_text.strip() in (
        "📄 Перечень документов",
        "Перечень документов",
    ):
        text = """📄 <b>Пакет документов для вступления в СРО:</b>

Документы на вступление в СРО Ассоциацию могут подавать юрлица и ИП. Пакет документов соискателя должен включать:

1️⃣ <b>Заявление о приёме</b> в члены СРО Ассоциации.
2️⃣ <b>Документы о страховании</b> гражданской ответственности.
3️⃣ <b>Копии учредительных документов</b> (Устав, ИНН, Лист записи ЕГРЮЛ).
4️⃣ <b>Документы по специалистам НРС</b> (дипломы, трудовые книжки, свидетельства НОК, должностные инструкции).
5️⃣ <b>Сведения о наличии имущества</b> (зданий, оборудования, строительных машин).
6️⃣ <b>Порядок контроля качества</b> выполняемых работ и доверенность на представителя.

👇 <i>Чтобы не перегружать чат десятками отдельных файлов, вы можете скачать официальные бланки, шаблоны заявлений и анкет напрямую с сайта Ассоциации по кнопке ниже:</i>"""
        
        # Красивая инлайн-кнопка со ссылкой на официальный сайт
        reply_faq_text(message.chat.id, text, user_text, add_footer=False)
        return
    elif "Благотворительность" in user_text:
        text = """❤️ <b>Благотворительность</b>

Ассоциация участвует в социальных проектах строительной отрасли совместно с партнёрами и благотворительным фондом <b>«Помощь больным детям»</b>.

🏫 <b>Проект «Дивеевская школа-интернат»</b>
При поддержке Минстроя России и Общественного совета при Минстрое построены мастерские для обучения детей строительным профессиям и эстетическому воспитанию. Торжественное открытие нового корпуса состоялось <b>17 сентября 2024 года</b>.

🤝 <b>Участие СРО и отрасли</b>
В реализации проекта приняли участие саморегулируемые организации и строительные компании, в том числе Ассоциация «Нижегородское объединение строительных организаций».

👇 Фото, новости и подробности — на официальной странице по кнопке ниже."""
        reply_faq_text(message.chat.id, text, user_text)
        return
    elif "Партнеры и НО" in user_text:
        reply_faq_text(message.chat.id, get_partners_full_text(), user_text)
        return

    if send_sro_contact_reply(message.chat.id, user_text):
        exit_ai_mode(message.chat.id)
        return

    if send_partner_reply(message.chat.id, user_text):
        exit_ai_mode(message.chat.id)
        return

    if handle_blanki_menu_text(message.chat.id, user_text, folder_path):
        return

    if is_search_mode(message.chat.id) and not is_ai_mode(message.chat.id):
        handle_universal_search(message.chat.id, user_text)
        return

    clean_inn = normalize_inn(user_text)
    if looks_like_inn(user_text):
        exit_ai_mode(message.chat.id)
        if present_found_organization(
            message.chat.id,
            clean_inn,
            reply_markup=get_main_keyboard(message.chat.id),
        ):
            return
        send_org_not_found(message.chat.id, user_text)
        return


    elif is_ai_mode(message.chat.id):
        if should_route_to_ai(user_text):
            send_ai_reply(message.chat.id, user_text)
            return
        if handle_org_name_search(message.chat.id, user_text):
            return
        send_ai_reply(message.chat.id, user_text)
        return

    if should_route_to_ai(user_text):
        send_ai_reply(message.chat.id, user_text)
        return

    if handle_org_name_search(message.chat.id, user_text):
        return

    if is_faq_mode(message.chat.id):
        send_faq_not_found(message.chat.id)
        return

    # Свободный текст без совпадений в реестре — сразу ИИ, без кнопки «ИИ-помощник»
    if len(user_text.strip()) >= 3:
        send_ai_reply(message.chat.id, user_text)
        return

    bot.send_message(
        message.chat.id,
        "⚠️ Не удалось распознать запрос.\n\n"
        "Выберите раздел в меню ниже или напишите вопрос своими словами — "
        "например: «Что такое НОК?» или «Какие документы для вступления?»\n\n"
        "<i>Для поиска организации введите ИНН или название компании.</i>",
        parse_mode="HTML"
    )

# === ОБРАБОТЧИК НАЖАТИЙ НА ИНЛАЙН-КНОПКИ ОРГАНИЗАЦИЙ ===
@bot.callback_query_handler(func=lambda call: call.data == FB_CALLBACK)
def handle_feedback_bad(call):
    try:
        bot.answer_callback_query(call.id, "Запишем замечание")
        if not has_last_ai(call.message.chat.id):
            bot.send_message(
                call.message.chat.id,
                "Пока нет ответа ИИ для оценки.",
            )
            return
        prompt_feedback_expected(call.message.chat.id)
    except Exception:
        logging.error("Ошибка в handle_feedback_bad", exc_info=True)


@bot.callback_query_handler(
    func=lambda call: call.data in (DOC_FALLBACK_YES, DOC_FALLBACK_NO)
)
def handle_doc_fallback(call):
    try:
        chat_id = call.message.chat.id
        if call.data == DOC_FALLBACK_NO:
            clear_doc_fallback_pending(chat_id)
            bot.answer_callback_query(call.id, "Ок")
            bot.send_message(
                chat_id,
                "Хорошо. Можно уточнить вопрос или открыть сайт: https://www.srogen.ru/",
            )
            return

        question = pop_doc_fallback_pending(chat_id)
        if not question:
            bot.answer_callback_query(call.id, "Вопрос устарел")
            bot.send_message(
                chat_id,
                "Задайте вопрос ещё раз — предложение по документу уже неактуально.",
            )
            return

        bot.answer_callback_query(call.id, "Ищу в документах…")
        try:
            bot.send_chat_action(chat_id, "typing")
        except Exception:
            pass
        bot.send_message(chat_id, "⏳ Готовлю короткий ответ по документу…")
        result = answer_from_document(question, sro_id=get_user_sro_id(chat_id))
        bot.send_message(
            chat_id,
            result.get("text") or "⚠️ Пустой ответ.",
            parse_mode="HTML",
        )
    except Exception:
        logging.error("Ошибка в handle_doc_fallback", exc_info=True)


@bot.callback_query_handler(func=lambda call: call.data == "faq:ask_ai")
def handle_faq_ask_ai(call):
    try:
        bot.answer_callback_query(call.id, "⏳ Ищу ответ...")
        start_faq_ai_chat(call.message.chat.id)
    except Exception:
        logging.error("Ошибка в handle_faq_ask_ai", exc_info=True)


@bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("fees_doc:"))
def handle_fees_doc_download(call):
    try:
        sro_id = call.data.split(":", 1)[1]
        bot.answer_callback_query(call.id, "Отправляю файл…")
        pol_path = fees_doc_path(sro_id)
        if not pol_path or not os.path.isfile(pol_path):
            bot.send_message(
                call.message.chat.id,
                "⚠️ Файл Положения о членстве не найден. "
                "Запросите актуальный документ в Ассоциации или на сайте СРО.",
            )
            return
        tg_upload_document(call.message.chat.id)
        with open(pol_path, "rb") as file:
            bot.send_document(
                call.message.chat.id,
                file,
                caption=(
                    "📄 <b>Положение о членстве</b> — сверьте раздел о взносах перед оплатой."
                ),
                parse_mode="HTML",
            )
    except Exception:
        logging.error("Ошибка в handle_fees_doc_download", exc_info=True)
        bot.send_message(
            call.message.chat.id,
            "⚠️ Не удалось отправить файл. Попробуйте позже или запросите на сайте СРО.",
        )


@bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("chk:"))
@log_errors
def handle_checko_callbacks(call):
    chat_id = call.message.chat.id
    if not can_use_checko(chat_id):
        safe_answer_callback(
            call.id,
            "Checko — в /controller",
        )
        return
    parts = (call.data or "").split(":")
    # chk:r:INN | chk:f:INN | chk:s:SECTION:INN
    if len(parts) < 3:
        safe_answer_callback(call.id, "Устаревшая кнопка")
        return
    kind = parts[1]
    if kind == "r" and len(parts) >= 3:
        inn = parts[2]
        safe_answer_callback(call.id, "Реестр СРО…")
        if not org_in_local_reestr(inn):
            safe_send_message(
                chat_id,
                "❌ В реестре 15 СРО этой организации нет.",
            )
            return
        send_company_card(
            chat_id,
            inn,
            reply_markup=get_main_keyboard(chat_id),
        )
        exit_search_mode(chat_id)
        return
    if kind == "f" and len(parts) >= 3:
        inn = parts[2]
        print(f"🔎 chk:f inn={inn} chat={chat_id}", flush=True)
        safe_answer_callback(call.id, "Загружаю…")
        try:
            bot.send_chat_action(chat_id, "typing")
        except Exception:
            pass
        # Сразу полезная карточка + меню разделов (не пустой экран).
        try:
            text = format_checko_section("general", inn)
        except Exception as exc:
            print(f"⚠️ Checko general: {exc}", flush=True)
            text = (
                f"🔎 <b>Полная информация</b> (ИНН <code>{inn}</code>)\n\n"
                "Не удалось загрузить краткие данные. Выберите раздел ниже "
                "или откройте сайт."
            )
        try:
            safe_send_message(
                chat_id,
                text,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=get_checko_sections_keyboard(inn, page=0),
                retries=4,
            )
        except Exception as exc:
            print(f"⚠️ chk:f send failed: {exc}", flush=True)
            # Запасной путь — хотя бы ссылка на сайт.
            kb = types.InlineKeyboardMarkup()
            kb.add(
                types.InlineKeyboardButton(
                    "🌐 Открыть на checko.ru",
                    url=checko_site_url(inn),
                )
            )
            if org_in_local_reestr(inn):
                kb.add(
                    types.InlineKeyboardButton(
                        "📦 В реестре СРО",
                        callback_data=f"chk:r:{inn}",
                    )
                )
            safe_send_message(
                chat_id,
                f"⚠️ Не удалось отправить меню Checko (сеть Telegram).\n"
                f"ИНН <code>{inn}</code> — откройте карточку на сайте:",
                parse_mode="HTML",
                reply_markup=kb,
                retries=3,
            )
        return
    if kind == "m" and len(parts) >= 3:
        inn = parts[2]
        page = int(parts[3]) if len(parts) >= 4 and str(parts[3]).isdigit() else 0
        safe_answer_callback(call.id)
        try:
            bot.edit_message_reply_markup(
                chat_id,
                call.message.message_id,
                reply_markup=get_checko_sections_keyboard(inn, page=page),
            )
        except Exception:
            safe_send_message(
                chat_id,
                f"📂 Разделы (ИНН <code>{inn}</code>):",
                parse_mode="HTML",
                reply_markup=get_checko_sections_keyboard(inn, page=page),
            )
        return
    if kind == "s" and len(parts) >= 4:
        section = parts[2]
        inn = parts[3]
        print(f"🔎 chk:s section={section} inn={inn} chat={chat_id}", flush=True)
        safe_answer_callback(call.id, "Загружаю…")
        try:
            bot.send_chat_action(chat_id, "typing")
        except Exception:
            pass
        text = format_checko_section(section, inn)
        safe_send_message(
            chat_id,
            text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=get_checko_after_section_keyboard(inn),
            retries=4,
        )
        return
    safe_answer_callback(call.id, "Неизвестная команда")


@bot.callback_query_handler(func=lambda call: call.data.startswith("search_inn:"))
@log_errors
def handle_inline_search(call):
    inn = call.data.split(":")[1] # Извлекаем ИНН из скрытых данных
    chat_id = call.message.chat.id

    if inn in sro_database or inn in reestr_database:
        bot.answer_callback_query(call.id, "⏳ Ищу данные по организации...")
        bot.delete_message(chat_id, call.message.message_id)
        outcome = present_found_organization(
            chat_id,
            inn,
            reply_markup=get_main_keyboard(chat_id),
        )
        if outcome == "card":
            exit_search_mode(chat_id)
            return
        if outcome == "fork":
            # Список закрыли, развилка открыта — универсальный поиск не сбрасываем.
            return
        bot.send_message(
            chat_id,
            "❌ Данные организации устарели, попробуйте еще раз.",
        )
        return
    else:
        bot.answer_callback_query(call.id, "❌ Данные организации устарели, попробуйте еще раз.")

if __name__ == "__main__":
    BOT_VERSION = "1.09"
    setup_bot_commands()
    from prevent_sleep import install_for_bot

    if install_for_bot():
        print("💤 Автосон Windows отключён, пока бот запущен (Ctrl+C — выход).", flush=True)
    print(f"🚀 Бот запускается... ({BOT_VERSION})", flush=True)
    print(f"👥 В журнале пользователей: {users_count()} (файл bot_users.json)", flush=True)
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=20)
        except KeyboardInterrupt:
            break
        except Exception as e:
            logging.error("Polling упал, перезапуск через 5 сек...", exc_info=True)
            print(f"⚠️ Сбой связи с Telegram: {e}. Перезапуск через 5 сек...", flush=True)
            import time
            time.sleep(5)