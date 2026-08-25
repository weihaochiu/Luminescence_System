@echo off
setlocal EnableExtensions
cd /d "%~dp0\..\.."
chcp 65001 >nul

if not exist ".venv\Scripts\python.exe" (
    echo [錯誤] 找不到 repository virtual environment: .venv\Scripts\python.exe
    echo 請先執行 repository 的 setup_and_run.bat 建立環境；本工具不會自動安裝套件。
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m tools.ruler_scale_calibration_tester.main
if errorlevel 1 (
    echo.
    echo [錯誤] Ruler Scale Calibration Tester 執行失敗，請保留此視窗中的訊息。
    pause
)
