# Бот СРО для Telegram и MAX (GOLD)

Боевой помощник для экосистемы СРО в **Telegram** и **MAX**: поиск организаций по ИНН/названию (~18 тыс. карточек), бланки, планы проверок, FAQ/ИИ по материалам сайтов СРО, режим контролёра с расширенной справкой (Checko).

> **Секреты в репозиторий не входят.** Скопируйте `config_keys.example.py` → `config_keys.py` и заполните своими ключами (`BOT_TOKEN`, `MAX_BOT_TOKEN`, ИИ и т.д.).

## Каналы

| Канал | Запуск | Сервис на VPS |
|-------|--------|----------------|
| **Telegram** | `bot_FINAL_GOLD.py` | `sro-bot` |
| **MAX** | `bot_MAX.py` | `sro-max-bot` |

Общая логика (поиск, FAQ, контролёр, ИИ) — в shared-модулях; интерфейсы мессенджеров разделены.

## Что умеет (кратко)

- Поиск организации в реестре партнёрских СРО
- Карточка: статус, проверки, бланки под выбранное СРО
- ИИ-помощник по FAQ / документам (OpenRouter / GigaChat / Groq)
- Режим контролёра: меню, «полная информация» по организации, голос/файлы в ИИ
- Работает 24/7 на VPS (оба бота параллельно)

## Стек

- Python 3
- Telegram: [pyTelegramBotAPI](https://github.com/eternnoir/pyTelegramBotAPI)
- MAX: [MAX Bot API](https://dev.max.ru/) (`max_api.py`, long polling)
- `python-docx`, `openpyxl`, `requests`, `pypdf`

## Быстрый старт (локально)

```bash
pip install -r requirements.txt

copy config_keys.example.py config_keys.py
copy contacts_data.example.py contacts_data.py
# config_keys.py: BOT_TOKEN, MAX_BOT_TOKEN, ключи ИИ

# Telegram
python bot_FINAL_GOLD.py

# MAX (отдельный процесс)
python bot_MAX.py
```

На Windows: `START_BOT.ps1` / `START_BOT.bat` (Telegram), `START_BOT_MAX.ps1` / `START_BOT_MAX.bat` (MAX).

## Чего нет в git (намеренно)

| Исключено | Почему |
|-----------|--------|
| `config_keys.py` | токены и пароли |
| `contacts_data.py` | телефоны и почты сотрудников (скопируйте `contacts_data.example.py`) |
| `reestr_cache.json` | кэш реестра, собирается скриптом |
| `sro files/` | бланки и внутренние PDF |
| логи, `bot_users.json` | эксплуатационные данные |

## Структура репозитория

| Папка / файл | Содержимое |
|--------------|------------|
| `bot_FINAL_GOLD.py` | Telegram-бот |
| `bot_MAX.py`, `max_api.py` | MAX-бот и клиент API |
| корень | shared-модули (поиск, FAQ, controller, ИИ) |
| `docs/` | инструкции, презентация, VPS-заметки |
| `scripts/` | офлайн-утилиты, регрессия, проверка меню MAX |
| `assets/` | аватар бота |
| `vps/` | systemd, upload, watchdog |

## Деплой

Краткие заметки: `docs/VPS_SETUP.md`, `docs/VPS_SECURITY.md`, `docs/VPS_5_MIN_CHECK.md`, `docs/DEPLOY_1.10.md`.

На VPS после заливки: `systemctl restart sro-bot sro-max-bot`.

## Автор

Павел — разработка ботов для мессенджеров (Telegram, MAX) и автоматизация для СРО / бизнеса.  
Стек: Python, Bot API, парсинг, VPS, ИИ-ассистенты в разработке.
