param(
  [string]$Server = "kadin@100.79.132.39",
  [int]$LocalPort = 18100,
  [int]$RemotePort = 18100
)

$ErrorActionPreference = "Stop"

$existing = Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction SilentlyContinue
if ($existing) {
  Write-Host "Local port $LocalPort is already listening. Tunnel may already be running."
  exit 0
}

$args = @(
  "-N",
  "-L",
  "${LocalPort}:127.0.0.1:${RemotePort}",
  $Server
)

Start-Process -FilePath "ssh" -ArgumentList $args -WindowStyle Hidden
Start-Sleep -Seconds 2

$ready = Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction SilentlyContinue
if ($ready) {
  Write-Host "Jarvis Chat tunnel is listening on http://127.0.0.1:$LocalPort"
} else {
  Write-Host "Tunnel process started, but port $LocalPort is not listening yet. Check SSH auth/connectivity."
}
