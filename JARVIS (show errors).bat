@echo off
REM Same as JARVIS.bat, but keeps a console window open so you can read any
REM error message. Use this one if JARVIS.bat appears to do nothing.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo   JARVIS is not set up yet. Run setup.ps1 first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m jarvis
echo.
echo   JARVIS exited with code %ERRORLEVEL%.
pause
