# Безопасность репозитория GOLD

## Правило

В git попадает только код и примеры. **Живые ключи — только в локальном `config_keys.py` и на VPS.**

## Перед каждым push

```powershell
# не должно быть config_keys.py
git status
git check-ignore -v config_keys.py
# поиск похожих на ключи строк в индексе
git grep -n "BOT_TOKEN\|sk-or-\|gsk_\|CHECKO_API" $(git rev-parse --abbrev-ref HEAD) 2>$null
```

## Если ключ когда-то засветился

Сразу перевыпустить (старый отозвать):

1. Telegram BotFather → `/revoke` или новый токен бота  
2. OpenRouter / Groq / Checko / GigaChat — новые ключи в кабинетах  
3. Сменить `CONTACTS_PASSWORD`  
4. Обновить `config_keys.py` локально и на VPS  

Историю git с секретом **нельзя** «просто удалить файлом» — нужен новый репозиторий или очистка истории. Поэтому первый push делаем только после `.gitignore` и проверки.
