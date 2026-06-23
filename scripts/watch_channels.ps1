param(
    [string]$ConfigPath = "",
    [string]$OutputRoot = "",
    [string]$RunScript = "",
    [string]$YtDlpPath = "",
    [string]$YtDlpPython = "",
    [string]$Model = "large-v3",
    [string]$Language = "zh",
    [ValidateSet("txt", "srt", "both")]
    [string]$Format = "both",
    [int]$LookbackHours = 36,
    [int]$PlaylistEnd = 12,
    [int]$MaxNewPerRun = 8,
    [string]$Cookies = "",
    [string]$CookiesFromBrowser = "",
    [switch]$IncludeStreams,
    [switch]$DiscoverOnly,
    [ValidateSet("none", "rclone")]
    [string]$UploadMode = "none",
    [string]$DriveRemote = "gdrive",
    [string]$DrivePath = "YouTubeTranscripts"
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir

if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Join-Path $ScriptDir "channels.json"
}
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $RepoRoot "output\channel-watch"
}
if ([string]::IsNullOrWhiteSpace($RunScript)) {
    $RunScript = Join-Path $RepoRoot "run.ps1"
}

$TranscriptRoot = Join-Path $OutputRoot "transcripts"
$LogRoot = Join-Path $OutputRoot "logs"
$ProcessedPath = Join-Path $OutputRoot "processed.txt"
$RunLogPath = Join-Path $OutputRoot "runs.jsonl"
New-Item -ItemType Directory -Force -Path $OutputRoot, $TranscriptRoot, $LogRoot | Out-Null

function Get-SafePathName {
    param([string]$Value)
    $invalid = [IO.Path]::GetInvalidFileNameChars()
    $safe = (-join ($Value.ToCharArray() | ForEach-Object {
        if ($invalid -contains $_) { "_" } else { $_ }
    })).Trim()
    if ([string]::IsNullOrWhiteSpace($safe)) {
        return "unnamed"
    }
    return $safe
}

function Write-RunRecord {
    param([object]$Record)
    ($Record | ConvertTo-Json -Depth 8 -Compress) | Add-Content -LiteralPath $RunLogPath -Encoding utf8
}

function Test-CommandVersion {
    param([object]$Command)
    try {
        $oldPythonPath = $env:PYTHONPATH
        if ($Command.PythonPath) {
            $env:PYTHONPATH = $Command.PythonPath
        }
        $args = @()
        if ($Command.Module) {
            $args += @("-m", $Command.Module)
        }
        $args += "--version"
        $output = & $Command.Executable @args 2>$null
        return ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($output))
    } catch {
        return $false
    } finally {
        $env:PYTHONPATH = $oldPythonPath
    }
}

function Resolve-YtDlpCommand {
    $commands = @()

    if (-not [string]::IsNullOrWhiteSpace($YtDlpPath)) {
        $commands += [pscustomobject]@{ Executable = $YtDlpPath; Module = ""; PythonPath = "" }
    }

    $repoYtDlp = Join-Path $RepoRoot ".venv\Scripts\yt-dlp.exe"
    if (Test-Path -LiteralPath $repoYtDlp) {
        $commands += [pscustomobject]@{ Executable = $repoYtDlp; Module = ""; PythonPath = "" }
    }

    $pathYtDlp = Get-Command "yt-dlp" -ErrorAction SilentlyContinue
    if ($pathYtDlp) {
        $commands += [pscustomobject]@{ Executable = $pathYtDlp.Source; Module = ""; PythonPath = "" }
    }

    $sitePackages = Join-Path $RepoRoot ".venv\Lib\site-packages"
    if (Test-Path -LiteralPath (Join-Path $sitePackages "yt_dlp")) {
        if (-not [string]::IsNullOrWhiteSpace($YtDlpPython)) {
            $commands += [pscustomobject]@{ Executable = $YtDlpPython; Module = "yt_dlp"; PythonPath = $sitePackages }
        }

        $codexPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
        if (Test-Path -LiteralPath $codexPython) {
            $commands += [pscustomobject]@{ Executable = $codexPython; Module = "yt_dlp"; PythonPath = $sitePackages }
        }

        $pathPython = Get-Command "python" -ErrorAction SilentlyContinue
        if ($pathPython) {
            $commands += [pscustomobject]@{ Executable = $pathPython.Source; Module = "yt_dlp"; PythonPath = $sitePackages }
        }
    }

    foreach ($command in $commands) {
        if (Test-CommandVersion -Command $command) {
            return $command
        }
    }

    throw "Could not run yt-dlp. Rebuild .venv with setup.ps1, install yt-dlp, or pass -YtDlpPath / -YtDlpPython."
}

function Invoke-YtDlpPrint {
    param(
        [object]$Command,
        [string]$Url,
        [int]$Limit
    )

    $oldPythonPath = $env:PYTHONPATH
    if ($Command.PythonPath) {
        $env:PYTHONPATH = $Command.PythonPath
    }

    try {
        $tab = [char]9
        $printFormat = "%(id)s${tab}%(timestamp)s${tab}%(upload_date)s${tab}%(duration_string)s${tab}%(live_status)s${tab}%(playlist_channel)s${tab}%(playlist_channel_id)s${tab}%(title)s"
        $args = @()
        if ($Command.Module) {
            $args += @("-m", $Command.Module)
        }
        $args += @("--skip-download", "--print", $printFormat, "--playlist-end", "$Limit", "--no-warnings", $Url)
        $lines = & $Command.Executable @args 2>&1
        $dataLines = @($lines | Where-Object { $_ -match "^[A-Za-z0-9_-]{11}`t" })
        if ($LASTEXITCODE -ne 0) {
            $errors = @($lines | Where-Object { $_ -match "^(ERROR|WARNING):" } | Select-Object -First 3)
            if ($dataLines.Count -gt 0) {
                Write-Warning "yt-dlp partially failed for $Url; keeping $($dataLines.Count) public rows. $($errors -join ' ')"
                return $dataLines
            }
            throw "yt-dlp failed for $Url. $($errors -join ' ')"
        }
        return $dataLines
    } finally {
        $env:PYTHONPATH = $oldPythonPath
    }
}

function Get-ChannelItems {
    param(
        [object]$YtDlpCommand,
        [string]$Handle,
        [string]$Source,
        [int]$Limit
    )

    $url = "https://www.youtube.com/@$Handle/$Source"
    $lines = Invoke-YtDlpPrint -Command $YtDlpCommand -Url $url -Limit $Limit
    $items = @()

    foreach ($line in $lines) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }
        $parts = $line -split "`t", 8
        if ($parts.Count -lt 8 -or [string]::IsNullOrWhiteSpace($parts[0]) -or $parts[0] -eq "NA") {
            continue
        }
        if ($parts[4] -in @("is_live", "is_upcoming")) {
            continue
        }

        $published = $null
        if ($parts[1] -match "^\d+$") {
            $published = [DateTimeOffset]::FromUnixTimeSeconds([int64]$parts[1]).LocalDateTime
        }
        if (-not $published -and $parts[2] -match "^\d{8}$") {
            $published = [datetime]::ParseExact($parts[2], "yyyyMMdd", $null)
        }
        if (-not $published) {
            $published = Get-Date
        }

        $items += [pscustomobject]@{
            Id = [string]$parts[0]
            Url = "https://www.youtube.com/watch?v=$($parts[0])"
            Title = [string]$parts[7]
            Source = $Source
            PublishedAt = $published
            Duration = [string]$parts[3]
            Channel = if ($parts[5] -eq "NA") { "" } else { [string]$parts[5] }
            ChannelId = if ($parts[6] -eq "NA") { "" } else { [string]$parts[6] }
            Handle = $Handle
        }
    }

    return $items
}

function Invoke-Transcription {
    param(
        [object]$Item,
        [string]$OutDir,
        [string]$LogPath
    )

    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
    $args = @{
        Url = $Item.Url
        Model = $Model
        Language = $Language
        Format = $Format
        OutputDir = $OutDir
    }
    if (-not [string]::IsNullOrWhiteSpace($Cookies)) {
        $args.Cookies = $Cookies
    }
    if (-not [string]::IsNullOrWhiteSpace($CookiesFromBrowser)) {
        $args.CookiesFromBrowser = $CookiesFromBrowser
    }

    "[$(Get-Date -Format o)] $($Item.Url) $($Item.Title)" | Set-Content -LiteralPath $LogPath -Encoding utf8
    & $RunScript @args 2>&1 | Tee-Object -FilePath $LogPath -Append
    if ($LASTEXITCODE -ne 0) {
        throw "Transcription failed with exit code $LASTEXITCODE. See $LogPath"
    }

    $patterns = @()
    if ($Format -eq "txt" -or $Format -eq "both") {
        $patterns += "*.txt"
    }
    if ($Format -eq "srt" -or $Format -eq "both") {
        $patterns += "*.srt"
    }

    $found = @()
    foreach ($pattern in $patterns) {
        $found += Get-ChildItem -LiteralPath $OutDir -Filter $pattern -File -ErrorAction SilentlyContinue
    }
    if ($found.Count -eq 0) {
        throw "Transcription command finished but no transcript files were found in $OutDir"
    }

    return @($found.FullName)
}

function Get-TranscriptFiles {
    param([string]$OutDir)

    if (-not (Test-Path -LiteralPath $OutDir)) {
        return @()
    }

    $patterns = @()
    if ($Format -eq "txt" -or $Format -eq "both") {
        $patterns += "*.txt"
    }
    if ($Format -eq "srt" -or $Format -eq "both") {
        $patterns += "*.srt"
    }

    $found = @()
    foreach ($pattern in $patterns) {
        $found += Get-ChildItem -LiteralPath $OutDir -Filter $pattern -File -ErrorAction SilentlyContinue
    }

    return @($found.FullName)
}
function Invoke-RcloneUpload {
    param(
        [string]$SourceDir,
        [string]$RemotePath,
        [string]$LogPath
    )

    $rclone = Get-Command "rclone" -ErrorAction SilentlyContinue
    if (-not $rclone) {
        throw "rclone was not found on PATH. Install rclone and configure remote '$DriveRemote' first."
    }

    "[$(Get-Date -Format o)] Upload $SourceDir -> $RemotePath" | Add-Content -LiteralPath $LogPath -Encoding utf8
    & $rclone.Source copy $SourceDir $RemotePath --create-empty-src-dirs 2>&1 | Tee-Object -FilePath $LogPath -Append
    if ($LASTEXITCODE -ne 0) {
        throw "rclone upload failed with exit code $LASTEXITCODE. See $LogPath"
    }
}

if (-not (Test-Path -LiteralPath $ConfigPath)) {
    throw "Channel config not found: $ConfigPath"
}
if (-not (Test-Path -LiteralPath $RunScript)) {
    throw "Run script not found: $RunScript"
}

$processed = [System.Collections.Generic.HashSet[string]]::new()
if (Test-Path -LiteralPath $ProcessedPath) {
    Get-Content -LiteralPath $ProcessedPath | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object {
        [void]$processed.Add($_.Trim())
    }
}

$channels = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$ytDlp = Resolve-YtDlpCommand
$cutoff = (Get-Date).AddHours(-1 * $LookbackHours)
$allItems = @()

foreach ($channel in $channels) {
    $sources = @("videos")
    if ($IncludeStreams -or $channel.includeStreams) {
        $sources += "streams"
    }

    foreach ($source in $sources) {
        try {
            $items = Get-ChannelItems -YtDlpCommand $ytDlp -Handle $channel.handle -Source $source -Limit $PlaylistEnd
            foreach ($item in $items) {
                if (-not $item.Channel) {
                    $item.Channel = $channel.name
                }
                $allItems += $item
            }
        } catch {
            Write-Warning $_.Exception.Message
        }
    }
}

$newItems = $allItems |
    Sort-Object PublishedAt |
    Group-Object Id |
    ForEach-Object { $_.Group | Sort-Object PublishedAt -Descending | Select-Object -First 1 } |
    Where-Object {
        $_.PublishedAt -ge $cutoff -and -not $processed.Contains($_.Id)
    } |
    Sort-Object PublishedAt |
    Select-Object -First $MaxNewPerRun

Write-Host "yt-dlp executable: $($ytDlp.Executable)"
if ($ytDlp.Module) {
    Write-Host "yt-dlp module: $($ytDlp.Module)"
}
Write-Host "Discovered items: $($allItems.Count)"
Write-Host "New items within $LookbackHours hours: $($newItems.Count)"

if ($DiscoverOnly) {
    $newItems | Select-Object Channel, Handle, Source, PublishedAt, Duration, Title, Url | Format-Table -AutoSize -Wrap
    exit 0
}

$hadFailure = $false
foreach ($item in $newItems) {
    $datePart = $item.PublishedAt.ToString("yyyy-MM-dd")
    $channelPart = Get-SafePathName -Value $item.Channel
    $videoOutDir = Join-Path $TranscriptRoot (Join-Path $datePart (Join-Path $channelPart $item.Id))
    $logPath = Join-Path $LogRoot "$($item.PublishedAt.ToString("yyyyMMdd-HHmmss"))-$($item.Id).log"
    $record = [ordered]@{
        time = (Get-Date).ToString("o")
        id = $item.Id
        url = $item.Url
        title = $item.Title
        channel = $item.Channel
        handle = $item.Handle
        source = $item.Source
        publishedAt = $item.PublishedAt.ToString("o")
        outputDir = $videoOutDir
        logPath = $logPath
        status = "started"
    }
    Write-RunRecord -Record $record

    try {
        $files = Get-TranscriptFiles -OutDir $videoOutDir
        if ($files.Count -gt 0) {
            Write-Host "Transcript exists, skipping transcription: $($item.Channel) / $($item.Title)"
            $record.time = (Get-Date).ToString("o")
            $record.status = "transcript_exists"
            $record.files = @($files)
            Write-RunRecord -Record $record
        } else {
            Write-Host "Transcribing: $($item.Channel) / $($item.Title)"
            $files = Invoke-Transcription -Item $item -OutDir $videoOutDir -LogPath $logPath

            $record.time = (Get-Date).ToString("o")
            $record.status = "transcribed"
            $record.files = @($files)
            Write-RunRecord -Record $record
        }

        if ($UploadMode -eq "rclone") {
            $remoteChannel = Get-SafePathName -Value $item.Channel
            $remotePath = "$DriveRemote`:$DrivePath/$datePart/$remoteChannel/$($item.Id)"
            Invoke-RcloneUpload -SourceDir $videoOutDir -RemotePath $remotePath -LogPath $logPath

            $record.time = (Get-Date).ToString("o")
            $record.status = "uploaded"
            $record.remotePath = $remotePath
            Write-RunRecord -Record $record
        }

        $item.Id | Add-Content -LiteralPath $ProcessedPath -Encoding ascii
        [void]$processed.Add($item.Id)
    } catch {
        $hadFailure = $true
        $record.time = (Get-Date).ToString("o")
        $record.status = "failed"
        $record.error = $_.Exception.Message
        Write-RunRecord -Record $record
        Write-Error $_.Exception.Message
    }
}

if ($hadFailure) {
    exit 2
}

exit 0
