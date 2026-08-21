param(
  [switch]$Console,
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

$Hidden = $NoWindow -or -not $Console

if ($Hidden -and (Test-Path $Pythonw)) {
  Start-Process -FilePath $Pythonw -ArgumentList @($Client, "--worker", "--env", $EnvPath) -WorkingDirectory $ClientDir -WindowStyle Hidden
  exit 0
} elseif ($Hidden) {
  Start-Process -FilePath $Python -ArgumentList @($Client, "--worker", "--env", $EnvPath) -WorkingDirectory $ClientDir -WindowStyle Hidden
  exit 0
} else {
  & $Python $Client --worker --env $EnvPath
}
