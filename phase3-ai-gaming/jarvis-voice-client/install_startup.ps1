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

try {
  $client = Join-Path $ClientDir "client.py"
  $action = New-ScheduledTaskAction -Execute $PythonPath -Argument "`"$client`" --tray --env `"$ClientDir\.env`"" -WorkingDirectory $ClientDir
  $trigger = New-ScheduledTaskTrigger -AtLogOn
  $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
  $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
  Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force -ErrorAction Stop | Out-Null
  Write-Host "Installed startup task $TaskName for Jarvis voice client."
} catch {
  $client = Join-Path $ClientDir "client.py"
  $startup = [Environment]::GetFolderPath("Startup")
  $shortcutPath = Join-Path $startup "Jarvis Voice Client.lnk"
  $shell = New-Object -ComObject WScript.Shell
  $shortcut = $shell.CreateShortcut($shortcutPath)
  $shortcut.TargetPath = $PythonPath
  $shortcut.Arguments = "`"$client`" --tray --env `"$ClientDir\.env`""
  $shortcut.WorkingDirectory = $ClientDir
  $shortcut.WindowStyle = 7
  $shortcut.Description = "Jarvis voice tray client"
  $shortcut.Save()
  Write-Host "Scheduled task was unavailable, so installed startup shortcut: $shortcutPath"
}
