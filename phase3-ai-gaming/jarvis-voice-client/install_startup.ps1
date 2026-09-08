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
$Client = Join-Path $ClientDir "client.py"
$EnvPath = Join-Path $ClientDir ".env"
$IconPath = Join-Path $ClientDir "jarvis-core.ico"

if (-not $PythonPath) {
  $PythonPath = Join-Path $ClientDir ".venv\Scripts\pythonw.exe"
  if (-not (Test-Path $PythonPath)) {
    $PythonPath = Join-Path $ClientDir ".venv\Scripts\python.exe"
  }
}

if (-not (Test-Path $PythonPath)) {
  throw "Jarvis voice client Python runtime is missing. Run setup first, then rerun install_startup.ps1."
}

try {
  $action = New-ScheduledTaskAction -Execute $PythonPath -Argument "`"$Client`" --tray --env `"$EnvPath`"" -WorkingDirectory $ClientDir
  $trigger = New-ScheduledTaskTrigger -AtLogOn
  $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
  $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
  Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force -ErrorAction Stop | Out-Null
  Write-Host "Installed startup task $TaskName for Jarvis voice client."
} catch {
  $launcher = Join-Path $ClientDir "start_tray.ps1"
  $startup = [Environment]::GetFolderPath("Startup")
  $shortcutPath = Join-Path $startup "Jarvis Voice Client.lnk"
  $shell = New-Object -ComObject WScript.Shell
  $shortcut = $shell.CreateShortcut($shortcutPath)
  $shortcut.TargetPath = $PythonPath
  $shortcut.Arguments = "`"$Client`" --tray --env `"$EnvPath`""
  $shortcut.WorkingDirectory = $ClientDir
  $shortcut.WindowStyle = 7
  $shortcut.Description = "Jarvis voice tray client"
  if (Test-Path $IconPath) {
    $shortcut.IconLocation = $IconPath
  }
  $shortcut.Save()
  Write-Host "Scheduled task was unavailable, so installed startup shortcut: $shortcutPath"
}
