# Repair WSL runtime (missing WSLService / C:\Program Files\WSL) by installing the official MSI.
# Run elevated:  powershell -ExecutionPolicy Bypass -File F:\ctf_agent\scripts\fix-wsl.ps1

$ErrorActionPreference = "Continue"
$log = "F:\ctf_agent\logs\fix-wsl.log"
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
Start-Transcript -Path $log -Append -Force

function Show-Section($t) { Write-Output ""; Write-Output "==== $t ====" }

function Invoke-WithTimeout {
    param([string]$Label, [string]$Exe, [string]$Arguments, [int]$TimeoutSeconds = 60)
    $job = Start-Job -ScriptBlock {
        param($e, $a)
        & $e $a.Split(" ") 2>&1 | Out-String
    } -ArgumentList $Exe, $Arguments
    if (Wait-Job $job -Timeout $TimeoutSeconds) {
        Receive-Job $job | Write-Output
    } else {
        Write-Output "TIMEOUT after ${TimeoutSeconds}s: $Label"
        Stop-Job $job
    }
    Remove-Job $job -Force -ErrorAction SilentlyContinue
}

Show-Section "features"
foreach ($f in @("VirtualMachinePlatform", "Microsoft-Windows-Subsystem-Linux")) {
    try {
        Get-WindowsOptionalFeature -Online -FeatureName $f |
            Select-Object FeatureName, State | Format-List | Out-String | Write-Output
    } catch {
        Write-Output "feature ${f} query failed: $($_.Exception.Message)"
    }
}

Show-Section "start vmcompute"
Start-Service vmcompute -ErrorAction Continue
Get-Service vmcompute | Select-Object Name, Status, StartType | Format-List | Out-String | Write-Output

Show-Section "install WSL MSI"
$msi = "F:\ctf_agent\installers\wsl.2.7.10.0.x64.msi"
$msiExit = -1
if (-not (Test-Path $msi)) {
    Write-Output "MSI missing: $msi"
} else {
    Write-Output ("MSI size: {0:N0} bytes" -f (Get-Item $msi).Length)
    $p = Start-Process msiexec.exe -Wait -PassThru -ArgumentList @(
        "/i", "`"$msi`"", "/qn", "/norestart",
        "/l*v", "`"F:\ctf_agent\logs\wsl-msi.log`""
    )
    $msiExit = $p.ExitCode
    Write-Output "msiexec exit code: $msiExit"
}

Show-Section "C:\Program Files\WSL"
Get-ChildItem "C:\Program Files\WSL" -ErrorAction SilentlyContinue |
    Select-Object Name, Length | Format-Table -AutoSize | Out-String | Write-Output

Show-Section "WSLService"
Get-Service WSLService -ErrorAction SilentlyContinue |
    Format-List Name, Status, StartType | Out-String | Write-Output

Show-Section "wsl --version"
$exe = "C:\Program Files\WSL\wsl.exe"
if (-not (Test-Path $exe)) { $exe = "$env:SystemRoot\System32\wsl.exe" }
Invoke-WithTimeout -Label "wsl --version" -Exe $exe -Arguments "--version" -TimeoutSeconds 60

Show-Section "wsl --status"
Invoke-WithTimeout -Label "wsl --status" -Exe $exe -Arguments "--status" -TimeoutSeconds 60

Show-Section "wsl -l -v"
Invoke-WithTimeout -Label "wsl -l -v" -Exe $exe -Arguments "-l -v" -TimeoutSeconds 60

Stop-Transcript
Write-Output "DONE msi_exit=$msiExit"
exit $(if ($msiExit -eq 0 -or $msiExit -eq 3010) { 0 } else { 1 })
