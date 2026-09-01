@echo off
cd /d "%~dp0"
echo ============================================
echo   ASCII CRPG - MVP Prototype
echo ============================================
echo.
echo Installing dependencies...
set "TEXTUAL_VERSION=8.2.8"
set "RICH_VERSION=15.0.0"
python -m pip install -r requirements.txt "textual==%TEXTUAL_VERSION%" "rich==%RICH_VERSION%" -q 2>nul
echo.
echo Starting game...
python main.py
pause
