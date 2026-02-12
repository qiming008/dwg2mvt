<#
.SYNOPSIS
Auto download and configure GeoServer + Java for Windows

.DESCRIPTION
Downloads OpenJDK 17 and GeoServer, extracts them to tools directory.
#>

$ErrorActionPreference = "Stop"
$toolsDir = Join-Path $PSScriptRoot "tools"
$javaDir = Join-Path $toolsDir "java"
$geoserverDir = Join-Path $toolsDir "geoserver"

# URLs
$jdkUrl = "https://aka.ms/download-jdk/microsoft-jdk-17-windows-x64.zip"
# Using a specific mirror or direct link for GeoServer can be tricky. 
# Using SourceForge latest 2.26.x link.
$geoserverUrl = "https://sourceforge.net/projects/geoserver/files/GeoServer/2.26.2/geoserver-2.26.2-bin.zip/download"

# 1. Create tools directory
if (-not (Test-Path $toolsDir)) {
    New-Item -ItemType Directory -Path $toolsDir | Out-Null
}

# 2. Setup Java
if (-not (Test-Path $javaDir)) {
    Write-Host "Downloading OpenJDK 17..." -ForegroundColor Cyan
    $jdkZip = Join-Path $toolsDir "jdk.zip"
    Invoke-WebRequest -Uri $jdkUrl -OutFile $jdkZip
    
    Write-Host "Extracting Java..." -ForegroundColor Cyan
    Expand-Archive -Path $jdkZip -DestinationPath $toolsDir -Force
    
    # Rename extracted folder (usually jdk-17...) to java
    $extractedJdk = Get-ChildItem -Path $toolsDir -Directory | Where-Object { $_.Name -like "jdk-17*" } | Select-Object -First 1
    if ($extractedJdk) {
        Rename-Item -Path $extractedJdk.FullName -NewName "java"
    }
    Remove-Item $jdkZip
    Write-Host "Java installed." -ForegroundColor Green
} else {
    Write-Host "Java already exists." -ForegroundColor Yellow
}

# 3. Setup GeoServer
if (-not (Test-Path $geoserverDir)) {
    Write-Host "Downloading GeoServer 2.26.2..." -ForegroundColor Cyan
    $gsZip = Join-Path $toolsDir "geoserver.zip"
    
    # SourceForge requires a User-Agent sometimes, or follows redirects
    try {
        Invoke-WebRequest -Uri $geoserverUrl -OutFile $gsZip -UserAgent "PowerShell" -MaximumRedirection 5
    } catch {
        Write-Error "Download failed: $_"
        exit 1
    }
    
    Write-Host "Extracting GeoServer..." -ForegroundColor Cyan
    Expand-Archive -Path $gsZip -DestinationPath $toolsDir -Force
    
    # Rename extracted folder (usually geoserver-2.26.2-bin) to geoserver
    $extractedGs = Get-ChildItem -Path $toolsDir -Directory | Where-Object { $_.Name -like "geoserver-*" } | Select-Object -First 1
    if ($extractedGs) {
        Rename-Item -Path $extractedGs.FullName -NewName "geoserver"
    }
    Remove-Item $gsZip
    Write-Host "GeoServer installed." -ForegroundColor Green
} else {
    Write-Host "GeoServer already exists." -ForegroundColor Yellow
}

Write-Host "Setup finished." -ForegroundColor Green
