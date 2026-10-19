# Arrête le bot et le tableau de bord, puis supprime leurs tâches planifiées.
foreach ($name in @("ForexBot-Bot", "ForexBot-Dashboard", "ForexBot-Report")) {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $name
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
        Write-Host "Tâche $name supprimée."
    }
}
# Le superviseur lance forex-bot.exe dans un processus séparé : on l'arrête aussi.
Get-Process forex-bot -ErrorAction SilentlyContinue | Stop-Process -Force
Write-Host "Bot et tableau de bord arrêtés (MetaTrader 5 reste ouvert)."
