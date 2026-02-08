# YouTube Video Transcription Tool - Run Script
# Usage: .\run.ps1 "YouTubeURL"
# Or run directly for interactive mode: .\run.ps1

param(
    [Parameter(Position=0)]
    [string]$Url,
    
    [string]$Model = "large-v3",
    [string]$Language = "",
    [string]$OutputDir = ".",
    [ValidateSet("txt", "srt", "both")]
    [string]$Format = "both",
    [switch]$KeepAudio,
    [string]$Cookies = "",
    [string]$CookiesFromBrowser = "",
    [string]$JsRuntimes = "",
    [string]$RemoteComponents = ""
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$VenvPath = Join-Path $ScriptDir ".venv"
$ActivateScript = Join-Path $VenvPath "Scripts\Activate.ps1"

# Check if venv exists
if (-not (Test-Path $VenvPath)) {
    Write-Host "[X] Virtual environment not found, please run setup.ps1 first" -ForegroundColor Red
    Write-Host "    Run: .\setup.ps1" -ForegroundColor Yellow
    exit 1
}

# Activate venv
. $ActivateScript

# Interactive mode if no URL provided
if ([string]::IsNullOrEmpty($Url)) {
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  YouTube Video Transcription Tool" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Enter one or more YouTube URLs." -ForegroundColor Gray
    Write-Host "Use | or separate lines. Press Enter on an empty line to start." -ForegroundColor Gray
    $lines = @()
    $queuedCount = 0
    while ($true) {
        $line = Read-Host "URL"
        if ([string]::IsNullOrWhiteSpace($line)) {
            break
        }
        $lines += $line
        $lineUrls = $line -split "\|" | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" }
        $queuedCount += $lineUrls.Count
        Write-Host "Queued URLs: $queuedCount" -ForegroundColor Gray
    }
    if ($lines.Count -eq 0) {
        Write-Host "[X] No URL provided, exiting" -ForegroundColor Red
        exit 1
    }
    $Url = ($lines -join "`n")
}

# Split URLs by newline or pipe
$UrlList = $Url -split "(?:\r?\n|\|)" | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" }
if ($UrlList.Count -eq 0) {
    Write-Host "[X] No valid URL provided, exiting" -ForegroundColor Red
    exit 1
}

# Build base arguments
$baseArgs = @()

$baseArgs += "--model"
$baseArgs += $Model

$baseArgs += "--output"
$baseArgs += $Format

if (-not [string]::IsNullOrEmpty($Language)) {
    $baseArgs += "--language"
    $baseArgs += $Language
}

if ($OutputDir -ne ".") {
    $baseArgs += "--output-dir"
    $baseArgs += $OutputDir
}

if ($KeepAudio) {
    $baseArgs += "--keep-audio"
}

if (-not [string]::IsNullOrEmpty($Cookies)) {
    $baseArgs += "--cookies"
    $baseArgs += $Cookies
}

if (-not [string]::IsNullOrEmpty($CookiesFromBrowser)) {
    $baseArgs += "--cookies-from-browser"
    $baseArgs += $CookiesFromBrowser
}

if (-not [string]::IsNullOrEmpty($JsRuntimes)) {
    $baseArgs += "--js-runtimes"
    $baseArgs += $JsRuntimes
}

if (-not [string]::IsNullOrEmpty($RemoteComponents)) {
    $baseArgs += "--remote-components"
    $baseArgs += $RemoteComponents
}

# Run transcription queue
Write-Host ""
Write-Host "[*] Starting transcription queue..." -ForegroundColor Green
Write-Host "    Model: $Model | Format: $Format | Count: $($UrlList.Count)" -ForegroundColor Gray
$hadError = $false
foreach ($item in $UrlList) {
    Write-Host ""
    Write-Host "[*] Processing: $item" -ForegroundColor Green
    $pyArgs = @($item) + $baseArgs
    python transcribe.py @pyArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[X] Failed: $item" -ForegroundColor Red
        $hadError = $true
    }
}
if ($hadError) {
    exit 1
}
