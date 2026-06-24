@echo off
cd /d "%~dp0"

:: Find Python, prefer pythonw (no console)
set "PY="
if exist "C:\Users\a\AppData\Local\Python\bin\pythonw.exe" set "PY=C:\Users\a\AppData\Local\Python\bin\pythonw.exe"
if "%PY%"=="" (py --version >nul 2>&1 && set "PY=pythonw")
if "%PY%"=="" (python --version >nul 2>&1 && set "PY=pythonw")

if "%PY%"=="" (
    echo Python not found. Please run setup.bat first.
    pause
    exit /b 1
)

:: Launch without keeping CMD window open
start "" "%PY%" "%~dp0main.py"
