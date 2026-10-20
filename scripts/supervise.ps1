# Lance "forex-bot run" (le bot) ou "forex-bot api" (le tableau de bord) et le relance
# s'il s'arrête. Utilisé par les tâches planifiées créées par install_tasks.ps1.
param(
    [ValidateSet("run", "api")]
    [string]$Command = "run"
)

$root = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $root ".venv\Scripts\forex-bot.exe"
$logs = Join-Path $root "data\logs"
New-Item -ItemType Directory -Force $logs | Out-Null

$env:LOG_FILE = Join-Path $logs "$Command.log"
$env:PYTHONIOENCODING = "utf-8"
$arguments = if ($Command -eq "api") { "api --host 127.0.0.1 --port 8000" } else { "run" }
$supervisorLog = Join-Path $logs "supervisor-$Command.log"
$pidFile = Join-Path $logs "$Command.pid"

# Si la tâche a été arrêtée puis relancée, l'ancien forex-bot tourne peut-être encore :
# on le ferme pour ne jamais avoir deux bots en même temps. Son numéro de processus est
# dans le fichier .pid (plus fiable et bien plus rapide qu'une recherche WMI).
if (Test-Path $pidFile) {
    $old = Get-Process -Id ([int](Get-Content $pidFile -Raw)) -ErrorAction SilentlyContinue
    if ($old -and $old.ProcessName -eq "forex-bot") { Stop-Process -Id $old.Id -Force }
}

while ($true) {
    Add-Content $supervisorLog "$(Get-Date -Format s) démarrage de forex-bot $Command"
    $process = Start-Process -FilePath $exe -ArgumentList $arguments -WorkingDirectory $root `
        -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logs "$Command.stdout.log") `
        -RedirectStandardError (Join-Path $logs "$Command.stderr.log")
    $null = $process.Handle  # nécessaire pour lire ExitCode après la fin du processus
    Set-Content $pidFile $process.Id
    $process.WaitForExit()
    Add-Content $supervisorLog "$(Get-Date -Format s) forex-bot $Command arrêté (code $($process.ExitCode)), relance dans 60 s"
    Start-Sleep -Seconds 60
}
