@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ==========================================
echo   NJUST Schedule Manager - Setup
echo ==========================================
echo.

:: Find Python
set "PY="
if exist "C:\Users\a\AppData\Local\Python\bin\python.exe" set "PY=C:\Users\a\AppData\Local\Python\bin\python.exe"
if "%PY%"=="" (py --version >nul 2>&1 && set "PY=py")
if "%PY%"=="" (python --version >nul 2>&1 && set "PY=python")

if "%PY%"=="" (
    echo [ERROR] Python not found!
    echo.
    echo Please install Python 3.9+ from:
    echo   https://www.python.org/downloads/
    echo.
    echo Make sure to check "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)

echo Python found: %PY%
echo.

:: Check pip
%PY% -m pip --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] pip not available. Please reinstall Python.
    pause
    exit /b 1
)

echo Installing dependencies...
echo.
%PY% -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo Retry with default mirror...
    %PY% -m pip install -r requirements.txt
)

echo.
echo ==========================================
echo   Setup complete! Double-click run.bat
echo ==========================================
echo.
pause
