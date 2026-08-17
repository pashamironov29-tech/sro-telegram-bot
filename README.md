# Telegram-бот для СРО (GOLD)

Боевой бот для экосистемы СРО: поиск организаций по ИНН/названию (~18 тыс. карточек), бланки, планы проверок, FAQ/ИИ по материалам сайтов СРО, режим контролёра с расширенной справкой (Checko).

> **Секреты в репозиторий не входят.** Скопируйте `config_keys.example.py` → `config_keys.py` и заполните своими ключами.

## Что умеет (кратко)

- Поиск организации в реестре партнёрских СРО
- Карточка: статус, проверки, бланки под выбранное СРО
- ИИ-помощник по FAQ / документам (OpenRouter / GigaChat / Groq)
- `/controller` — меню для контролёров, «полная информация» по организации
- Работает 24/7 на VPS

## Стек

- Python 3, [pyTelegramBotAPI](https://github.com/eternnoir/pyTelegramBotAPI)
- `python-docx`, `requests`, `pypdf`

## Быстрый старт (локально)

```bash
# 1. Зависимости
pip install -r requirements.txt

# 2. Секреты
copy config_keys.example.py config_keys.py
copy contacts_data.example.py contacts_data.py
# отредактируйте config_keys.py: BOT_TOKEN и ключи ИИ

# 3. Папка бланков (путь в SRO_FILES_DIR)
# 4. Запуск
python bot_FINAL_GOLD.py
```

На Windows есть `START_BOT.ps1` / `START_BOT.bat`.

## Чего нет в git (намеренно)

| Исключено | Почему |
|-----------|--------|
| `config_keys.py` | токены и пароли |
| `contacts_data.py` | телефоны и почты сотрудников (скопируйте `contacts_data.example.py`) |
| `reestr_cache.json` | кэш реестра, собирается скриптом |
| `sro files/` | бланки и внутренние PDF |
| логи, `bot_users.json` | эксплуатационные данные |

## Структура репозитория

| Папка | Содержимое |
|-------|------------|
| корень | runtime-код бота (`bot_FINAL_GOLD.py`, модули), `requirements.txt` |
| `docs/` | инструкции, презентация, VPS-заметки, история версий |
| `scripts/` | офлайн-утилиты (планы месяца, экспорт Word, sync бланков) |
| `assets/` | аватар бота |
| `vps/` | systemd, install, upload |

## Деплой

Краткие заметки: `docs/VPS_SETUP.md`, `docs/VPS_SECURITY.md`, `docs/VPS_5_MIN_CHECK.md`.

## Автор

Павел — разработка Telegram-ботов и автоматизации для СРО / бизнеса.  
Стек: Python, Bot API, парсинг, VPS, работа с ИИ-ассистентами в разработке.
