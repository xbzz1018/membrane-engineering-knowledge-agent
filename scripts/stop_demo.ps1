$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$statePath = Join-Path $root 'data\runtime\demo-processes.json'
if (-not (Test-Path -LiteralPath $statePath)) { Write-Output 'No saved demo processes.'; exit 0 }
$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
foreach ($kind in @('frontend', 'mcp', 'api', 'worker', 'temporal')) {
    $recordedPid = $state."${kind}_pid"
    $recordedTicks = $state."${kind}_started_ticks"
    if (-not $recordedPid) { continue }
    $process = Get-Process -Id ([int]$recordedPid) -ErrorAction SilentlyContinue
    if (-not $process) { continue }
    if (-not $recordedTicks -or "$($process.StartTime.ToUniversalTime().Ticks)" -ne "$recordedTicks") {
        throw "Saved identity does not match process $recordedPid; inspect it manually."
    }
    Stop-Process -Id $process.Id
    Write-Output "Stopped demo $kind process $recordedPid"
}
