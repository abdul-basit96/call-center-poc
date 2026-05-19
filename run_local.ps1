# Windows native launcher — same flow as run_local.sh on Mac.
# Usage (PowerShell, from project folder):
#   .\run_local.ps1                  # check tools, then run
#   .\run_local.ps1 -InstallMissing  # winget: uv, Node, Ollama, ffmpeg; then run
#
# Manual one-time (script cannot fully automate):
#   PostgreSQL + pgvector + database from your .env
#   Start Ollama app after installing Ollama

param(
    [switch]$InstallMissing
)

#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root

$script:BackendProc = $null

# CLI tools we can often install via winget; Postgres is manual only.
$script:ToolChecks = @(
    @{
        Label    = "uv (Python)"
        Command  = "uv"
        WingetId = "astral-sh.uv"
        Manual   = "https://docs.astral.sh/uv/getting-started/installation/"
        Required = $true
    },
    @{
        Label    = "Node.js"
        Command  = "node"
        WingetId = "OpenJS.NodeJS.LTS"
        Manual   = "https://nodejs.org/"
        Required = $true
    },
    @{
        Label    = "npm"
        Command  = "npm"
        WingetId = $null
        Manual   = "Included with Node.js — reinstall Node if missing."
        Required = $true
    },
    @{
        Label    = "Ollama CLI"
        Command  = "ollama"
        WingetId = "Ollama.Ollama"
        Manual   = "https://ollama.com/download/windows — then open the Ollama app."
        Required = $true
    },
    @{
        Label     = "ffmpeg (voice STT)"
        Command   = "ffmpeg"
        WingetId  = "Gyan.FFmpeg"
        WingetIds = @("Gyan.FFmpeg", "ffmpeg")   # try fallbacks if one package fails
        Manual    = "winget install --id Gyan.FFmpeg  or  https://www.gyan.dev/ffmpeg/builds/"
        Required  = $true
    }
)

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Fail([string]$Message) {
    Write-Host ""
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

function Refresh-SessionPath {
    $machine = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Test-HasCommand([string]$Name) {
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-WingetAvailable {
    return Test-HasCommand "winget"
}

function Install-WithWinget([string]$WingetId, [string]$Label, [string]$CommandName) {
    if (-not (Test-WingetAvailable)) {
        Write-Host "  winget not available — install $Label manually." -ForegroundColor Yellow
        return $false
    }
    Write-Host "  Installing $Label ($WingetId) via winget..." -ForegroundColor Yellow
    & winget install --id $WingetId -e `
        --accept-source-agreements `
        --accept-package-agreements `
        --disable-interactivity
    if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne -1978335189) {
        # -1978335189 = already installed
        Write-Host "  winget install returned $LASTEXITCODE" -ForegroundColor Yellow
        return $false
    }
    Refresh-SessionPath
    return (Test-HasCommand $CommandName)
}

function Install-ToolWithWinget([hashtable]$Tool) {
    $ids = @()
    if ($Tool.WingetIds) { $ids = @($Tool.WingetIds) }
    elseif ($Tool.WingetId) { $ids = @($Tool.WingetId) }
    foreach ($id in $ids) {
        Install-WithWinget $id $Tool.Label $Tool.Command | Out-Null
        if (Test-HasCommand $Tool.Command) { return $true }
    }
    return $false
}

function Ensure-CliPrerequisites {
    Write-Step "Checking required tools"

    $missingRequired = [System.Collections.Generic.List[string]]::new()

    foreach ($tool in $script:ToolChecks) {
        if (Test-HasCommand $tool.Command) {
            Write-Host "  ok: $($tool.Label)" -ForegroundColor DarkGray
            continue
        }

        if ($InstallMissing -and ($tool.WingetId -or $tool.WingetIds)) {
            Install-ToolWithWinget $tool | Out-Null
        }

        if (Test-HasCommand $tool.Command) {
            Write-Host "  ok: $($tool.Label)" -ForegroundColor DarkGray
            continue
        }

        $line = "  MISSING: $($tool.Label) — $($tool.Manual)"
        $missingRequired.Add($line) | Out-Null
        Write-Host $line -ForegroundColor Red
    }

    if ($missingRequired.Count -gt 0) {
        Write-Host ""
        Write-Host "Install the items above, then run this script again." -ForegroundColor Red
        if (-not $InstallMissing -and (Test-WingetAvailable)) {
            Write-Host "Or retry with:  .\run_local.ps1 -InstallMissing" -ForegroundColor Cyan
            Write-Host "(winget installs uv, Node, Ollama, and ffmpeg — open a new terminal if a tool is still not found)" -ForegroundColor DarkGray
        }
        exit 1
    }

}

function Test-TcpPort([int]$Port) {
    return (Test-NetConnection -ComputerName localhost -Port $Port -WarningAction SilentlyContinue).TcpTestSucceeded
}

function Stop-Backend {
    if ($null -eq $script:BackendProc) { return }
    if (-not $script:BackendProc.HasExited) {
        Write-Host "Stopping backend..." -ForegroundColor DarkGray
        Stop-Process -Id $script:BackendProc.Id -Force -ErrorAction SilentlyContinue
    }
    $script:BackendProc = $null
}

function Get-OllamaModelNames {
    $resp = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 15
    if ($null -eq $resp.models) { return @() }
    return @($resp.models | ForEach-Object { $_.name })
}

function Test-OllamaModelPresent([string]$ModelName, [string[]]$Installed) {
    foreach ($n in $Installed) {
        if ($n -eq $ModelName -or $n.StartsWith("${ModelName}:")) { return $true }
    }
    return $false
}

function Ensure-OllamaModel([string]$ModelName) {
    $installed = Get-OllamaModelNames
    if (Test-OllamaModelPresent $ModelName $installed) {
        Write-Host "  ok: $ModelName" -ForegroundColor DarkGray
        return
    }
    Write-Host "  pulling $ModelName (first run can take several minutes)..." -ForegroundColor Yellow
    & ollama pull $ModelName
    if ($LASTEXITCODE -ne 0) { Fail "ollama pull $ModelName failed" }
}

function Wait-BackendHealth {
    param([int]$TimeoutSeconds = 300)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if ($script:BackendProc.HasExited) {
            Fail "Backend exited (code $($script:BackendProc.ExitCode)). Check Ollama, .env DATABASE_URL, and pgvector."
        }
        try {
            $h = Invoke-RestMethod -Uri "http://localhost:8000/health" -TimeoutSec 3
            if ($h.status -eq "ok") { return }
        } catch { }
        Start-Sleep -Seconds 2
    }
    Fail "Backend not healthy at http://localhost:8000/health within ${TimeoutSeconds}s."
}

Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action { Stop-Backend } | Out-Null

Write-Host ""
Write-Host "Medical Appointment Assistant — Windows" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green

Ensure-CliPrerequisites

Write-Step "Syncing Python dependencies (uv sync)"
uv sync
if ($LASTEXITCODE -ne 0) { Fail "uv sync failed" }

Write-Step "Syncing frontend dependencies (npm install)"
Push-Location "$Root\frontend"
npm install
if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "npm install failed" }
Pop-Location

Write-Step "Checking Ollama is running (http://localhost:11434)"
try {
    Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 5 | Out-Null
} catch {
    Fail @"
Ollama is installed but not responding on http://localhost:11434.
Open the Ollama app from the Start menu and wait until it is running, then run this script again.
"@
}

Write-Step "Checking Ollama models"
Ensure-OllamaModel "gemma4:e2b"
Ensure-OllamaModel "bge-m3"

Write-Step "Checking PostgreSQL (localhost:5432)"
if (-not (Test-TcpPort 5432)) {
    Fail @"
PostgreSQL is not reachable on localhost:5432.

This cannot be installed automatically. Each developer must set up once:
  1. Install PostgreSQL for Windows: https://www.postgresql.org/download/windows/
  2. Install pgvector for your Postgres version: https://github.com/pgvector/pgvector
  3. Create the database/user from your project .env (DATABASE_URL)

Then run this script again.
"@
}

Write-Step "Seeding database (schema + embeddings)"
uv run python -m scripts.seed_db
if ($LASTEXITCODE -ne 0) {
    Fail "seed_db failed — verify .env DATABASE_URL, pgvector, and that bge-m3 is available in Ollama."
}

Write-Step "Starting backend (http://localhost:8000)"
$script:BackendProc = Start-Process -FilePath "uv" `
    -ArgumentList @("run", "python", "-m", "backend.main") `
    -WorkingDirectory $Root `
    -PassThru `
    -WindowStyle Hidden

Wait-BackendHealth

Write-Step "Starting frontend (http://localhost:5173)"
Write-Host ""
Write-Host "Ready — open http://localhost:5173 in your browser" -ForegroundColor Green
Write-Host "API health: http://localhost:8000/health" -ForegroundColor DarkGray
Write-Host "Press Ctrl+C to stop backend and frontend." -ForegroundColor DarkGray
Write-Host ""

try {
    Push-Location "$Root\frontend"
    npm run dev
} finally {
    Stop-Backend
    Pop-Location -ErrorAction SilentlyContinue
}
