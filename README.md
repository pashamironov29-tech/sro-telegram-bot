# Бот СРО для Telegram и MAX (GOLD)

Боевой помощник для экосистемы СРО в **Telegram** и **MAX**: поиск организаций по ИНН/названию (~18 тыс. карточек), бланки, планы проверок, FAQ и ответы по материалам сайтов СРО, режим контролёра с справкой Checko по организации (доступна всем).

> **Секреты в репозиторий не входят.** Скопируйте `config_keys.example.py` → `config_keys.py` и заполните своими ключами (`BOT_TOKEN`, `MAX_BOT_TOKEN`).

Правила для ассистентов (Cursor, DeepSeek): [AGENTS.md](AGENTS.md).

## Каналы

| Канал | Запуск | Сервис на VPS |
|-------|--------|----------------|
| **Telegram** | `bot_FINAL_GOLD.py` | `sro-bot` |
| **MAX** | `bot_MAX.py` | `sro-max-bot` |

Общая логика (поиск, FAQ, Checko) — в shared-модулях; интерфейсы мессенджеров разделены.

## Что умеет (кратко)

- Поиск организации в реестре партнёрских СРО
- Карточка: статус, проверки, бланки под выбранное СРО
- Вопрос своими словами: партнёры, темы, «Вопрос-ответ», ссылка на сайт
- Checko: кнопка «📋 Проверить в Checko» под карточкой организации (для всех)
- Работает 24/7 на VPS (оба бота параллельно)

## Стек

- Python 3
- Telegram: [pyTelegramBotAPI](https://github.com/eternnoir/pyTelegramBotAPI)
- MAX: [MAX Bot API](https://dev.max.ru/) (`max_api.py`, long polling)
- `python-docx`, `openpyxl`, `requests`

## Быстрый старт (локально)

```bash
pip install -r requirements.txt

copy config_keys.example.py config_keys.py
copy contacts_data.example.py contacts_data.py
# config_keys.py: BOT_TOKEN, MAX_BOT_TOKEN

# Telegram
python bot_FINAL_GOLD.py

# MAX (отдельный процесс)
python bot_MAX.py
```

На Windows: `START_BOT.ps1` / `START_BOT.bat` (Telegram), `START_BOT_MAX.ps1` / `START_BOT_MAX.bat` (MAX).

Telegram и MAX пишут один журнал `bot_users.sqlite` (SQLite, WAL). У строки есть площадка `tg` или `max`: одинаковый числовой id в двух мессенджерах — разные люди. Старый `bot_users.json` при первом запуске переносится в базу и остаётся на диске как копия, бот его больше не переписывает.

Ожидания ввода (поиск, FAQ, ИНН, опрос инфолиста, фраза «какой ответ ждали») лежат в `session_state_tg.json` и `session_state_max.json` и переживают перезапуск процесса.

Разово снять порог «меньше половины» у синка специалистов: `python specialist_sync.py --allow-prune OGPS` (флаг можно повторить). Переменную `SPECIALIST_ALLOW_PRUNE` в unit-файл `sro-specialist-sync.service` насовсем не прописывать — ночной синк иначе будет удалять членов при каждом коротком списке.

## Чего нет в git (намеренно)

| Исключено | Почему |
|-----------|--------|
| `config_keys.py` | токены и пароли |
| `contacts_data.py` | телефоны и почты сотрудников (скопируйте `contacts_data.example.py`) |
| `reestr_cache.json` | кэш реестра, собирается скриптом |
| `sro files/` | бланки и внутренние PDF |
| логи, `bot_users.json`, `bot_users.sqlite` | эксплуатационные данные |

## Структура репозитория

| Папка / файл | Содержимое |
|--------------|------------|
| `bot_FINAL_GOLD.py` | Telegram-бот |
| `bot_MAX.py`, `max_api.py` | MAX-бот и клиент API |
| корень | shared-модули (поиск, FAQ, Checko) |
| `docs/` | инструкции, презентация, VPS-заметки |
| `scripts/` | офлайн-утилиты, регрессия, проверка меню MAX |
| `assets/` | аватар бота |
| `vps/` | systemd, upload, watchdog |

## Деплой

Push в `master` запускает `.github/workflows/deploy.yml`: тесты, затем выкладка в `/opt/sro-bot`. Джоба `deploy` привязана к environment `production`. Если в этом environment включены Required reviewers, копирование ждёт кнопку подтверждения.

Секреты: `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`. Необязательные: `VPS_PORT` (иначе 22), `VPS_KNOWN_HOSTS` (иначе ключ хоста берётся через ssh-keyscan на время прогона).

На сервер попадают только файлы из git. `config_keys.py`, `contacts_data.py` и каталог `vps/` не затираются. Заменённые файлы до копирования лежат в `/opt/sro-bot/backups/auto-ГГГГММДД-ЧЧММСС` (последние 10 каталогов `auto-*`). После копирования перезапускаются только `sro-bot` и `sro-max-bot`.

Ручной откат:

```bash
cp -a /opt/sro-bot/backups/auto-…/files/. /opt/sro-bot/ && systemctl restart sro-bot sro-max-bot
```

Новые файлы этого прогона перечислены в `changes.txt` рядом с бэкапом — при ручном откате их нужно удалить. `pip` при откате сам не возвращается.

Краткие заметки о первой установке: `docs/VPS_SETUP.md`, `docs/VPS_SECURITY.md`, `docs/VPS_5_MIN_CHECK.md`, `docs/DEPLOY_1.10.md`.

## Автор

Павел — разработка ботов для мессенджеров (Telegram, MAX) и автоматизация для СРО / бизнеса.  
Стек: Python, Bot API, парсинг, VPS.
