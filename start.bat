@echo off
setlocal
title MovieMate
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"
set "result=%errorlevel%"
if not "%result%"=="0" (
    echo.
    echo MovieMate could not start. See the error above.
    pause
)
exit /b %result%
