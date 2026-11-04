# One-click update (Windows).
#
#   powershell -ExecutionPolicy Bypass -File scripts\update.ps1
#   powershell ... -File scripts\update.ps1 -Rebuild      # also rebuild the sandbox image
#   powershell ... -File scripts\update.ps1 -NoDeps       # code only
#
# It backs up .env, pulls the latest code (fast-forward only), syncs Python
# dependencies with uv, and optionally rebuilds the Docker sandbox image.

param(
    [switch]$Rebuild,
    [switch]$NoDeps
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "== CTF Agent update ==" -ForegroundColor Cyan
Write-Host "repo: $root"

if (-not (Test-Path ".git")) {
    Write-Host "not a git checkout - re-clone the repository instead" -ForegroundColor Red
    exit 1
}

# 1. keep the user's configuration
if (Test-Path ".env") {
    Copy-Item ".env" ".env.bak" -Force
    Write-Host "[1/4] backed up .env -> .env.bak"
} else {
    Write-Host "[1/4] no .env yet (copy .env.example after the update)"
}

# 2. pull
git fetch --prune
if ($LASTEXITCODE -ne 0) { Write-Host "git fetch failed" -ForegroundColor Red; exit 1 }

$dirty = git status --porcelain
if ($dirty) {
    Write-Host "local changes detected:" -ForegroundColor Yellow
    $dirty | ForEach-Object { Write-Host "  $_" }
    Write-Host "run 'git stash' first, then re-run this script" -ForegroundColor Yellow
    exit 1
}

git pull --ff-only
if ($LASTEXITCODE -ne 0) { Write-Host "git pull failed (non fast-forward?)" -ForegroundColor Red; exit 1 }
Write-Host "[2/4] code updated"

# 3. dependencies
if (-not $NoDeps) {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Host "uv not found - install it: powershell -c `"irm https://astral.sh/uv/install.ps1 | iex`"" -ForegroundColor Red
        exit 1
    }
    uv sync
    if ($LASTEXITCODE -ne 0) { Write-Host "uv sync failed" -ForegroundColor Red; exit 1 }
    Write-Host "[3/4] python dependencies synced"
} else {
    Write-Host "[3/4] skipped dependency sync (-NoDeps)"
}

# 4. sandbox image
if ($Rebuild) {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Host "docker not found - install Docker Desktop first" -ForegroundColor Red
        exit 1
    }
    Write-Host "[4/4] rebuilding ctf-sandbox (this takes a while)..."
    docker build -f sandbox/Dockerfile.sandbox -t ctf-sandbox .
    if ($LASTEXITCODE -ne 0) { Write-Host "docker build failed" -ForegroundColor Red; exit 1 }
} else {
    Write-Host "[4/4] skipped image rebuild (pass -Rebuild to do it)"
}

Write-Host ""
Write-Host "done. your previous .env is at .env.bak (merge any new keys by hand)." -ForegroundColor Green
Write-Host "start the dashboard:  uv run python scripts/webui.py --port 8099"
