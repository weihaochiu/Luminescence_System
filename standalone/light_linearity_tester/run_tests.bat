@echo off
setlocal
cd /d "%~dp0..\.."
if not exist ".venv\Scripts\python.exe" goto no_venv
".venv\Scripts\python.exe" -m unittest discover -s tests -p "test_light_linearity*.py" -v
set "EXIT_CODE=%ERRORLEVEL%"
pause
exit /b %EXIT_CODE%
:no_venv
echo ERROR: Project Python virtual environment was not found.
pause
exit /b 1
