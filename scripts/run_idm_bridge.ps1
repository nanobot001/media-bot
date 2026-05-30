# IDM Container-to-Host HTTP Bridge Listener
# Exposes a local web service on 127.0.0.1 to enqueue downloads in native IDM.

$port = 8765
$secret = "your_configured_shared_secret_here" # Matches IDM_BRIDGE_SECRET in .env
$idmExe = "C:\Program Files (x86)\Internet Download Manager\IDMan.exe"

# If .env exists in parent directory, try parsing the secret from it
$envPath = Join-Path $PSScriptRoot "..\.env"
if (Test-Path $envPath) {
    Get-Content $envPath | ForEach-Object {
        if ($_ -match "^IDM_BRIDGE_SECRET=(.+)$") {
            $secret = $Matches[1].Trim()
        }
    }
}

if (-not (Test-Path $idmExe)) {
    Write-Warning "IDMan.exe was not found at expected path: $idmExe"
}

$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add("http://127.0.0.1:$port/")
try {
    $listener.Start()
    Write-Host "IDM HTTP Bridge listening on http://127.0.0.1:$port/ ..." -ForegroundColor Green
    Write-Host "Ctrl+C to terminate."
    
    while ($listener.IsListening) {
        $context = $listener.GetContext()
        $request = $context.Request
        $response = $context.Response
        
        Write-Host "[$((Get-Date).ToString("HH:mm:ss"))] $($request.HttpMethod) $($request.Url.LocalPath)"
        
        # 1. Route validation
        if ($request.Url.LocalPath -eq "/health" -and $request.HttpMethod -eq "GET") {
            $response.StatusCode = 200
            $response.ContentType = "application/json"
            $buffer = [System.Text.Encoding]::UTF8.GetBytes('{"status":"ok"}')
            $response.ContentLength64 = $buffer.Length
            $response.OutputStream.Write($buffer, 0, $buffer.Length)
            $response.Close()
            continue
        }

        if ($request.Url.LocalPath -ne "/downloads" -or $request.HttpMethod -ne "POST") {
            $response.StatusCode = 404
            $response.Close()
            continue
        }
        
        # 2. Secret authentication
        $headerSecret = $request.Headers.Get("X-Bridge-Secret")
        if ($headerSecret -ne $secret) {
            Write-Host "  [Unauthorized request]" -ForegroundColor Red
            $response.StatusCode = 401
            $response.ContentType = "application/json"
            $buffer = [System.Text.Encoding]::UTF8.GetBytes('{"error":"Unauthorized"}')
            $response.ContentLength64 = $buffer.Length
            $response.OutputStream.Write($buffer, 0, $buffer.Length)
            $response.Close()
            continue
        }
        
        # 3. Read request body
        $reader = New-Object System.IO.StreamReader($request.InputStream, [System.Text.Encoding]::UTF8)
        $body = $reader.ReadToEnd()
        
        try {
            $data = ConvertFrom-Json $body
        } catch {
            $response.StatusCode = 400
            $response.ContentType = "application/json"
            $buffer = [System.Text.Encoding]::UTF8.GetBytes('{"error":"Invalid JSON"}')
            $response.ContentLength64 = $buffer.Length
            $response.OutputStream.Write($buffer, 0, $buffer.Length)
            $response.Close()
            continue
        }
        
        $url = $data.url
        $outputDir = $data.output_dir
        $filename = $data.filename
        $dryRun = $data.dry_run
        
        if (-not $url -or -not $filename) {
            $response.StatusCode = 400
            $response.ContentType = "application/json"
            $buffer = [System.Text.Encoding]::UTF8.GetBytes('{"error":"url and filename parameters are required"}')
            $response.ContentLength64 = $buffer.Length
            $response.OutputStream.Write($buffer, 0, $buffer.Length)
            $response.Close()
            continue
        }
        
        if ([string]::IsNullOrEmpty($outputDir)) {
            $outputDir = "F:\_temp\movies"
        }
        
        # 4. Trigger IDM
        if ($dryRun) {
            Write-Host "  [DRY-RUN] Would enqueue: $filename" -ForegroundColor Yellow
            $response.StatusCode = 200
            $response.ContentType = "application/json"
            $buffer = [System.Text.Encoding]::UTF8.GetBytes('{"status":"dry_run","message":"Dry-run validated successfully."}')
            $response.ContentLength64 = $buffer.Length
            $response.OutputStream.Write($buffer, 0, $buffer.Length)
            $response.Close()
            continue
        }
        
        Write-Host "  Queueing file: $filename" -ForegroundColor Cyan
        
        # Ensure arguments with potential spaces are wrapped in escaped quotes for Start-Process
        $args = @("/d", "`"$url`"", "/p", "`"$outputDir`"", "/f", "`"$filename`"", "/n", "/q")
        
        try {
            Start-Process $idmExe -ArgumentList $args
            $response.StatusCode = 200
            $response.ContentType = "application/json"
            $buffer = [System.Text.Encoding]::UTF8.GetBytes('{"status":"success","message":"Successfully sent to IDM"}')
            $response.ContentLength64 = $buffer.Length
            $response.OutputStream.Write($buffer, 0, $buffer.Length)
        } catch {
            $response.StatusCode = 500
            $response.ContentType = "application/json"
            $buffer = [System.Text.Encoding]::UTF8.GetBytes("`"error`":`"$($_.Exception.Message)`"")
            $response.ContentLength64 = $buffer.Length
            $response.OutputStream.Write($buffer, 0, $buffer.Length)
        }
        
        $response.Close()
    }
} finally {
    $listener.Stop()
    Write-Host "Listener stopped."
}
