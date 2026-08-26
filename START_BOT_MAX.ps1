# Запуск СРО-бота в MAX (отдельный процесс и токен, не Telegram)
# Пока процесс жив — Windows не уйдёт в автосон (см. prevent_sleep.py).
Set-Location $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"
py -u bot_MAX.py
