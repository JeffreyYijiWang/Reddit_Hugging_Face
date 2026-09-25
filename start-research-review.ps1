$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$stateFile = Join-Path $taskRoot 'data\state\resumed_research_status.json'
if (Test-Path -LiteralPath $stateFile) {
    $previousRun = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
    if ($previousRun.state -notin @('finished_with_reported_coverage','failed_or_interrupted')) {
        $existingRun = Get-Process -Id $previousRun.pid -ErrorAction SilentlyContinue
        if ($existingRun) { throw "A resumed research run is already active with PID $($previousRun.pid)." }
    }
}
if (Test-Path -LiteralPath (Join-Path $taskRoot 'data\state\stop_requested')) {
    throw 'A stop marker is present; no restart was performed.'
}
$process = Start-Process -FilePath (Join-Path $taskRoot '.venv-research\Scripts\python.exe') -ArgumentList '-u','-m','reddit_reid.resume_review','config.yaml' -WorkingDirectory $taskRoot -RedirectStandardOutput (Join-Path $taskRoot 'data\logs\resumed-research-console.txt') -RedirectStandardError (Join-Path $taskRoot 'data\logs\resumed-research-errors.txt') -WindowStyle Hidden -PassThru
Write-Output "Started research supervisor launcher PID $($process.Id). The actual worker PID and stages are in data/state/resumed_research_status.json."
