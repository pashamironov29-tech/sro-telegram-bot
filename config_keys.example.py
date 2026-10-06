BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
SRO_FILES_DIR = r"C:\Users\User\OneDrive\Рабочие\GOLD\sro files"

# Запасной: https://console.groq.com/keys
GROQ_API_KEY = "YOUR_GROQ_API_KEY"

# Основной ИИ. Те же имена можно задать в .env (см. .env.example) — они важнее.
# deepseek — напрямую https://api.deepseek.com, без прокси.
# openrouter — прежний путь через OPENROUTER_BASE (прокси в Нидерландах).
LLM_PROVIDER = "deepseek"
DEEPSEEK_API_KEY = ""
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
# deepseek-chat снят 24.07.2026; бот подставляет deepseek-flash и выключает thinking.
DEEPSEEK_MODEL = "deepseek-chat"

# OpenRouter, если LLM_PROVIDER=openrouter: https://openrouter.ai/keys
OPENROUTER_API_KEY = "YOUR_OPENROUTER_API_KEY"
# Прокси OpenRouter (опционально). Прямой openrouter.ai с РФ часто 403.
OPENROUTER_BASE = ""
OPENROUTER_MODEL = "openai/gpt-4.1"
# Сканы/PDF контролёра (если пусто — openai/gpt-4.1)
OPENROUTER_DOC_MODEL = "google/gemini-2.5-flash"

# Запасной ИИ в РФ (Сбер): https://developers.sber.ru/
GIGACHAT_CREDENTIALS = ""
GIGACHAT_SCOPE = "GIGACHAT_API_PERS"  # PERS / B2B / CORP
GIGACHAT_MODEL = "GigaChat"
GIGACHAT_VERIFY_SSL = True

# Пароль для раздела «Контакты отделов» (конфиденциальный справочник)
CONTACTS_PASSWORD = "YOUR_CONTACTS_PASSWORD"

# Кто может смотреть /users (свой Telegram chat_id после /start)
BOT_ADMIN_IDS = []

# Telegram chat_id контролёров СРО (команда /controller)
CONTROLLER_CHAT_IDS = []

# MAX user_id контролёров (в MAX это не тот же номер, что Telegram chat_id)
MAX_CONTROLLER_IDS = []

# Checko API key (полная справка по орг. для контролёров)
CHECKO_API_KEY = ""

# MAX messenger. Токен — только локально, в чат и git не класть.
MAX_BOT_TOKEN = ""
