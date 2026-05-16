# Stop on error
$ErrorActionPreference = "Stop"

Write-Host "📦 Syncing Python dependencies (uv)..." -ForegroundColor Cyan
uv sync

Write-Host "📦 Syncing Frontend dependencies (npm)..." -ForegroundColor Cyan
Set-Location frontend
npm install
Set-Location ..

Write-Host "🧠 Checking Ollama & Models..." -ForegroundColor Cyan
try {
    Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -Method Get > $null
} catch {
    Write-Host "❌ Error: Ollama is not running. Please start the Ollama app first." -ForegroundColor Red
    exit
}

Write-Host "  - Pulling gemma4:e2b..."
ollama pull gemma4:e2b
Write-Host "  - Pulling bge-m3..."
ollama pull bge-m3

Write-Host "🗄️ Checking Database & Seeding..." -ForegroundColor Cyan
if (!(Test-NetConnection -ComputerName localhost -Port 5432).TcpTestSucceeded) {
    Write-Host "❌ Error: Postgres is not running on localhost:5432." -ForegroundColor Red
    exit
}

Write-Host "  - Running seed_db.py (Schema + Embeddings)..."
uv run python -m scripts.seed_db

Write-Host "🚀 Starting Backend & Frontend..." -ForegroundColor Green
Write-Host "Press Ctrl+C to stop."

# Start backend in a new background job
Start-Job -ScriptBlock { uv run python -m backend.main }

# Start frontend in the current window
Set-Location frontend
npm run dev
