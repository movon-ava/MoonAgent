# Phase 3: run the directly-downloaded Docker Desktop installer (elevated).
$ErrorActionPreference = 'Continue'
$root = 'F:\ctf_agent'
$log  = Join-Path $root 'logs\install-docker.log'
function Log($m) {
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    "$ts  $m" | Tee-Object -FilePath $log -Append | Out-Null
    Write-Host "$ts  $m"
}

Log '=== phase 3 start (direct installer) ==='
Log ("admin = " + ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))

# Stop the stuck winget / DeliveryOptimization download
Get-Process winget -ErrorAction SilentlyContinue | ForEach-Object { Log "killing winget PID $($_.Id)"; Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
Get-Service DoSvc -ErrorAction SilentlyContinue | ForEach-Object { Log "DoSvc status: $($_.Status)" }

$exe = Join-Path $root 'installers\DockerDesktopInstaller.exe'
if (-not (Test-Path $exe)) { Log "ERROR: installer missing at $exe"; exit 2 }
$sizeMB = [math]::Round((Get-Item $exe).Length / 1MB, 0)
Log "installer size: $sizeMB MB"
if ($sizeMB -lt 300) { Log 'ERROR: installer looks truncated (<300MB)'; exit 3 }

Log 'running: DockerDesktopInstaller.exe install --quiet --accept-license --backend=wsl-2'
& $exe install --quiet --accept-license --backend=wsl-2 2>&1 | ForEach-Object { Log "installer: $_" }
$code = $LASTEXITCODE
Log "installer exit code: $code (0=ok, 3010=reboot required)"

$dd = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
Log ("Docker Desktop.exe present: " + (Test-Path $dd))

# Make sure the current user is allowed to use Docker without elevation
try {
    $grp = Get-LocalGroup -Name 'docker-users' -ErrorAction Stop
    $me  = "$env:USERDOMAIN\$env:USERNAME"
    $members = Get-LocalGroupMember -Group 'docker-users' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name
    if ($members -contains $me -or $members -contains $env:USERNAME) { Log "docker-users already contains $me" }
    else { Add-LocalGroupMember -Group 'docker-users' -Member $me -ErrorAction Stop; Log "added $me to docker-users" }
} catch { Log "docker-users: $($_.Exception.Message)" }

Log '=== phase 3 done ==='
exit $code
