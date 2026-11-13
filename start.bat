@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv" (
    echo 建立虛擬環境中...
    python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install -q -r requirements.txt

if not exist ".env" (
    echo 找不到 .env，請先把 .env.example 複製成 .env 並填入 DISCORD_TOKEN
    pause
    exit /b 1
)

python bot.py
pause
