@echo off
setlocal
call "%~dp0standalone\light_linearity_tester\run.bat"
exit /b %ERRORLEVEL%
