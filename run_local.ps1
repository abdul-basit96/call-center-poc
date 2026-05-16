# Local dev (Windows): same flow as run_local.sh — one command starts backend + frontend.
$ErrorActionPreference = "Stop"

$RepoRoot = $PSScriptRoot
if (-not $RepoRoot) { $RepoRoot = Get-Location }
Set-Location $RepoRoot

$BackendProc = $null

function Stop-Backend {
    if ($null -ne $script:BackendProc -and -not $script:BackendProc.HasExited) {
        Write-Host "Stopping backend…" -ForegroundColor DarkGray
        Stop-Process -Id $script:BackendProc.Id -Force -ErrorAction SilentlyContinue
    }
}

try {
    Write-Host "📦 Syncing Python dependencies (uv)…" -ForegroundColor Cyan
    uv sync

    Write-Host "📦 Syncing Frontend dependencies (npm)…" -ForegroundColor Cyan
    Push-Location frontend
    npm install
    Pop-Location

    Write-Host "🐘 Checking Database (Postgres)…" -ForegroundColor Cyan
    $pgCheck = Test-NetConnection -ComputerName localhost -Port 5432 -InformationLevel Quiet -WarningAction SilentlyContinue
    if (-not $pgCheck) {
        Write-Host "⚠️ Warning: Postgres might not be running on localhost:5432" -ForegroundColor Yellow
        Write-Host "   Tip: run 'docker compose up db' in another terminal." -ForegroundColor Yellow
    }

    Write-Host "🌱 Initializing Database & Seed Data…" -ForegroundColor Cyan
    uv run python -m scripts.seed_db

    function Wait-ForBackend {
        $url = "http://127.0.0.1:8000/health"
        $maxWait = if ($env:BACKEND_HEALTH_TIMEOUT_SEC) { [int]$env:BACKEND_HEALTH_TIMEOUT_SEC } else { 900 }
        Write-Host "⏳ Waiting for backend at $url (up to ${maxWait}s; models preload at startup)…" -ForegroundColor Cyan
        $elapsed = 0
        while ($elapsed -lt $maxWait) {
            $ready = $false
            try {
                $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5
                if ($resp.StatusCode -eq 200) {
                    $h = $resp.Content | ConvertFrom-Json
                    if ($h.status -eq "ok" -and $h.models_preloaded) { $ready = $true }
                }
            } catch {
                # connection refused or 503 while models load
            }
            if ($ready) {
                Write-Host "✅ Backend is ready (all models preloaded)." -ForegroundColor Green
                return
            }
            Start-Sleep -Seconds 2
            $elapsed += 2
            if ($elapsed % 30 -eq 0) {
                Write-Host "   still waiting (${elapsed}s)…" -ForegroundColor DarkGray
            }
        }
        throw "Backend did not become ready on port 8000 within ${maxWait}s."
    }

    Write-Host "🚀 Starting backend (frontend starts after /health is up)…" -ForegroundColor Green
    $uvicornArgs = @("run", "uvicorn", "backend.main:app", "--port", "8000")
    if ($env:UVICORN_RELOAD -eq "1") {
        $uvicornArgs += "--reload"
        Write-Host "   (uvicorn --reload enabled; saving backend files will reload the LLM)" -ForegroundColor Yellow
    } else {
        Write-Host "   Models preload at startup; keep this terminal open between chats." -ForegroundColor DarkGray
    }

    $script:BackendProc = Start-Process -FilePath "uv" `
        -ArgumentList $uvicornArgs `
        -WorkingDirectory $RepoRoot `
        -PassThru `
        -NoNewWindow

    Wait-ForBackend

    Write-Host "🚀 Starting frontend…" -ForegroundColor Green
    Write-Host "   UI: http://127.0.0.1:5173" -ForegroundColor DarkGray
    Push-Location frontend
    npm run dev
    Pop-Location
}
finally {
    Stop-Backend
}
