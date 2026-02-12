@echo off
set "TOOLS_DIR=%~dp0tools"
set "JAVA_HOME=%TOOLS_DIR%\java"
set "GEOSERVER_HOME=%TOOLS_DIR%"

echo ========================================
echo   Starting GeoServer...
echo ========================================
echo.

echo [1] Setting JAVA_HOME to portable Java...
echo   JAVA_HOME=%JAVA_HOME%
echo   GEOSERVER_HOME=%GEOSERVER_HOME%
echo.

if not exist "%JAVA_HOME%\bin\java.exe" (
    echo ERROR: Java not found at %JAVA_HOME%\bin\java.exe
    pause
    exit /b 1
)

echo [2] Launching GeoServer...
echo   Calling %GEOSERVER_HOME%\bin\startup.bat
echo.

call "%GEOSERVER_HOME%\bin\startup.bat"
