# Запуск СРО-бота (один экземпляр!)
# Пока процесс жив — Windows не уйдёт в автосон (см. prevent_sleep.py).
Set-Location $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"
py -u bot_FINAL_GOLD.py
