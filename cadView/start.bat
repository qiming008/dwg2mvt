@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

echo ========================================
echo   cadView Microapp Dev Launcher
echo ========================================
echo.

cd /d "%~dp0"

rem Check Node.js
node --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js was not found. Please install Node.js 18+ first.
    echo Download: https://nodejs.org/
    pause
    exit /b 1
)

node -e "const m=Number(process.versions.node.split('.')[0]); process.exit(m>=18?0:1)" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js 18+ is required. Current version is:
    node --version
    echo Please install Node.js 18 or newer, then rerun this launcher.
    pause
    exit /b 1
)

echo [1/3] Checking frontend dependencies...
if not exist "node_modules" (
    echo node_modules not found. Installing dependencies...
    call npm install
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed.
        pause
        exit /b 1
    )
) else (
    echo Dependencies already installed.
)

echo [2/3] Starting frontend dev server...
echo.
echo ========================================
echo   cadView:   http://localhost:3666
echo   Backend:   http://localhost:8088
echo   GeoServer: http://localhost:19080
echo   Press Ctrl+C to stop
echo ========================================
echo.

call npm run dev

pause
exit /b 0
