$ErrorActionPreference = "Stop"

$ProjectRoot = "C:\Users\antho\Code\media-bot"
$TotalItems = 421
$BatchSize = 5
$DelaySeconds = 90
$RateLimitCooldownSeconds = 1800
$StartOffset = 300
$Provider = "rules"

Set-Location $ProjectRoot
$env:PYTHONPATH = "src"

Write-Host "Starting Wikidata-backed enrichment batches" -ForegroundColor Green
Write-Host "Project: $ProjectRoot"
Write-Host "Provider: $Provider"
Write-Host "Batch size: $BatchSize"
Write-Host "Delay between clean batches: $DelaySeconds seconds"
Write-Host "Rate-limit cooldown: $RateLimitCooldownSeconds seconds"
Write-Host "Start offset: $StartOffset"

for ($offset = $StartOffset; $offset -lt $TotalItems; $offset += $BatchSize) {
    Write-Host ""
    Write-Host "=== Batch offset $offset, limit $BatchSize ===" -ForegroundColor Cyan

    $output = py -3.12 -m moviebot.cli.tool_cli sync-enrichment `
        --no-dry-run `
        --limit $BatchSize `
        --offset $offset `
        --provider $Provider `
        --json 2>&1

    $text = ($output | Out-String)
    Write-Host $text

    if ($LASTEXITCODE -ne 0) {
        Write-Host "Command failed at offset $offset. Stopping." -ForegroundColor Red
        exit $LASTEXITCODE
    }

    if ($text -match "429|rate.limit|too many requests|Wikidata rate limited|rate-limited") {
        Write-Host "Detected Wikidata rate limit. Cooling down for $RateLimitCooldownSeconds seconds..." -ForegroundColor Yellow
        Start-Sleep -Seconds $RateLimitCooldownSeconds
    }
    else {
        Write-Host "Sleeping $DelaySeconds seconds before next batch..." -ForegroundColor DarkGray
        Start-Sleep -Seconds $DelaySeconds
    }
}

Write-Host ""
Write-Host "Done. Running final dry-run audit..." -ForegroundColor Green

py -3.12 -m moviebot.cli.tool_cli sync-enrichment --limit 1 --provider rules --json
