# Stop on error
$ErrorActionPreference = "Stop"

Write-Host "📦 Syncing Python dependencies (uv)..." -ForegroundColor Cyan
uv sync

Write-Host "📦 Syncing Frontend dependencies (npm)..." -ForegroundColor Cyan
Set-Location frontend
npm install
Set-Location ..

Write-Host "🐘 Checking Database (Postgres)..." -ForegroundColor Cyan
# Simple check for Postgres
$pgCheck = Test-NetConnection -ComputerName localhost -Port 5432 -InformationLevel Quiet
if (-not $pgCheck) {
    Write-Host "⚠️ Warning: Postgres might not be running on localhost:5432" -ForegroundColor Yellow
}

Write-Host "🌱 Initializing Database & Seed Data..." -ForegroundColor Cyan
uv run python -m scripts.seed_db

function Wait-ForBackend {
    $url = "http://127.0.0.1:8000/health"
    $maxWait = if ($env:BACKEND_HEALTH_TIMEOUT_SEC) { [int]$env:BACKEND_HEALTH_TIMEOUT_SEC } else { 900 }
    Write-Host "⏳ Waiting for backend at $url (up to ${maxWait}s)..." -ForegroundColor Cyan
    $elapsed = 0
    while ($elapsed -lt $maxWait) {
        try {
            $h = Invoke-RestMethod -Uri $url -TimeoutSec 5
            if ($h.status -eq "ok" -and $h.models_preloaded) {
                Write-Host "✅ Backend is ready (all models preloaded)." -ForegroundColor Green
                return
            }
        } catch {
            Start-Sleep -Seconds 2
            $elapsed += 2
            if ($elapsed % 30 -eq 0) {
                Write-Host "   still waiting (${elapsed}s)..." -ForegroundColor DarkGray
            }
        }
    }
    throw "Backend did not respond on port 8000 within ${maxWait}s."
}

Write-Host "🚀 Starting backend (frontend starts after /health is up)..." -ForegroundColor Green
$uvicornArgs = "run", "uvicorn", "backend.main:app", "--port", "8000"
if ($env:UVICORN_RELOAD -eq "1") {
    $uvicornArgs += "--reload"
    Write-Host "   (uvicorn --reload enabled; saving backend files will reload the LLM)" -ForegroundColor Yellow
} else {
    Write-Host "   Models preload at startup; keep backend running between chats." -ForegroundColor DarkGray
}
Start-Process uv -ArgumentList $uvicornArgs

Wait-ForBackend

Write-Host "🚀 Starting frontend..." -ForegroundColor Green
Set-Location frontend
npm run dev
