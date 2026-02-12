<#
.SYNOPSIS
Auto download and configure LibreDWG for Windows

.DESCRIPTION
Downloads the latest LibreDWG Windows build from GitHub, extracts it to tools directory,
and configures .env file.
#>

$ErrorActionPreference = "Stop"
$toolsDir = Join-Path $PSScriptRoot "tools"
$libredwgDir = Join-Path $toolsDir "libredwg"

# 1. Create directory
if (-not (Test-Path $toolsDir)) {
    New-Item -ItemType Directory -Path $toolsDir | Out-Null
}

Write-Host "Fetching latest LibreDWG version info..." -ForegroundColor Cyan

# 2. Get latest Release download link
try {
    # GitHub API to get latest release
    $response = Invoke-RestMethod -Uri "https://api.github.com/repos/LibreDWG/libredwg/releases" -Method Get
    # Find asset with win64
    $downloadUrl = $null
    $tagName = $null

    foreach ($release in $response) {
        foreach ($asset in $release.assets) {
            if ($asset.name -like "*win64.zip") {
                $downloadUrl = $asset.browser_download_url
                $tagName = $release.tag_name
                break
            }
        }
        if ($downloadUrl) { break }
    }

    if (-not $downloadUrl) {
        throw "LibreDWG Windows 64-bit download link not found"
    }

    Write-Host "Found version: $tagName"
    Write-Host "Download URL: $downloadUrl"

} catch {
    Write-Error "Failed to get version: $_"
    Write-Warning "Please manually download LibreDWG win64.zip and extract to: $libredwgDir"
    exit 1
}

# 3. Download
$zipFile = Join-Path $toolsDir "libredwg.zip"
if (-not (Test-Path $libredwgDir)) {
    Write-Host "Downloading LibreDWG..." -ForegroundColor Cyan
    Invoke-WebRequest -Uri $downloadUrl -OutFile $zipFile
    
    Write-Host "Extracting..." -ForegroundColor Cyan
    Expand-Archive -Path $zipFile -DestinationPath $toolsDir -Force
    
    # Rename extracted folder (usually with version number) to libredwg
    $extractedDir = Get-ChildItem -Path $toolsDir -Directory | Where-Object { $_.Name -like "libredwg-*" } | Select-Object -First 1
    if ($extractedDir) {
        Rename-Item -Path $extractedDir.FullName -NewName "libredwg"
    }
    
    Remove-Item $zipFile
    Write-Host "LibreDWG installation completed" -ForegroundColor Green
} else {
    Write-Host "LibreDWG directory already exists, skipping download" -ForegroundColor Yellow
}

# 4. Configure .env
$envFile = Join-Path $PSScriptRoot ".env"
$envExample = Join-Path $PSScriptRoot ".env.example"
$dwg2dxfPath = Join-Path $libredwgDir "dwg2dxf.exe"

if (-not (Test-Path $dwg2dxfPath)) {
    Write-Warning "dwg2dxf.exe not found in expected location, please check $libredwgDir"
} else {
    if (-not (Test-Path $envFile)) {
        Copy-Item $envExample $envFile
    }
    
    # Read .env content
    $envContent = Get-Content $envFile
    $newEnvContent = @()
    $updated = $false
    
    foreach ($line in $envContent) {
        if ($line -match "^APP_DWG2DXF_CMD=") {
            $newEnvContent += "APP_DWG2DXF_CMD=$dwg2dxfPath"
            $updated = $true
        } else {
            $newEnvContent += $line
        }
    }
    
    if (-not $updated) {
        $newEnvContent += "APP_DWG2DXF_CMD=$dwg2dxfPath"
    }
    
    $newEnvContent | Set-Content $envFile
    Write-Host "Updated .env configuration file" -ForegroundColor Green
}

Write-Host "`nTip: GDAL (ogr2ogr) is complex, suggest using OSGeo4W or downloading GISInternals package." -ForegroundColor Cyan
