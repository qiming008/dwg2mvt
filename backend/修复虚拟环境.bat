@echo off
chcp 65001 >nul
echo ========================================
echo   修复虚拟环境脚本
echo ========================================
echo.

if exist ".venv" (
    echo 发现损坏的虚拟环境，正在删除...
    rmdir /s /q .venv
    echo 已删除旧虚拟环境
)

echo 正在创建新的虚拟环境...
python -m venv .venv
if errorlevel 1 (
    echo [错误] 虚拟环境创建失败
    echo 请检查：
    echo 1. Python 是否正确安装（运行 python --version 测试）
    echo 2. 是否有足够的磁盘空间
    pause
    exit /b 1
)

echo.
echo 虚拟环境创建成功！
echo 现在可以运行 start.bat 启动服务
echo.
pause
