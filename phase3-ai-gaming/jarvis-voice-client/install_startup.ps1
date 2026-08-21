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

try {
  $launcher = Join-Path $ClientDir "start_tray.ps1"
  $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$launcher`" -NoWindow" -WorkingDirectory $ClientDir
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
  $shortcut.TargetPath = "powershell.exe"
  $shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$launcher`" -NoWindow"
  $shortcut.WorkingDirectory = $ClientDir
  $shortcut.WindowStyle = 7
  $shortcut.Description = "Jarvis voice tray client"
  $shortcut.Save()
  Write-Host "Scheduled task was unavailable, so installed startup shortcut: $shortcutPath"
}
