@echo off
REM Force ASCII output to avoid encoding issues
chcp 437 >nul

echo ========================================
echo   PRODUCTION MODE: Backend Service
echo ========================================
echo.

cd /d "%~dp0"

REM [1] Setting up PATH...
set "TOOLS_DIR=%~dp0tools"
REM Add tools root for dwg2dxf.exe
set "PATH=%TOOLS_DIR%;%PATH%"
REM Add GDAL paths
set "PATH=%TOOLS_DIR%\gdal\bin\gdal\apps;%TOOLS_DIR%\gdal\bin;%PATH%"
REM Set GDAL_DATA
set "GDAL_DATA=%TOOLS_DIR%\gdal\bin\gdal-data"
REM Set PROJ_LIB for proj.db (found in proj9/share)
set "PROJ_LIB=%TOOLS_DIR%\gdal\bin\proj9\share"
REM Add libredwg subfolder just in case
if exist "%TOOLS_DIR%\libredwg" set "PATH=%TOOLS_DIR%\libredwg;%PATH%"

echo [2] Activating venv...
if not exist ".venv" (
    echo [ERROR] Virtual environment not found!
    echo Please run 'start.bat' first to install dependencies and initialize the environment.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] Failed to activate venv!
    pause
    exit /b 1
)

echo [3] Starting Uvicorn (Production)...
echo Host: 0.0.0.0
echo Port: 8000
echo Workers: 4
echo.
echo Press Ctrl+C to stop.
echo.

REM --workers 4: Enable multi-process for production
REM --host 0.0.0.0: Listen on all network interfaces
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4

pause
