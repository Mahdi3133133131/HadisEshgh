@echo off
REM ===========================================================
REM   Hadis-e Eshgh - install prerequisites
REM   Double-click this file.
REM ===========================================================
chcp 65001 >nul 2>&1
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set RC=%ERRORLEVEL%

echo.
if not "%RC%"=="0" (
  echo [!] Setup did not finish. See the messages above.
)
pause
exit /b %RC%
