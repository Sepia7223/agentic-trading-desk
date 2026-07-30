# One-click dashboard access from any machine on the LAN.
# The Operations Center binds loopback-only on the mini PC (governance
# rule); this opens a secure SSH tunnel and launches the browser.
#
# Usage:  powershell -File scripts\open_dashboard.ps1
param(
    [string]$MiniPc = "gusanio@10.0.0.8",
    [string]$Key = "$env:USERPROFILE\.ssh\id_ed25519_minipc",
    [int]$LocalPort = 8000
)
$tunnel = Start-Process ssh -ArgumentList @(
    "-i", $Key, "-N",
    "-L", "$($LocalPort):127.0.0.1:8000",
    $MiniPc
) -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 2
Start-Process "http://localhost:$LocalPort"
Write-Host "Dashboard tunnel open (pid $($tunnel.Id)). Close it with:"
Write-Host "  Stop-Process -Id $($tunnel.Id)"
