@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul

if not exist ".venv\Scripts\python.exe" (
    call setup_and_run.bat
    exit /b %errorlevel%
)

".venv\Scripts\python.exe" main.py
if errorlevel 1 (
    echo.
    echo [錯誤] 程式執行失敗，請保留此視窗中的訊息。
    pause
)
