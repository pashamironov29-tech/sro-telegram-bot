# Скопируйте в config_keys.py на VPS и подставьте свои значения.
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"

# Папка с plany/ и blanki/ на сервере
SRO_FILES_DIR = "/opt/sro-bot/sro_data"

GROQ_API_KEY = "YOUR_GROQ_API_KEY"

# Основной ИИ (отдельный ключ от MC)
OPENROUTER_API_KEY = "YOUR_OPENROUTER_API_KEY"
OPENROUTER_MODEL = "openai/gpt-4.1"
# Сканы/PDF контролёра (если пусто — openai/gpt-4.1)
OPENROUTER_DOC_MODEL = "google/gemini-2.5-flash"

# Запасной ИИ в РФ (Сбер GigaChat)
GIGACHAT_CREDENTIALS = ""
GIGACHAT_SCOPE = "GIGACHAT_API_PERS"
GIGACHAT_MODEL = "GigaChat"
GIGACHAT_VERIFY_SSL = True

CONTACTS_PASSWORD = "YOUR_CONTACTS_PASSWORD"

# MAX messenger (не заливать с Windows — править на VPS)
MAX_BOT_TOKEN = ""
# user_id контролёров в MAX (не Telegram chat_id)
MAX_CONTROLLER_IDS = []

