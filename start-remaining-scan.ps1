$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$dataRoot = Join-Path $taskRoot 'data_remaining'
$lockPath = Join-Path $dataRoot 'state\runner.lock'
if (Test-Path -LiteralPath $lockPath) {
    $scanLock = Get-Content -LiteralPath $lockPath -Raw | ConvertFrom-Json
    $existingScan = Get-Process -Id $scanLock.pid -ErrorAction SilentlyContinue
    if ($existingScan) { throw "Continuation runner already exists: $($scanLock.pid)" }
}
if (Test-Path -LiteralPath (Join-Path $dataRoot 'state\stop_requested')) {
    throw 'A stop marker is present. Remove this marker only when intentionally resuming.'
}
$scanProcess = Start-Process -FilePath (Join-Path $taskRoot '.venv-research\Scripts\python.exe') -ArgumentList '-u','-m','reddit_reid.remaining','--config',(Join-Path $taskRoot 'config.remaining.yaml') -WorkingDirectory (Join-Path $taskRoot 'remaining_scan\code') -RedirectStandardOutput (Join-Path $dataRoot 'logs\continuation-console.txt') -RedirectStandardError (Join-Path $dataRoot 'logs\continuation-errors.txt') -WindowStyle Hidden -PassThru
$scanProcess.Id | Set-Content -LiteralPath (Join-Path $dataRoot 'state\full_run.pid')
Write-Output "Started remaining-archive scan PID $($scanProcess.Id)."
