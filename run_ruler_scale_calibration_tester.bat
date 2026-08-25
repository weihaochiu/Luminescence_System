@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul

if not exist ".venv\Scripts\python.exe" (
    echo 找不到 Luminescence_System 虛擬環境。
    echo 請先執行 setup_and_run.bat 完成環境建立。
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m tools.ruler_scale_calibration_tester.main
set "RULER_TESTER_EXIT_CODE=%ERRORLEVEL%"
if not "%RULER_TESTER_EXIT_CODE%"=="0" (
    echo.
    echo Ruler Scale Calibration Tester 執行失敗，exit code: %RULER_TESTER_EXIT_CODE%
    pause
    exit /b %RULER_TESTER_EXIT_CODE%
)

exit /b 0
