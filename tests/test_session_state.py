"""Ожидания ввода переживают перезапуск процесса."""

from __future__ import annotations

import feedback_log
import info_list_quiz
import local_answers
import session_persist
import sro_context
from info_list_quiz import apply_info_list_quiz_answer, start_info_list_quiz
from local_answers import enter_search_mode, is_search_mode


def test_search_inn_and_joiner_waits_survive_restart():
    enter_search_mode(3)
    local_answers.search_mode_users.clear()
    local_answers._load_persisted()
    assert is_search_mode(3) is True

    sro_context.begin_await_inn(7)
    sro_context._await_inn.clear()
    sro_context._open_main_after_sro.clear()
    sro_context._load_persisted()
    assert sro_context.is_awaiting_inn(7) is True
    assert 7 in sro_context._open_main_after_sro

    sro_context.begin_joiner_activity_pick(8)
    sro_context._await_joiner_activity.clear()
    sro_context._load_persisted()
    assert sro_context.is_awaiting_joiner_activity(8) is True

    sro_context.clear_joiner_activity_await(8)
    sro_context._await_joiner_activity.add(8)
    sro_context._load_persisted()
    assert sro_context.is_awaiting_joiner_activity(8) is False


def test_info_quiz_and_feedback_wait_survive_restart():
    start_info_list_quiz(4, "7700000001", "OGPS")
    assert apply_info_list_quiz_answer(4, "как юр.")["kind"] == "question"
    info_list_quiz._sessions.clear()
    info_list_quiz._load_persisted()
    sess = info_list_quiz._sessions[4]
    assert sess["step"] == 1
    assert sess["answers"]["fact_address"] == "как юр."
    assert sess["inn"] == "7700000001"

    feedback_log.remember_ai_reply(
        8, question="вопрос", answer_text="ответ", route="faq", sro_id="OGPS"
    )
    assert feedback_log.begin_await_expected(8) is True
    feedback_log._await_expected.clear()
    feedback_log._last_ai.clear()
    feedback_log._load_persisted()
    assert feedback_log.is_awaiting_expected(8) is True
    assert feedback_log.has_last_ai(8) is True


def test_state_file_name_depends_on_platform():
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(session_persist.__file__).resolve().parent
    names = {}
    for plat in ("tg", "max"):
        env = dict(os.environ, BOT_PLATFORM=plat)
        out = subprocess.run(
            [sys.executable, "-c", "import session_persist as s; print(s.STATE_FILE.name)"],
            cwd=root, env=env, capture_output=True, text=True, timeout=60, check=True,
        )
        names[plat] = out.stdout.strip().splitlines()[-1]
    assert names == {"tg": "session_state_tg.json", "max": "session_state_max.json"}
