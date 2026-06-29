@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ================================================
echo   南理工课表管理 — 桌面应用构建工具
echo ================================================
echo.

:: ---- 找 Python ----
set "PY="
if exist "C:\Users\a\AppData\Local\Python\bin\python.exe" set "PY=C:\Users\a\AppData\Local\Python\bin\python.exe"
if "%PY%"=="" (py --version >nul 2>&1 && set "PY=py")
if "%PY%"=="" (python --version >nul 2>&1 && set "PY=python")

if "%PY%"=="" (
    echo [ERROR] Python 未找到，请先安装 Python 3.9+
    pause
    exit /b 1
)

echo Python: %PY%
echo.

:: ---- 检查/安装 PyInstaller ----
echo [1/4] 检查 PyInstaller...
%PY% -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo 正在安装 PyInstaller...
    %PY% -m pip install pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (
        %PY% -m pip install pyinstaller
    )
)
echo PyInstaller 已就绪
echo.

:: ---- 生成 ICO 图标 ----
echo [2/4] 生成应用图标...
set "ICO_FILE=static\app.ico"
if not exist "%ICO_FILE%" (
    %PY% -c "from PIL import Image; img=Image.open('static/icon-512.png'); img.save('static/app.ico', format='ICO', sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])"
    if errorlevel 1 (
        echo [警告] 图标转换失败（不影响构建），将使用默认图标
    ) else (
        echo 图标已生成: static\app.ico
    )
) else (
    echo 图标已存在: static\app.ico
)
echo.

:: ---- 清理旧构建 ----
echo [3/4] 清理旧构建...
if exist "build" rmdir /s /q "build"
if exist "dist\南理工课表管理" rmdir /s /q "dist\南理工课表管理"
echo 清理完成
echo.

:: ---- 开始构建 ----
echo [4/4] 开始构建（需要 3~10 分钟，首次更久）...
echo ================================================
echo.

%PY% -m PyInstaller njust_schedule.spec --clean --noconfirm

if errorlevel 1 (
    echo.
    echo ================================================
    echo   [失败] 构建出错，请检查上方日志
    echo ================================================
    pause
    exit /b 1
)

echo.
echo ================================================
echo   [成功] 构建完成！
echo ================================================
echo.
echo   位置: dist\南理工课表管理\南理工课表管理.exe
echo.
echo   可直接双击运行，或创建快捷方式
echo.

:: 计算大小
if exist "dist\南理工课表管理" (
    for /f "tokens=1,2" %%a in ('dir "dist\南理工课表管理" /s ^| find "个文件"') do (
        echo   大小: %%a
    )
)

:: ---- 可选：打开输出目录 ----
echo.
set /p "OPEN=是否打开输出目录? (y/n): "
if /i "%OPEN%"=="y" (
    explorer "dist\南理工课表管理"
)

pause
