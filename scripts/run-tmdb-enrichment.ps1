$ErrorActionPreference = "Continue"

$ProjectRoot = "C:\Users\antho\Code\media-bot"
$TotalItems = 450         # Adjust this to match your total library size
$BatchSize = 10           # Safe batch size for rate limits
$DelaySeconds = 2        # Sleep interval between batches
$RateLimitCooldownSeconds = 15
$StartOffset = 0
$Provider = "rules"

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
    $BackupFile = Join-Path $BackupDir "moviebot.sqlite3.bak_$BackupTimestamp"
    
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

# Python query to check missing TMDb brand/franchise enrichment
$countScript = @"
import sqlite3
import os
db_path = os.path.join("data", "moviebot.sqlite3")
if not os.path.exists(db_path):
    print(0)
    import sys
    sys.exit(0)
conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute("SELECT COUNT(*) FROM library_items WHERE source = 'plex' AND (brand_tags IS NULL OR brand_tags = '')")
print(cursor.fetchone()[0])
"@

# Get initial count of missing items
$initialMissingStr = $countScript | py -3.12 -
$initialMissing = [int]$initialMissingStr.Trim()

Write-Host "[$timestamp] Starting TMDb Brand/Franchise enrichment backfill batches" -ForegroundColor Green
Write-Host "Project: $ProjectRoot"
Write-Host "Provider: $Provider"
Write-Host "Batch size: $BatchSize"
Write-Host "Delay between batches: $DelaySeconds seconds"
Write-Host "Rate-limit cooldown: $RateLimitCooldownSeconds seconds"
Write-Host "Start offset: $StartOffset"
Write-Host "Initial items needing enrichment: $initialMissing" -ForegroundColor Cyan

$offset = $StartOffset
$successfulCount = 0
$consecutiveRetries = 0

while ($true) {
    # Get current missing count for progress tracking
    $currentMissingStr = $countScript | py -3.12 -
    $currentMissing = [int]$currentMissingStr.Trim()

    # If no more items need enrichment, we are done!
    if ($currentMissing -le 0) {
        Write-Host "No more items need TMDb/brand/franchise enrichment." -ForegroundColor Green
        break
    }

    # If offset is greater than or equal to currentMissing, we've processed or skipped all remaining items
    if ($offset -ge $currentMissing) {
        Write-Host "Reached offset limit (offset $offset >= remaining missing $currentMissing). Skipping remaining stuck items." -ForegroundColor Yellow
        break
    }

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Host ""
    Write-Host "=== [$timestamp] Batch offset $offset, limit $BatchSize (Remaining missing: $currentMissing / Initial missing: $initialMissing) ===" -ForegroundColor Cyan

    $output = py -3.12 -m moviebot.cli.tool_cli sync-enrichment `
        --no-dry-run `
        --limit $BatchSize `
        --offset $offset `
        --provider $Provider `
        --only-missing-brands `
        --json

    $outputStr = ($output | Out-String).Trim()
    
    # Try parsing response JSON
    $json = $null
    try {
        $json = ConvertFrom-Json $outputStr -ErrorAction Stop
    } catch {
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        Write-Host "[$timestamp] Failed to parse JSON response from command. Raw output:" -ForegroundColor Red
        Write-Host $outputStr
        exit 1
    }

    if ($json.ok) {
        $processed = $json.data.processed
        $selected = $json.data.selected
        
        if ($selected -eq 0) {
            Write-Host "No more library items selected for processing." -ForegroundColor Green
            break
        }

        $successfulCount += $processed
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        Write-Host "[$timestamp] Batch succeeded. Enriched $processed items in this batch. (Total enriched this run: $successfulCount)" -ForegroundColor Green

        # Reset consecutive retries and keep offset (the successfully enriched items are now removed from the query)
        $consecutiveRetries = 0

        Write-Host "[$timestamp] Sleeping $DelaySeconds seconds before next batch..." -ForegroundColor DarkGray
        Start-Sleep -Seconds $DelaySeconds
    }
    else {
        # Error case
        $errCode = $json.error.code
        $errMsg = $json.error.message
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

        $isTransient = $false
        if ($errCode -eq "RATE_LIMIT_OR_OVERLOAD" -or $errMsg -match "429|RESOURCE_EXHAUSTED|quota|Quota exceeded|too many requests|503|Service Unavailable") {
            $isTransient = $true
        }

        if ($isTransient) {
            $consecutiveRetries++
            Write-Host "[$timestamp] Transient error encountered: $errMsg" -ForegroundColor Yellow
            Write-Host "[$timestamp] Retry attempt $consecutiveRetries/3 for offset $offset." -ForegroundColor Yellow

            if ($consecutiveRetries -gt 3) {
                Write-Host "[$timestamp] Max retries exceeded for this batch. Skipping to next batch by incrementing offset." -ForegroundColor Orange
                $offset += $BatchSize
                $consecutiveRetries = 0
                Write-Host "[$timestamp] Sleeping $DelaySeconds seconds..." -ForegroundColor DarkGray
                Start-Sleep -Seconds $DelaySeconds
            } else {
                Write-Host "[$timestamp] Cooling down for $RateLimitCooldownSeconds seconds..." -ForegroundColor Yellow
                Start-Sleep -Seconds $RateLimitCooldownSeconds
            }
        }
        else {
            # Fatal error (e.g. database locked, configuration issues)
            Write-Host "[$timestamp] Fatal error encountered: $errMsg. Stopping script." -ForegroundColor Red
            exit 1
        }
    }
}

# Get final count of missing items
$finalMissingStr = $countScript | py -3.12 -
$finalMissing = [int]$finalMissingStr.Trim()

$totalProcessed = $initialMissing - $finalMissing

Write-Host ""
Write-Host "==================================================" -ForegroundColor Green
Write-Host "          TMDb Enrichment Summary" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green
Write-Host "Initial items needing enrichment: $initialMissing"
Write-Host "Final items needing enrichment:   $finalMissing"
Write-Host "Successfully processed/fallback:  $totalProcessed"
Write-Host "Enrichments added in this run:    $successfulCount"
if ($finalMissing -gt 0) {
    Write-Host "Status: Completed with some items skipped due to persistent errors." -ForegroundColor Yellow
} else {
    Write-Host "Status: Fully completed. All items enriched!" -ForegroundColor Green
}
Write-Host "==================================================" -ForegroundColor Green
