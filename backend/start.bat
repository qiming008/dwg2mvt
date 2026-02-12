@echo off
REM Force ASCII output to avoid encoding issues
chcp 437 >nul

echo ========================================
echo   DEBUG MODE: Backend Service Launcher
echo ========================================
echo.

echo [1] Checking directory...
cd /d "%~dp0"
echo Current directory: %CD%
echo.

echo [1.5] Setting up PATH...
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
echo PATH updated.
echo GDAL_DATA=%GDAL_DATA%
echo PROJ_LIB=%PROJ_LIB%
echo.

echo [2] Checking Python...
python --version
if errorlevel 1 (
    echo [ERROR] Python not found or not in PATH!
    echo Please install Python 3.11+ and check "Add to PATH"
    goto :ERROR
)
echo.

echo [3] Checking venv...
if not exist ".venv" (
    echo Virtual environment not found. Creating...
    python -m venv .venv
    if errorlevel 1 goto :ERROR
)

echo [4] Activating venv...
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] Failed to activate venv!
    goto :ERROR
)
echo Venv activated.
echo.

echo [5] Installing dependencies...
echo (This might take a while...)
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Dependency installation failed!
    goto :ERROR
)
echo Dependencies OK.
echo.

echo [6] Starting Uvicorn...
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

echo.
echo Service stopped normally.
pause
exit /b 0

:ERROR
echo.
echo ========================================
echo   CRITICAL ERROR OCCURRED
echo ========================================
echo.
pause
exit /b 1
