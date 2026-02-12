@echo off
chcp 65001 >nul
echo ========================================
echo   DWG 转切片 - 前端启动脚本
echo ========================================
echo.

REM 检查 Node.js 是否安装
node --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Node.js，请先安装 Node.js 18+
    echo 下载地址: https://nodejs.org/
    pause
    exit /b 1
)

echo [1/2] 检查依赖...
if not exist "node_modules" (
    echo 首次运行，正在安装依赖（可能需要几分钟）...
    call npm install
    if errorlevel 1 (
        echo [错误] 依赖安装失败
        pause
        exit /b 1
    )
) else (
    echo 依赖已安装
)

echo [2/2] 启动前端开发服务器...
echo.
echo ========================================
echo   前端地址: http://localhost:5173
echo   请确保后端已启动: http://localhost:8000
echo   按 Ctrl+C 停止
echo ========================================
echo.

call npm run dev

pause
