@echo off
REM ===========================================================
REM   Hadis-e Eshgh - start the bot
REM ===========================================================
chcp 65001 >nul 2>&1
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [!] .venv not found. Run install.bat first.
  pause
  exit /b 1
)

set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
".venv\Scripts\python.exe" main.py
set RC=%ERRORLEVEL%

echo.
echo Bot stopped ^(exit code %RC%^).
pause
exit /b %RC%
