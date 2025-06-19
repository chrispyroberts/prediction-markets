@echo off
:loop
echo Starting Kalshi data collector...
python kalshi_data.py
if %ERRORLEVEL% EQU 0 (
    echo Collector exited normally
    exit /b 0
) else if %ERRORLEVEL% EQU 99 (
    echo Stale data detected - restarting in 15 seconds...
    timeout /t 15 /nobreak >nul
    goto loop
) else (
    echo Collector crashed with code %ERRORLEVEL% - restarting in 15 seconds...
    timeout /t 15 /nobreak >nul
    goto loop
)