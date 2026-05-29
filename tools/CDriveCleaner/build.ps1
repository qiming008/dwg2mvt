$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$sourceFile = Join-Path $scriptDir "Program.cs"
$outputDir = Join-Path $scriptDir "dist"
$outputFile = Join-Path $outputDir "CDriveCleaner.exe"
$csc = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"

if (-not (Test-Path $csc)) {
    throw "未找到 C# 编译器: $csc"
}

if (-not (Test-Path $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir | Out-Null
}

& $csc /nologo /target:winexe /out:$outputFile /platform:anycpu /optimize+ /r:System.dll /r:System.Core.dll /r:System.Drawing.dll /r:System.Windows.Forms.dll $sourceFile

if ($LASTEXITCODE -ne 0) {
    throw "编译失败，退出码: $LASTEXITCODE"
}

Write-Host "Build completed: $outputFile"
