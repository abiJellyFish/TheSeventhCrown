@echo off
cd /d "%~dp0test"
echo ============================================
echo   ASCII CRPG - MVP Prototype
echo ============================================
echo.
echo Installing dependencies...
pip install -r requirements.txt -q 2>nul
echo.
echo Starting game...
python main.py
pause
