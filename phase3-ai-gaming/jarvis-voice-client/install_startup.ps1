param(
  [string]$TaskName = "JarvisVoiceClient",
  [string]$PythonPath = "",
  [string]$ClientDir = ""
)

$ErrorActionPreference = "Stop"

if (-not $ClientDir) {
  $ClientDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}
$ClientDir = Resolve-Path $ClientDir

if (-not $PythonPath) {
  $venvPythonw = Join-Path $ClientDir ".venv\Scripts\pythonw.exe"
  $venvPython = Join-Path $ClientDir ".venv\Scripts\python.exe"
  if (Test-Path $venvPythonw) {
    $PythonPath = $venvPythonw
  } elseif (Test-Path $venvPython) {
    $PythonPath = $venvPython
  } else {
    $PythonPath = "pythonw.exe"
  }
}

$client = Join-Path $ClientDir "client.py"
$action = New-ScheduledTaskAction -Execute $PythonPath -Argument "`"$client`" --listen --env `"$ClientDir\.env`"" -WorkingDirectory $ClientDir
$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel LeastPrivilege
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Write-Host "Installed startup task $TaskName for Jarvis voice client."
