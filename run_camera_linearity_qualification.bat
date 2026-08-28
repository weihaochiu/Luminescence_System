@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" goto no_venv

".venv\Scripts\python.exe" -m tools.camera_linearity_qualification.main
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" goto failed
exit /b 0

:no_venv
echo ERROR: Python virtual environment was not found.
echo Run setup_and_run.bat first.
pause
exit /b 1

:failed
echo.
echo ERROR: Camera Linearity Qualification failed.
echo Exit code: %EXIT_CODE%
pause
exit /b %EXIT_CODE%
