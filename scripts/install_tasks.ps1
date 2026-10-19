# Crée deux tâches planifiées Windows qui démarrent à l'ouverture de la session :
#   ForexBot-Bot        -> le bot (qui lance lui-même MetaTrader 5 via MT5_PATH)
#   ForexBot-Dashboard  -> le tableau de bord sur http://127.0.0.1:8000
# et une tâche quotidienne ForexBot-Report (bilan Discord à 22 h).
# Désinstallation : scripts\uninstall_tasks.ps1
param([switch]$NoStart)

$root = Split-Path -Parent $PSScriptRoot
$supervisor = Join-Path $PSScriptRoot "supervise.ps1"
if (-not (Test-Path (Join-Path $root ".venv\Scripts\forex-bot.exe"))) {
    throw "Environnement introuvable : lancez d'abord 'python -m uv sync --extra mt5' dans $root"
}

$user = "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew -StartWhenAvailable
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

foreach ($task in @(
        @{ Name = "ForexBot-Bot"; Command = "run"; Description = "Bot de trading forex (forex-bot run)" },
        @{ Name = "ForexBot-Dashboard"; Command = "api"; Description = "Tableau de bord du bot forex (http://127.0.0.1:8000)" }
    )) {
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -WorkingDirectory $root -Argument (
        "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$supervisor`" -Command $($task.Command)")
    Register-ScheduledTask -TaskName $task.Name -Description $task.Description -Action $action `
        -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
    Write-Host "Tâche $($task.Name) installée."
    if (-not $NoStart) {
        Start-ScheduledTask -TaskName $task.Name
        Write-Host "Tâche $($task.Name) démarrée."
    }
}

# Bilan quotidien sur Discord à 22 h (heure du PC). Si le PC dort à 22 h, il part au réveil.
$exe = Join-Path $root ".venv\Scripts\forex-bot.exe"
$reportLog = Join-Path $root "data\logs\report.log"
$reportAction = New-ScheduledTaskAction -Execute "powershell.exe" -WorkingDirectory $root -Argument (
    "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command " +
    "`"`$env:LOG_FILE='$reportLog'; & '$exe' report`"")
$reportSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName "ForexBot-Report" -Description "Bilan quotidien du bot forex sur Discord" `
    -Action $reportAction -Trigger (New-ScheduledTaskTrigger -Daily -At "22:00") `
    -Settings $reportSettings -Principal $principal -Force | Out-Null
Write-Host "Tâche ForexBot-Report installée (tous les jours à 22:00)."
