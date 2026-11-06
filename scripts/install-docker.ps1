# Elevated installer: enables WSL2 + installs Docker Desktop for ctf-agent.
# Must be run from an ADMIN PowerShell. Logs to F:\ctf_agent\logs\install-docker.log
$ErrorActionPreference = 'Continue'
$log = 'F:\ctf_agent\logs\install-docker.log'
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null

function Log($m) {
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    "$ts  $m" | Tee-Object -FilePath $log -Append | Out-Null
    Write-Host "$ts  $m"
}

Log '=== elevated Docker/WSL install start ==='
Log ("user     : " + (whoami))
Log ("is admin : " + ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))

# --- 1. Enable WSL + Virtual Machine Platform (required by Docker Desktop WSL2 backend)
foreach ($f in @('VirtualMachinePlatform', 'Microsoft-Windows-Subsystem-Linux')) {
    try {
        $r = Enable-WindowsOptionalFeature -Online -FeatureName $f -All -NoRestart -ErrorAction Stop
        Log "feature $f -> RestartNeeded=$($r.RestartNeeded)"
    } catch {
        Log "feature $f FAILED: $($_.Exception.Message)"
    }
}

# --- 2. Update WSL2 kernel (best effort; may need reboot first)
try {
    $wsl = Join-Path $env:SystemRoot 'System32\wsl.exe'
    if (Test-Path $wsl) {
        & $wsl --update 2>&1 | ForEach-Object { Log "wsl: $_" }
        & $wsl --set-default-version 2 2>&1 | ForEach-Object { Log "wsl: $_" }
    } else { Log 'wsl.exe not found' }
} catch { Log "wsl update failed: $($_.Exception.Message)" }

# --- 3. Install Docker Desktop silently with WSL2 backend
try {
    Log 'installing Docker Desktop via winget (this downloads ~700MB)...'
    $out = & winget install --id Docker.DockerDesktop -e --silent --accept-package-agreements --accept-source-agreements `
        --override 'install --quiet --accept-license --backend=wsl-2' 2>&1
    $out | ForEach-Object { Log "winget: $_" }
} catch { Log "winget FAILED: $($_.Exception.Message)" }

# --- 4. Allow current user to use the Docker engine without admin
try {
    $u = "$env:USERDOMAIN\$env:USERNAME"
    $m = net localgroup docker-users $u /add 2>&1
    $m | ForEach-Object { Log "net: $_" }
} catch { Log "docker-users group add failed: $($_.Exception.Message)" }

# --- 5. Final status
Log ("Docker Desktop exe present: " + (Test-Path 'C:\Program Files\Docker\Docker\Docker Desktop.exe'))
Log ("docker CLI present       : " + [bool](Get-Command docker -ErrorAction SilentlyContinue))
Log '=== elevated install finished ==='
