@echo off
REM Double-click this to start JARVIS.
REM pythonw.exe runs it with no console window - just the dashboard.
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo.
    echo   JARVIS is not set up yet.
    echo.
    echo   Right-click setup.ps1 and choose "Run with PowerShell".
    echo.
    pause
    exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" -m jarvis
