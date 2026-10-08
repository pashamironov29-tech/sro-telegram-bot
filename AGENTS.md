# Правила для ИИ-ассистентов

Читать в начале сессии (Cursor, DeepSeek). Отвечать и рассуждать только по-русски. Английский — в именах файлов, функций и команд.

## Что это

Помощник экосистемы СРО Ассоциации «ГЕН». Две оболочки, общая логика.

- Telegram: `bot_FINAL_GOLD.py`, служба `sro-bot`. Версия — `BOT_VERSION` в этом файле (сейчас `1.12`).
- MAX: `bot_MAX.py`, клиент `max_api.py`, служба `sro-max-bot`. Свой процесс и токен.
- Режимы и права: `bot_core.py`. Оболочки рисуют кнопки и шлют сообщения.
- Ответы своими словами, без нейросети: `local_answers.py` — партнёры, темы по словам, «Вопрос-ответ», страницы сайта.

Партнёрских СРО пятнадцать: `PROD_SRO_COUNT` в `sro_profiles.py`, список — `SRO_SOURCES` в `reestr_sync.py`.

## Что умеет

- Поиск по ИНН и названию, карточка из реестра (`reestr_sync.py`). Кэш `reestr_cache.json` в git не лежит.
- Ночной синк: `sro-reestr-sync.timer`, 02:00 МСК. `vps/reestr_daily_sync.sh` ставит `maintenance_stub.py`, запускает `reestr_sync.py --daily`, поднимает `sro-bot`.
- Бланки: `blanki_sro.py`. Автозаполнение инфолиста и заявления на проверку: `info_list_fill.py` (заявление об изменениях и доверенность в коде выключены). Опрос инфолиста: `info_list_quiz.py`.
- FAQ: `voprosy_faq.py`, `faq_menu_content.py`, `sro_site_qa.py`. Взносы: `sro_fees.py`.
- Контакты СРО: `sro_contacts.py`. Справочник сотрудников: `contacts_search.py` (живой `contacts_data.py` не в git). Партнёры: `partners_data.py`. НРС: `nrs_search_links.py`.
- Checko для контролёров: `checko_client.py`, допуск — `controller_access.py`, команда `/controller`.
- Команды: `/start`, `/help`, `/search`, `/info`, `/controller`. В Telegram ещё админские `/users` и `/notify_update` (рассылка только с `confirm`). В MAX этих двух нет.
- Watchdog Telegram: `sro-telegram-watchdog.timer`, каждые 5 минут (`vps/telegram_watchdog.sh`).
- Проверка сайтов СРО и страниц реестра (и НРС) в 08:00 МСК: `sro-site-health.timer` → `site_health_check.py`. Эти страницы — источник ночного синка; при сбое админам уходит сообщение.

## Карта файлов

| Файл | Зачем |
|------|--------|
| `bot_FINAL_GOLD.py`, `bot_MAX.py` | оболочки Telegram и MAX |
| `bot_core.py`, `local_answers.py` | режимы и ответ без LLM |
| `reestr_sync.py` | загрузка реестров и карточка |
| `sro_profiles.py`, `sro_context.py`, `sro_about.py` | 15 СРО, контекст, «об ассоциации» |
| `blanki_sro.py`, `info_list_fill.py` | бланки и инфолист |
| `vps/` | systemd, таймеры, скрипты `.sh` |
| `scripts/` | офлайн-проверки, бот их не запускает |
| `docs/VERSION_HISTORY.md` | журнал версий |

## Как проверять

Python 3. В `requirements.txt` версия не зафиксирована. На VPS — `/opt/sro-bot/venv` из системного `python3` (Ubuntu 22.04/24.04, `vps/install.sh`).

Pytest-набора нет: в `tests/` пустой `__init__.py`, pytest не в зависимостях.

Из корня:

```bash
python scripts/routing_regression.py
python scripts/check_max_menu.py
python scripts/test_nrs_search_links.py
python vps/check_prod_sro_gate.py
```

`test_nrs_search_links.py` в конце ходит в живой API НОПРИЗ. `check_max_menu.py` для Checko сеть не требует.

## Правила правок

- Чинить только прямую ошибку. Методику и косметику без явной просьбы не делать.
- Нейросеть (LLM, GigaChat, OpenRouter, DeepSeek, распознавание голоса) и модуль новостей (`sro_news.py`) убраны намеренно в `1.11`. Не возвращать.
- Репозиторий публичный. Ключи, токены, пароли и данные людей не класть в код, тесты, логи и коммиты. Не коммитить `config_keys.py`, `.env`, `contacts_data.py` (они в `.gitignore`). Примеры: `config_keys.example.py`, `.env.example`, `contacts_data.example.py`.
- Любую смену логики проверять в Telegram и в MAX.
- Новые зависимости — только по согласованию.

## Выкладка

На VPS каталог `/opt/sro-bot` без git: файлы берутся с GitHub raw по коммиту. Перезапуск: `systemctl restart sro-bot sro-max-bot`. Боевой `config_keys.py` на сервере не затирать.

Файлы `.sh` с переводами строк Windows (CRLF) на сервере ломаются. Держать LF. Файла `.gitattributes` нет.

Старые заметки про копирование с ПК: `docs/VPS_SETUP.md`, `docs/DEPLOY_1.10.md`.
