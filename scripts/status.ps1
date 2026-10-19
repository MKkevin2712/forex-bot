# État des tâches, des processus et dernières lignes du journal du bot.
$root = Split-Path -Parent $PSScriptRoot
Get-ScheduledTask -TaskName "ForexBot-*" -ErrorAction SilentlyContinue |
    Select-Object TaskName, State | Format-Table -AutoSize
Get-Process forex-bot -ErrorAction SilentlyContinue |
    Select-Object Id, StartTime | Format-Table -AutoSize
$log = Join-Path $root "data\logs\run.log"
if (Test-Path $log) {
    Write-Host "--- Dernières lignes de $log ---"
    Get-Content $log -Tail 15 -Encoding UTF8
}
