# Shrink Docker Desktop's WSL disk (docker_data.vhdx) to give space back to C:.
#
# Run as Administrator (right-click → Run with PowerShell, or from an elevated
# PowerShell: powershell -ExecutionPolicy Bypass -File compact-docker-disk.ps1).
#
# Safe: images, containers and volumes stay inside the disk; only the unused
# blocks are released. Run `docker builder prune -af` first so there is
# something to release. It stops Docker Desktop and all WSL distros while it
# runs, then starts Docker Desktop again.

$ErrorActionPreference = "Stop"

$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Please run this script as Administrator." -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}

$vhdx = Join-Path $env:LOCALAPPDATA "Docker\wsl\disk\docker_data.vhdx"
if (-not (Test-Path $vhdx)) {
    # When elevated as another account, fall back to the interactive user's profile.
    $vhdx = Get-ChildItem "C:\Users\*\AppData\Local\Docker\wsl\disk\docker_data.vhdx" -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $vhdx) { throw "docker_data.vhdx not found" }

$before = (Get-Item $vhdx).Length / 1GB
Write-Host ("Disk: {0}  ({1:N2} GB)" -f $vhdx, $before)

Write-Host "Stopping Docker Desktop..."
Get-Process "Docker Desktop", "com.docker.backend", "com.docker.build" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 5
Write-Host "Shutting down WSL..."
wsl --shutdown
Start-Sleep -Seconds 5

$script = Join-Path $env:TEMP "compact-docker-vhdx.txt"
@"
select vdisk file="$vhdx"
attach vdisk readonly
compact vdisk
detach vdisk
exit
"@ | Set-Content -Path $script -Encoding ascii

Write-Host "Compacting (can take several minutes)..."
diskpart /s $script
Remove-Item $script -ErrorAction SilentlyContinue

$after = (Get-Item $vhdx).Length / 1GB
Write-Host ("Done: {0:N2} GB -> {1:N2} GB (freed {2:N2} GB)" -f $before, $after, ($before - $after)) -ForegroundColor Green

$desktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
if (Test-Path $desktop) {
    Write-Host "Starting Docker Desktop..."
    Start-Process $desktop
}
Read-Host "Press Enter to close"
