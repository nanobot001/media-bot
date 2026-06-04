param (
    [int]$Limit = 50,
    [double]$Delay = 4.0,
    [switch]$DryRun,
    [switch]$Force
)

$ErrorActionPreference = "Continue"

$ProjectRoot = "C:\Users\antho\Code\media-bot"
Set-Location $ProjectRoot
$env:PYTHONPATH = "src"

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

# --- Database Backup Step ---
$DatabaseFile = Join-Path $ProjectRoot "data\moviebot.sqlite3"
$BackupDir = Join-Path $ProjectRoot "data\backups"

if (Test-Path $DatabaseFile) {
    if (-not (Test-Path $BackupDir)) {
        New-Item -ItemType Directory -Path $BackupDir | Out-Null
    }
    $BackupTimestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $BackupFile = Join-Path $BackupDir "moviebot.sqlite3.bak_embeddings_$BackupTimestamp"
    
    # Check if WAL/shm files exist and copy them too if present (SQLite WAL mode safety)
    Copy-Item -Path $DatabaseFile -Destination $BackupFile -Force
    if (Test-Path "$DatabaseFile-wal") {
        Copy-Item -Path "$DatabaseFile-wal" -Destination "$BackupFile-wal" -Force
    }
    if (Test-Path "$DatabaseFile-shm") {
        Copy-Item -Path "$DatabaseFile-shm" -Destination "$BackupFile-shm" -Force
    }
    
    Write-Host "[$timestamp] Database backed up successfully to: $BackupFile" -ForegroundColor Cyan
} else {
    Write-Host "[$timestamp] Database file not found at $DatabaseFile. Skipping backup." -ForegroundColor Yellow
}
# ----------------------------

Write-Host "[$timestamp] Starting Embeddings Backfill Script" -ForegroundColor Green
Write-Host "Project Root: $ProjectRoot"
Write-Host "Limit:        $Limit"
Write-Host "Delay:        $Delay seconds"
Write-Host "DryRun:       $($DryRun.ToBool())"
Write-Host "Force:        $($Force.ToBool())"

# Construct arguments
$argsList = @("scripts/run_embeddings_backfill.py")
if ($Limit -gt 0) {
    $argsList += "--limit", $Limit
}
if ($Delay -ge 0) {
    $argsList += "--delay", $Delay
}
if ($DryRun) {
    $argsList += "--dry-run"
}
if ($Force) {
    $argsList += "--force"
}

# Run Python backfill
py -3.12 $argsList

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Write-Host "[$timestamp] Embeddings backfill process completed." -ForegroundColor Green
