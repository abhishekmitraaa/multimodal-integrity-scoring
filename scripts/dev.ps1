# Start everything for local development, in order: database, migrations, backend API on :8000
# (in its own window), then the web app on :5173 (in this window). Development data only.
#
# Usage, from the repository root:
#   powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 -DataRoot D:\integrity-data
# Stop: Ctrl+C here, then close the backend window.
param(
    [string]$DataRoot = $(if ($env:INTEGRITY_DATA_ROOT) { $env:INTEGRITY_DATA_ROOT } else { "C:\integrity-data" }),
    [ValidateSet("Normal", "Minimized", "Hidden")] [string]$BackendWindow = "Normal"
)
# Not "Stop": in Windows PowerShell 5.1 any stderr line from docker/npm (even a warning) would then be
# fatal. Every external command is checked through $LASTEXITCODE instead.
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
$py = Join-Path $repo ".venv\Scripts\python.exe"

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "`nSTOPPED: $text" -ForegroundColor Red; exit 1 }
function Test-Http($url) {
    try { return (Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 } catch { return $false }
}
function Wait-Until([scriptblock]$check, [int]$seconds, [string]$what) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) { if (& $check) { return } Start-Sleep -Seconds 2 }
    Fail "$what did not come up within $seconds s"
}

if (-not (Test-Path $py)) { Fail "no Python venv at $py. Follow README 'Setup' first." }
if (-not (Test-Path (Join-Path $repo "frontend\node_modules"))) { Fail "frontend dependencies missing. Run: cd frontend; npm install" }

Step "1/5 Docker"
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    $desktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if (-not (Test-Path $desktop)) { Fail "Docker is not running and Docker Desktop was not found." }
    Write-Host "Starting Docker Desktop..."
    Start-Process $desktop
    Wait-Until { docker info *> $null; $LASTEXITCODE -eq 0 } 180 "Docker"
}
Write-Host "Docker is running."

Step "2/5 Database (PostgreSQL on 127.0.0.1:5432)"
Push-Location $repo
try {
    docker compose up -d db
    if ($LASTEXITCODE -ne 0) { Fail "docker compose could not start the database. Are the secrets in place? (python scripts\make_secrets.py)" }
    Wait-Until { (docker compose ps db --format "{{.Status}}") -match "healthy" } 90 "The database"
    Write-Host "Database is healthy."

    Step "3/5 Data root and migrations"
    $env:INTEGRITY_DATA_ROOT = $DataRoot
    Write-Host "INTEGRITY_DATA_ROOT = $DataRoot"
    & $py -m alembic -c backend\alembic.ini upgrade head
    if ($LASTEXITCODE -ne 0) { Fail "database migrations failed (see the message above)." }

    Step "4/5 Backend API (http://127.0.0.1:8000)"
    if (Test-Http "http://127.0.0.1:8000/api/health") {
        Write-Host "A backend is already running; reusing it."
    } else {
        Start-Process -FilePath $py -ArgumentList "-m", "integrity_backend.app" -WorkingDirectory $repo -WindowStyle $BackendWindow
        Wait-Until { Test-Http "http://127.0.0.1:8000/api/health" } 60 "The backend"
        Write-Host "Backend is up (its log is in the new window)."
    }
} finally {
    Pop-Location
}

Step "5/5 Web app (http://127.0.0.1:5173, cross-origin isolated)"
if (Test-Http "http://127.0.0.1:5173/") {
    Write-Host "A web app is already running on :5173; reusing it."
    $serve = $false
} else {
    $serve = $true
}
Write-Host ""
Write-Host "  App (consent -> tasks -> submit):  http://127.0.0.1:5173/" -ForegroundColor Green
Write-Host "  Real-keyboard check:              http://127.0.0.1:5173/#/keycheck" -ForegroundColor Green
Write-Host "  Reviewer replay:                  http://127.0.0.1:5173/#/replay  (token: ~\.integrity-exam\secrets\reviewer_token.txt)" -ForegroundColor Green
Write-Host ""
if ($serve) {
    Push-Location (Join-Path $repo "frontend")
    try { npm run dev } finally { Pop-Location }
}
