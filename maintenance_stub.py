#!/usr/bin/env python3
"""Лёгкая заглушка на время sync реестра: тот же токен, ответ «техработы».

Запуск: python -u maintenance_stub.py
Остановка: SIGTERM / SIGINT.
"""

from __future__ import annotations

import logging
import signal
import sys

import telebot
from telebot import types

from config_keys import BOT_TOKEN

MAINTENANCE_TEXT = (
    "🛠 <b>Технические работы</b>\n\n"
    "Сейчас обновляется реестр СРО на сервере — бот временно недоступен.\n"
    "Обычно это <b>30–90 минут</b> (ночью).\n\n"
    "Попробуйте позже или напишите снова через час.\n"
    "Извините за неудобства."
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)


def _reply(chat_id: int) -> None:
    try:
        bot.send_message(chat_id, MAINTENANCE_TEXT, parse_mode="HTML")
    except Exception:
        logging.exception("send_message failed chat_id=%s", chat_id)


@bot.message_handler(commands=["start", "help", "search", "info", "controller", "users"])
def on_cmd(message: types.Message) -> None:
    _reply(message.chat.id)


@bot.message_handler(content_types=["text", "photo", "document", "sticker", "voice", "video"])
def on_any(message: types.Message) -> None:
    _reply(message.chat.id)


@bot.callback_query_handler(func=lambda call: True)
def on_cb(call: types.CallbackQuery) -> None:
    try:
        bot.answer_callback_query(call.id, "Технические работы")
    except Exception:
        pass
    if call.message:
        _reply(call.message.chat.id)


def main() -> int:
    def _stop(*_args) -> None:
        logging.info("maintenance stub stopping")
        try:
            bot.stop_polling()
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    logging.info("maintenance stub started (token held)")
    # long_polling: только ответ, без тяжёлой логики
    bot.infinity_polling(timeout=20, long_polling_timeout=20, skip_pending=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
