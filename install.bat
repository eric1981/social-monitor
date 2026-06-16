@echo off
chcp 65001 >nul
echo.
echo   ╔══════════════════════════════════════════╗
echo   ║       📡 Social Monitor Installer       ║
echo   ╚══════════════════════════════════════════╝
echo.
echo   检测到系统: Windows
echo   项目目录: %~dp0
echo.

cd /d "%~dp0"

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   ❌ 未找到 Python，请先安装 Python 3.9+
    echo      下载: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo   ✓ Python 已检测到

:: Run installer
python install.py --quick %*
if %errorlevel% neq 0 (
    pause
    exit /b 1
)

echo.
echo   安装完成！启动服务：
echo     python server.py
echo.
echo   浏览器打开: http://localhost:5408
pause
