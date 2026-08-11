@echo off
cd /d "%~dp0"
call "%~dp0STOP_BOT.bat"
set PYTHONIOENCODING=utf-8
echo Starting bot...
py -u bot_FINAL_GOLD.py
pause
