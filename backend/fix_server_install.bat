@echo off
chcp 65001
echo ==========================================
echo   LibreDWG 服务器安装修复工具
echo ==========================================
echo.
echo 正在检查虚拟环境...

if exist ".venv" (
    echo [警告] 发现旧的虚拟环境 (.venv)
    echo 这通常是因为直接复制了本地文件夹到服务器导致的路径不匹配。
    echo.
    echo 正在删除旧环境，请稍候...
    rmdir /s /q ".venv"
    if exist ".venv" (
        echo [错误] 无法删除 .venv 文件夹。请关闭所有相关窗口后重试，或手动删除。
        pause
        exit /b 1
    )
    echo 删除成功！
) else (
    echo 未发现旧环境，准备创建新环境...
)

echo.
echo ==========================================
echo   开始重新安装
echo ==========================================
echo.

call start.bat
