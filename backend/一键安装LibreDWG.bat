@echo off
echo ========================================
echo   Running LibreDWG Auto-Installer...
echo ========================================
echo.

cd /d "%~dp0"

REM Run PowerShell script with Bypass policy
powershell -NoProfile -ExecutionPolicy Bypass -File "setup_libredwg.ps1"

echo.
echo ========================================
if errorlevel 1 (
    echo [ERROR] Script failed. Please check messages above.
) else (
    echo [SUCCESS] Script finished.
)
echo ========================================
echo.
echo Press any key to exit...
pause >nul
