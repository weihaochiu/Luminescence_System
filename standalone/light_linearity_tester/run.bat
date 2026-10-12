@echo off
setlocal
cd /d "%~dp0..\.."
if not exist ".venv\Scripts\python.exe" goto no_venv
".venv\Scripts\python.exe" -m standalone.light_linearity_tester.main
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" goto failed
exit /b 0
:no_venv
echo ERROR: Project Python virtual environment was not found. Run setup_and_run.bat first.
pause
exit /b 1
:failed
echo ERROR: Light Linearity Tester failed. Exit code: %EXIT_CODE%
pause
exit /b %EXIT_CODE%
