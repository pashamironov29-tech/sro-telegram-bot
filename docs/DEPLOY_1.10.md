# Выкладка 1.10 на РФ VPS (NL не трогаем)

С ПК сейчас **нет SSH-ключа** → upload завис на пароле. Делать с **ноута**, где ключ есть.

```powershell
cd "O:\Рабочие\GOLD"
.\vps\upload_to_vps.ps1 -VpsIp "YOUR_VPS_IP"
ssh root@YOUR_VPS_IP "systemctl restart sro-bot && systemctl is-active sro-bot"
```

Проверка: Telegram `/controller` или MAX-меню контролёра → **🎙 ИИ-помощник** (не 💬). Оба сервиса: `systemctl restart sro-bot sro-max-bot`.

В upload уже добавлены: `controller_ai.py`, `bot_disclaimers.py`, `gigachat_client.py`.
`config_keys.py` на VPS **не перезаписывается**.