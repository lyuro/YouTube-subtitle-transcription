# Channel Automation

This repo can run channel discovery, local transcription, and optional Google Drive upload without the Google Drive desktop app.

## Discovery

The runner is:

```powershell
.\scripts\watch_channels.ps1 -DiscoverOnly
```

It reads `scripts/channels.json`, checks each channel's `/videos` page, and also checks `/streams` for channels marked with `includeStreams`.

It processes only new videos from the last 36 hours. State, logs, and output are written below:

```text
output/channel-watch/processed.txt
output/channel-watch/runs.jsonl
output/channel-watch/logs/
output/channel-watch/transcripts/
```

## Transcription

Run real transcription:

```powershell
.\scripts\watch_channels.ps1 -Format both -Language zh
```

If YouTube requires browser cookies:

```powershell
.\scripts\watch_channels.ps1 -Format both -Language zh -CookiesFromBrowser "chrome:Private Profile"
```

The exact Chrome profile name must match the local Chrome profile name that `yt-dlp` can read.

## Google Drive Upload

Use `rclone` as the upload layer. It performs a one-time OAuth flow in Chrome and then stores a refresh token locally in the user's rclone config. The Google Drive desktop app is not required.

One-time setup:

```powershell
rclone config
```

Create a Google Drive remote named `gdrive`. During browser authorization, use the Chrome private profile that is already logged into the target Google account. If rclone opens the wrong Chrome profile, copy the authorization URL into the private profile.

The existing Drive folder is assumed to be:

```text
My Drive/YouTubeTranscripts
```

After the remote is configured:

```powershell
.\scripts\watch_channels.ps1 -Format both -Language zh -UploadMode rclone -DriveRemote gdrive -DrivePath YouTubeTranscripts
```

## Codex Automation

Codex app automations should run this runner on a schedule while Codex is open and this machine is awake. The automation prompt should ask Codex to execute the runner, inspect `output/channel-watch/logs/` and `runs.jsonl`, and fix or report failures such as:

- broken `.venv`
- YouTube 403 or cookie failure
- outdated `yt-dlp`
- missing output files
- rclone authentication or upload failure
- livestream not yet archived

Codex automations are not cloud jobs. They require the local Codex app to be running and the project directory to remain available on disk.
