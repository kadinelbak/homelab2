param(
  [switch]$NoWindow
)

$ErrorActionPreference = "Stop"

$ClientDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ClientDir ".venv\Scripts\python.exe"
$Pythonw = Join-Path $ClientDir ".venv\Scripts\pythonw.exe"
$Client = Join-Path $ClientDir "client.py"
$EnvPath = Join-Path $ClientDir ".env"

if (-not (Test-Path $Python)) {
  throw "Jarvis voice client venv is missing. Run: python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
}

if ($NoWindow -and (Test-Path $Pythonw)) {
  Start-Process -FilePath $Pythonw -ArgumentList @($Client, "--tray", "--env", $EnvPath) -WorkingDirectory $ClientDir -WindowStyle Hidden
} else {
  & $Python $Client --tray --env $EnvPath
}
