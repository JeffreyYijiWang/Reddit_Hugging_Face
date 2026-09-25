$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$statusPath = Join-Path $taskRoot 'data\state\full_run_status.json'
if (Test-Path -LiteralPath $statusPath) {
    $scanStatus = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
    if ($scanStatus.state -in @('running', 'exporting')) {
        $existingScan = Get-Process -Id $scanStatus.pid -ErrorAction SilentlyContinue
        if ($existingScan) {
            Write-Output "A scan is already running with PID $($scanStatus.pid)."
            exit 0
        }
    }
}
if (Test-Path -LiteralPath (Join-Path $taskRoot 'data\state\stop_requested')) {
    throw 'A stop marker is present. Remove that single marker only when intentionally resuming.'
}
$scanProcess = Start-Process -FilePath (Join-Path $taskRoot '.venv-research\Scripts\python.exe') -ArgumentList '-u','-m','reddit_reid','run-full','--config','config.yaml','--resume' -WorkingDirectory $taskRoot -RedirectStandardOutput (Join-Path $taskRoot 'data\logs\full-run-active-console.txt') -RedirectStandardError (Join-Path $taskRoot 'data\logs\full-run-active-errors.txt') -WindowStyle Hidden -PassThru
$scanProcess.Id | Set-Content -LiteralPath (Join-Path $taskRoot 'data\state\full_run.pid')
Write-Output "Started launcher PID $($scanProcess.Id). The actual worker PID is in full_run_status.json."
