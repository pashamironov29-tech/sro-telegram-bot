"""Подпроцесс для test_inn_search_telegram.py: поиск по ИНН в Telegram-оболочке.

Отдельный процесс, потому что bot_MAX.py при импорте ставит BOT_PLATFORM=max,
а от платформы зависят общие модули (контекст СРО, режим НРС, список контролёров).
Здесь BOT_PLATFORM=tg. Запуск: python tests/tg_search_probe.py <tmp_dir>
Печатает JSON между маркерами.
"""

from __future__ import annotations

import json
import os
import sys
import types as pytypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["BOT_PLATFORM"] = "tg"

from tests import support  # noqa: E402

MARK_BEGIN = "<<<TG_PROBE_JSON>>>"
MARK_END = "<<<END_TG_PROBE_JSON>>>"


def main(tmp_dir: str) -> None:
    tmp = Path(tmp_dir)
    (tmp / "sro files").mkdir(parents=True, exist_ok=True)
    support.install_config_stub(str(tmp / "sro files"))
    support.block_network()

    import feedback_log
    import local_answers
    import log_redact
    import nrs_search_links
    import reestr_sync
    import sro_context
    import users_log

    users_log.USERS_FILE = tmp / "bot_users.json"
    sro_context._CONTEXT_FILE = tmp / "user_sro_context_tg.json"
    nrs_search_links._MODE_FILE = str(tmp / "nrs_link_mode_tg.json")
    feedback_log.FEEDBACK_FILE = tmp / "feedback_questions.jsonl"
    reestr_sync.CACHE_FILE = str(tmp / "reestr_cache.json")

    original_install = log_redact.install_secret_log_redaction
    log_redact.install_secret_log_redaction = lambda *a, **k: None
    try:
        import bot_FINAL_GOLD as tg
    finally:
        log_redact.install_secret_log_redaction = original_install

    tg.reestr_database = support.sample_reestr()
    tg.sro_database = {}

    sent: list[dict] = []

    def markup_strings(markup) -> list[str]:
        if markup is None:
            return []
        raw = json.loads(markup.to_json())
        out: list[str] = []
        for row in raw.get("keyboard") or raw.get("inline_keyboard") or []:
            for btn in row:
                if isinstance(btn, dict):
                    out.append(btn.get("text") or "")
                    if btn.get("callback_data"):
                        out.append(btn["callback_data"])
                else:
                    out.append(str(btn))
        return out

    def fake_send(chat_id, text, **kwargs):
        sent.append({"text": text, "markup": markup_strings(kwargs.get("reply_markup"))})
        return pytypes.SimpleNamespace(message_id=len(sent))

    tg.bot.send_message = fake_send
    tg.bot.send_chat_action = lambda *a, **k: None
    tg.bot.edit_message_text = lambda *a, **k: None
    tg.bot.delete_message = lambda *a, **k: None

    def reset() -> None:
        sent.clear()
        for container in (
            local_answers.faq_mode_users,
            local_answers.search_mode_users,
            sro_context._user_context,
            sro_context._pending_sro_pick,
            sro_context._pickable_sro_cache,
            sro_context._await_inn,
            sro_context._open_main_after_sro,
        ):
            container.clear()

    uid = support.TEST_UID
    results: dict[str, dict] = {}

    def run(name: str, func, *args) -> None:
        reset()
        local_answers.enter_search_mode(uid)
        ret = func(uid, *args)
        results[name] = {
            "ret": ret,
            "sent": list(sent),
            "sro_id": sro_context.get_user_sro_id(uid),
            "pending": sro_context.pending_sro_ids(uid),
            "search_mode": local_answers.is_search_mode(uid),
        }

    run("found", tg.handle_universal_search, support.INN_SINGLE)
    run("found_spaces", tg.handle_universal_search, "7700 000 001")
    run("found_ip", tg.handle_universal_search, support.INN_IP)
    run("not_found", tg.handle_universal_search, support.INN_ABSENT)
    for raw in ("12345678", "1234567890123", "77000O0001"):
        run(f"malformed:{raw}", tg.handle_universal_search, raw)
    run("short", tg.handle_universal_search, "123")
    run("multi", tg.handle_universal_search, support.INN_MULTI)
    run("present_absent", tg.present_found_organization, support.INN_ABSENT)
    run("looks_like_inn", lambda _uid: [
        tg.looks_like_inn(x) for x in ("7700000001", "770000000004", "12345678", "77000O0001")
    ])

    payload = json.dumps(results, ensure_ascii=False)
    sys.stdout.write(f"{MARK_BEGIN}{payload}{MARK_END}\n")


if __name__ == "__main__":
    main(sys.argv[1])
