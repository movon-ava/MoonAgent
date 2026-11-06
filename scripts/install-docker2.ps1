# Phase 2 (elevated): kill the stuck wsl --update, install Docker Desktop, grant docker-users.
$ErrorActionPreference = 'Continue'
$log = 'F:\ctf_agent\logs\install-docker.log'
function Log($m) {
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    "$ts  $m" | Tee-Object -FilePath $log -Append | Out-Null
    Write-Host "$ts  $m"
}

Log '=== phase 2 start (docker desktop) ==='
Log ("is admin : " + ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))

# kill the hung phase-1 script + its wsl.exe / conhost children
foreach ($id in 53056, 50660, 52580, 53052) {
    $p = Get-Process -Id $id -ErrorAction SilentlyContinue
    if ($p) {
        Log "killing PID $id ($($p.Name))"
        Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Seconds 2

# confirm feature state (pending reboot is expected)
try {
    foreach ($f in @('VirtualMachinePlatform', 'Microsoft-Windows-Subsystem-Linux')) {
        $s = Get-WindowsOptionalFeature -Online -FeatureName $f -ErrorAction Stop
        Log "feature $f = $($s.State)"
    }
} catch { Log "feature query failed: $($_.Exception.Message)" }

# Docker Desktop install (silent, WSL2 backend)
Log 'running: winget install Docker.DockerDesktop ...'
$out = & winget install --id Docker.DockerDesktop -e --silent --accept-package-agreements --accept-source-agreements --disable-interactivity --override 'install --quiet --accept-license --backend=wsl-2' 2>&1
$out | ForEach-Object { Log "winget: $_" }
Log "winget exit code: $LASTEXITCODE"

# docker-users group
try {
    $u = "$env:USERDOMAIN\$env:USERNAME"
    $m = net localgroup docker-users $u /add 2>&1
    $m | ForEach-Object { Log "net: $_" }
} catch { Log "docker-users group add failed: $($_.Exception.Message)" }

Log ("Docker Desktop exe present: " + (Test-Path 'C:\Program Files\Docker\Docker\Docker Desktop.exe'))
Log '=== phase 2 finished ==='
