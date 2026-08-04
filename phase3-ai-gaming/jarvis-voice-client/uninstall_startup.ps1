param(
  [string]$TaskName = "JarvisVoiceClient"
)

$ErrorActionPreference = "Stop"

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
  Write-Host "Removed startup task $TaskName."
} else {
  Write-Host "Startup task $TaskName was not installed."
}

$shortcutPath = Join-Path ([Environment]::GetFolderPath("Startup")) "Jarvis Voice Client.lnk"
if (Test-Path $shortcutPath) {
  Remove-Item -LiteralPath $shortcutPath -Force
  Write-Host "Removed startup shortcut $shortcutPath."
}
