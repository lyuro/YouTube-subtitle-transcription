# YouTube Video Transcription Tool - Setup Script

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

if (Test-Path (Join-Path $ScriptDir ".git")) {
    try {
        git config core.hooksPath .githooks | Out-Null
        Write-Host "[*] Git hooks path set to .githooks" -ForegroundColor Gray
        Write-Host ""
    } catch {
        Write-Host "[!] Could not configure git hooks path automatically" -ForegroundColor Yellow
        Write-Host ""
    }
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  YouTube Transcription Tool - Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check Python
Write-Host "[1/6] Checking Python..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    Write-Host "  [OK] $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "  [X] Python not found, please install Python 3.10+" -ForegroundColor Red
    exit 1
}

# Check FFmpeg
Write-Host "[2/6] Checking FFmpeg..." -ForegroundColor Yellow
$ffmpegPath = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($ffmpegPath) {
    Write-Host "  [OK] FFmpeg installed: $($ffmpegPath.Source)" -ForegroundColor Green
} else {
    Write-Host "  [!] FFmpeg not found, trying to install..." -ForegroundColor Yellow
    try {
        winget install FFmpeg --accept-source-agreements --accept-package-agreements
        Write-Host "  [OK] FFmpeg installed" -ForegroundColor Green
        Write-Host "  [!] Please restart terminal for FFmpeg to take effect" -ForegroundColor Yellow
    } catch {
        Write-Host "  [X] FFmpeg install failed, please run: winget install FFmpeg" -ForegroundColor Red
    }
}

# Check CUDA
Write-Host "[3/6] Checking NVIDIA GPU..." -ForegroundColor Yellow
$nvidiaSmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($nvidiaSmi) {
    $gpuInfo = nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>&1
    Write-Host "  [OK] GPU: $gpuInfo" -ForegroundColor Green
} else {
    Write-Host "  [!] No NVIDIA GPU detected, will use CPU mode" -ForegroundColor Yellow
}

# Create venv
$VenvPath = Join-Path $ScriptDir ".venv"
Write-Host "[4/6] Setting up virtual environment..." -ForegroundColor Yellow

if (Test-Path $VenvPath) {
    Write-Host "  [OK] Venv exists: $VenvPath" -ForegroundColor Green
} else {
    Write-Host "  [*] Creating venv..." -ForegroundColor Cyan
    python -m venv $VenvPath
    Write-Host "  [OK] Venv created" -ForegroundColor Green
}

# Activate venv (for shell convenience; package operations below use $VenvPython directly)
$ActivateScript = Join-Path $VenvPath "Scripts\Activate.ps1"
. $ActivateScript
Write-Host "  [OK] Venv activated" -ForegroundColor Green

# 显式使用 venv 内的 python，避免 Activate.ps1 失败时误装到系统环境
$VenvPython = Join-Path $VenvPath "Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "  [X] Venv python not found at $VenvPython" -ForegroundColor Red
    exit 1
}

# Install dependencies
Write-Host "[5/6] Installing Python packages..." -ForegroundColor Yellow

# Check PyTorch
$torchOK = $false
try {
    $result = & $VenvPython -c "import torch; print(torch.cuda.is_available())" 2>&1
    if ($result -match "True") {
        $torchOK = $true
    }
} catch {}

if ($torchOK) {
    Write-Host "  [OK] PyTorch CUDA installed" -ForegroundColor Green
} else {
    Write-Host "  [*] Installing PyTorch CUDA 12.1..." -ForegroundColor Cyan
    & $VenvPython -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
    Write-Host "  [OK] PyTorch installed" -ForegroundColor Green
}

# Check yt-dlp
$ytdlpOK = $false
try {
    & $VenvPython -c "import yt_dlp" 2>$null
    if ($LASTEXITCODE -eq 0) { $ytdlpOK = $true }
} catch {}

if ($ytdlpOK) {
    Write-Host "  [OK] yt-dlp installed" -ForegroundColor Green
} else {
    Write-Host "  [*] Installing yt-dlp (default extras)..." -ForegroundColor Cyan
    & $VenvPython -m pip install "yt-dlp[default]"
    Write-Host "  [OK] yt-dlp installed" -ForegroundColor Green
}

# Check faster-whisper
$whisperOK = $false
try {
    & $VenvPython -c "import faster_whisper" 2>$null
    if ($LASTEXITCODE -eq 0) { $whisperOK = $true }
} catch {}

if ($whisperOK) {
    Write-Host "  [OK] faster-whisper installed" -ForegroundColor Green
} else {
    Write-Host "  [*] Installing faster-whisper..." -ForegroundColor Cyan
    & $VenvPython -m pip install faster-whisper
    Write-Host "  [OK] faster-whisper installed" -ForegroundColor Green
}

# 卸载残留的 openai-whisper（如果存在），避免引发歧义
& $VenvPython -m pip show openai-whisper > $null 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "  [*] Removing legacy openai-whisper..." -ForegroundColor Cyan
    & $VenvPython -m pip uninstall -y openai-whisper | Out-Null
}

# Verify
Write-Host "[6/6] Verifying environment..." -ForegroundColor Yellow
try {
    $cudaResult = & $VenvPython -c "import torch; print(torch.cuda.is_available())" 2>&1
    if ($cudaResult -match "True") {
        $cudaDevice = & $VenvPython -c "import torch; print(torch.cuda.get_device_name(0))"
        Write-Host "  [OK] CUDA available: $cudaDevice" -ForegroundColor Green
    } else {
        Write-Host "  [!] CUDA not available, will use CPU mode" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  [!] Could not verify CUDA" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Setup Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Usage:" -ForegroundColor White
Write-Host "  1. Double-click run.bat to start" -ForegroundColor Gray
Write-Host "  2. Or run: .\run.ps1 YouTubeURL" -ForegroundColor Gray
Write-Host ""
