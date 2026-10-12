@echo off
setlocal
cd /d "%~dp0"

if exist "..\..\.venv\Scripts\python.exe" (
    "..\..\.venv\Scripts\python.exe" main.py
    goto result
)
py -3 main.py

:result
set "EXIT_CODE=%ERRORLEVEL%"
if "%EXIT_CODE%"=="0" exit /b 0
echo.
echo GSP-4H standalone controller could not start or exited with an error.
echo Install Python and the dependencies listed in this folder's requirements.txt.
echo Example: py -3 -m pip install -r requirements.txt
echo Exit code: %EXIT_CODE%
pause
exit /b %EXIT_CODE%
