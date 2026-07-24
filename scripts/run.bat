@echo off
cd /d "%~dp0.."

:: Find Python, prefer pythonw (no console)
set "PY="
for %%p in (py python) do (
    if "%PY%"=="" (%%p --version >nul 2>&1 && set "PY=%%pw")
)

if "%PY%"=="" (
    echo Python not found. Please run setup.bat first.
    pause
    exit /b 1
)

:: Launch without keeping CMD window open
start "" "%PY%" "%~dp0..\main.py"
