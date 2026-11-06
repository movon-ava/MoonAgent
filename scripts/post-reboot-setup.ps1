# Post-reboot setup for ctf-agent (run AFTER restarting Windows).
# 1) checks WSL2  2) starts Docker Desktop  3) builds the sandbox image  4) smoke-tests it
# Usage (elevated recommended for the WSL step):
#   powershell -ExecutionPolicy Bypass -File F:\ctf_agent\scripts\post-reboot-setup.ps1

$ErrorActionPreference = 'Continue'
$root = 'F:\ctf_agent'
$log  = Join-Path $root 'logs\post-reboot.log'
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null

$dockerDir = 'C:\Program Files\Docker\Docker\resources\bin'
$dockerExe = Join-Path $dockerDir 'docker.exe'
if (Test-Path $dockerDir) { $env:Path = "$dockerDir;$env:Path" }

function Log($m) {
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    "$ts  $m" | Tee-Object -FilePath $log -Append | Out-Null
    Write-Host "$ts  $m"
}
function IsAdmin {
    ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}
function DockerInfo {
    & $dockerExe info 2>&1 | Out-Null
    return ($LASTEXITCODE -eq 0)
}

Log '=== post-reboot setup start ==='
Log ("admin = " + (IsAdmin))
Log ("docker cli = " + (Test-Path $dockerExe))

# ---------- 1. WSL2 ----------
$wsl = Join-Path $env:SystemRoot 'System32\wsl.exe'
for ($i = 1; $i -le 3; $i++) {
    $out = & $wsl --status 2>&1 | Out-String
    if ($out -notmatch 'REGDB_E_CLASSNOTREG' -and $out -notmatch 'error') { break }
    Log "wsl not ready (attempt $i): $($out.Trim())"
    if (IsAdmin) {
        & $wsl --update 2>&1 | ForEach-Object { Log "wsl-update: $_" }
    } else {
        Log 'not elevated: skipping wsl --update'
    }
    Start-Sleep -Seconds 5
}
& $wsl --status 2>&1 | ForEach-Object { Log "wsl: $_" }
& $wsl --list --verbose 2>&1 | ForEach-Object { Log "wsl-distro: $_" }
if (IsAdmin) { & $wsl --set-default-version 2 2>&1 | Out-Null }

# ---------- 2. Start Docker Desktop ----------
$dd = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
if (Test-Path $dd) {
    if (-not (Get-Process 'Docker Desktop' -ErrorAction SilentlyContinue)) {
        Log 'starting Docker Desktop...'
        Start-Process -FilePath $dd
    } else { Log 'Docker Desktop already running' }
} else {
    Log 'ERROR: Docker Desktop is not installed. Run scripts\install-docker3.ps1 elevated first.'
    exit 1
}

# ---------- 3. Wait for the engine ----------
$ok = $false
for ($i = 1; $i -le 90; $i++) {
    if (DockerInfo) { $ok = $true; Log "docker engine ready after $($i*5)s"; break }
    Start-Sleep -Seconds 5
}
if (-not $ok) {
    Log 'engine not ready, cycling WSL and retrying once...'
    & $wsl --shutdown 2>&1 | Out-Null
    Start-Sleep -Seconds 8
    Start-Process -FilePath $dd
    for ($i = 1; $i -le 60; $i++) {
        if (DockerInfo) { $ok = $true; Log "docker engine ready (retry) after $($i*5)s"; break }
        Start-Sleep -Seconds 5
    }
}
if (-not $ok) {
    Log 'ABORT: docker engine unavailable. Open Docker Desktop > Troubleshoot and check WSL2.'
    Log '--- docker desktop logs (tail) ---'
    if (Test-Path $dockerExe) { & $dockerExe desktop logs --tail 40 2>&1 | ForEach-Object { Log "ddlog: $_" } }
    exit 1
}
& $dockerExe version --format 'server={{.Server.Version}}' 2>&1 | ForEach-Object { Log "docker: $_" }

# ---------- 4. Base image pull (checks registry mirror) ----------
Log 'pulling ubuntu:22.04 (mirror check)...'
& $dockerExe pull ubuntu:22.04 2>&1 | ForEach-Object { Log "pull: $_" }
$pullCode = $LASTEXITCODE
Log "pull exit code: $pullCode"

# ---------- 5. Build the sandbox image ----------
Push-Location $root
Log 'building ctf-sandbox image (30-60+ minutes)...'
$buildArgs = @()
if ($pullCode -ne 0) { $buildArgs += @('--build-arg', 'UBUNTU_MIRROR=mirrors.aliyun.com') }
& $dockerExe build -f sandbox/Dockerfile.sandbox -t ctf-sandbox @buildArgs . 2>&1 | ForEach-Object { Log "build: $_" }
$buildCode = $LASTEXITCODE
Log "build exit code: $buildCode"

# ---------- 6. Smoke test ----------
if ($buildCode -eq 0) {
    Log 'smoke test: import pwn / z3 / angr / sagemath'
    & $dockerExe run --rm ctf-sandbox bash -lc "python3 -c 'import pwn, z3, angr; print(pwn.__version__)'; sage --version" 2>&1 | ForEach-Object { Log "smoke: $_" }
    Log ("smoke exit code: " + $LASTEXITCODE)
}
Pop-Location
Log '=== post-reboot setup finished ==='
