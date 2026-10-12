@echo off
setlocal
cd /d "%~dp0..\.."
if not exist ".venv\Scripts\python.exe" goto no_venv
".venv\Scripts\python.exe" -m standalone.hdr_viewer.main
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" pause
exit /b %EXIT_CODE%
:no_venv
echo ERROR: Project Python virtual environment was not found. Run setup_and_run.bat first.
pause
exit /b 1
