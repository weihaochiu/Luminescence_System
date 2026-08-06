@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul

set "PYTHON_LAUNCHER="
where py.exe >nul 2>nul
if not errorlevel 1 set "PYTHON_LAUNCHER=py -3"

if not defined PYTHON_LAUNCHER (
    where python.exe >nul 2>nul
    if not errorlevel 1 set "PYTHON_LAUNCHER=python"
)

if not defined PYTHON_LAUNCHER (
    echo [錯誤] 找不到 Python。
    echo 請先安裝 64-bit Python 3.11 或 3.12，並勾選 Add Python to PATH。
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo 正在建立 Python 虛擬環境...
    %PYTHON_LAUNCHER% -m venv .venv
    if errorlevel 1 goto :failed
)

echo 正在確認 pip...
".venv\Scripts\python.exe" -m ensurepip --upgrade
if errorlevel 1 goto :failed

echo 正在安裝必要套件...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :failed

echo 正在啟動 EL 量測設備控制程式...
".venv\Scripts\python.exe" main.py
if errorlevel 1 goto :runtime_failed
exit /b 0

:failed
echo.
echo [錯誤] 安裝未完成，請保留此視窗中的訊息。
pause
exit /b 1

:runtime_failed
echo.
echo [錯誤] 程式執行失敗，請保留此視窗中的訊息。
pause
exit /b 1
