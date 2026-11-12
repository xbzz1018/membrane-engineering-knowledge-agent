param(
    [string]$PythonExe = 'F:\code\homework\conda-envs\agent-membrane\python.exe',
    [int]$Port = 8080,
    [int]$FrontendPort = 5173,
    [switch]$NoFrontend,
    [switch]$Temporal,
    [int]$TemporalPort = 17233,
    [switch]$Mcp
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runtime = Join-Path $root 'data\runtime'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
if (-not (Test-Path -LiteralPath $PythonExe)) { throw "Python not found: $PythonExe" }
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    throw "Port $Port is already in use. Inspect the existing service first."
}
if ($Mcp -and (Get-NetTCPConnection -LocalPort 8090 -State Listen -ErrorAction SilentlyContinue)) {
    throw 'MCP port 8090 is occupied. Inspect the existing service first.'
}

$env:RUNTIME_MODE = 'local'
$env:MODEL_MODE = 'fake'
$env:MODEL_PROVIDER = 'fake'
$env:RERANKER_ENABLED = 'false'
$env:PARSER_MODE = 'basic'
$env:TEMPORAL_ENABLED = if ($Temporal) { 'true' } else { 'false' }
$env:AUTH_ENABLED = 'false'
$env:DATABASE_URL = ''
$env:LOCAL_DB_PATH = 'data/runtime/demo.db'
if ($Temporal) {
    $temporalExe = Join-Path $runtime 'temporal-bin\temporal-sdk-python-1.32.0.exe'
    if (-not (Test-Path -LiteralPath $temporalExe)) {
        throw 'Temporal CLI missing. Run scripts/validate_temporal_local.py once to download and validate it.'
    }
    if (Get-NetTCPConnection -LocalPort $TemporalPort -State Listen -ErrorAction SilentlyContinue) {
        throw "Temporal port $TemporalPort is occupied. Inspect the existing service first."
    }
    $temporalRuntime = Join-Path $runtime 'temporal-demo-v3'
    New-Item -ItemType Directory -Force -Path $temporalRuntime | Out-Null
    $env:LOCAL_DB_PATH = 'data/runtime/temporal-demo-v3/business.db'
    $env:TEMPORAL_TARGET = "127.0.0.1:$TemporalPort"
    $env:TEMPORAL_TASK_QUEUE = 'resume-demo-v3-orchestration'
    $env:TEMPORAL_PARSE_TASK_QUEUE = 'resume-demo-v3-parse'
    $env:TEMPORAL_REVIEW_TASK_QUEUE = 'resume-demo-v3-review'
    $env:TEMPORAL_MAINTENANCE_TASK_QUEUE = 'resume-demo-v3-maintenance'
    $env:TEMPORAL_ACTIVITY_TEST_DELAY_SECONDS = '0'
}
$env:LOCAL_UPLOAD_PATH = 'data/uploads'
$env:PYTHONIOENCODING = 'utf-8'
$env:VITE_API_BASE_URL = "http://127.0.0.1:$Port"
$env:NO_PROXY = '127.0.0.1,localhost'

$api = Start-Process -FilePath $PythonExe -ArgumentList @(
    '-m', 'uvicorn', 'src.main:app', '--host', '127.0.0.1', '--port', "$Port"
) -WorkingDirectory $root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $runtime 'api.stdout.log') `
    -RedirectStandardError (Join-Path $runtime 'api.stderr.log')
$state = @{
    api_pid = $api.Id; api_started_ticks = "$($api.StartTime.ToUniversalTime().Ticks)"
    api_url = "http://127.0.0.1:$Port"; frontend_pid = $null
}
$statePath = Join-Path $runtime 'demo-processes.json'
$state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8

if (-not $NoFrontend) {
    $vite = Join-Path $root 'frontend\node_modules\vite\bin\vite.js'
    if (-not (Test-Path -LiteralPath $vite)) {
        throw 'Frontend dependencies missing. Run npm ci in frontend, or use -NoFrontend.'
    }
    if (Get-NetTCPConnection -LocalPort $FrontendPort -State Listen -ErrorAction SilentlyContinue) {
        throw "Frontend port $FrontendPort is already in use."
    }
    $node = (Get-Command node.exe -ErrorAction Stop).Source
    $quotedVite = '"' + $vite + '"'
    $frontend = Start-Process -FilePath $node -ArgumentList @(
        $quotedVite, '--host', '127.0.0.1', '--port', "$FrontendPort", '--strictPort', '--configLoader', 'runner'
    ) -WorkingDirectory (Join-Path $root 'frontend') -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $runtime 'frontend.stdout.log') `
        -RedirectStandardError (Join-Path $runtime 'frontend.stderr.log')
    $state.frontend_pid = $frontend.Id
    $state.frontend_started_ticks = "$($frontend.StartTime.ToUniversalTime().Ticks)"
    $state.frontend_url = "http://127.0.0.1:$FrontendPort"
    $state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8
}

$ready = $false
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    if ($api.HasExited) { throw "API exited. Inspect $runtime\api.stderr.log" }
    try {
        $health = Invoke-RestMethod -Uri "$($state.api_url)/health" -TimeoutSec 2
        if ($health.status -eq 'ok') { $ready = $true; break }
    } catch { Start-Sleep -Milliseconds 500 }
}
if (-not $ready) { throw "API not ready. Inspect $runtime\api.stderr.log" }
if ($Temporal) {
    $temporalDb = '"' + (Join-Path $temporalRuntime 'temporal.db') + '"'
    $temporalProcess = Start-Process -FilePath $temporalExe -ArgumentList @(
        'server', 'start-dev', '--headless', '--ip', '127.0.0.1', '--port', "$TemporalPort",
        '--db-filename', $temporalDb
    ) -WorkingDirectory $root -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $runtime 'temporal.stdout.log') `
        -RedirectStandardError (Join-Path $runtime 'temporal.stderr.log')
    $state.temporal_pid = $temporalProcess.Id
    $state.temporal_started_ticks = "$($temporalProcess.StartTime.ToUniversalTime().Ticks)"
    $state.temporal_target = $env:TEMPORAL_TARGET
    $state.mode = 'local-fake-with-real-temporal'
    $state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8
    $temporalReady = $false
    for ($attempt = 0; $attempt -lt 50; $attempt++) {
        if ($temporalProcess.HasExited) { throw "Temporal exited. Inspect $runtime\temporal.stderr.log" }
        $socket = [System.Net.Sockets.TcpClient]::new()
        try { $socket.Connect('127.0.0.1', $TemporalPort); $temporalReady = $true; break }
        catch { Start-Sleep -Milliseconds 300 }
        finally { $socket.Dispose() }
    }
    if (-not $temporalReady) { throw 'Temporal did not become ready.' }
    $worker = Start-Process -FilePath $PythonExe -ArgumentList @('scripts/run_temporal_worker.py') `
        -WorkingDirectory $root -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $runtime 'worker.stdout.log') `
        -RedirectStandardError (Join-Path $runtime 'worker.stderr.log')
    $state.worker_pid = $worker.Id
    $state.worker_started_ticks = "$($worker.StartTime.ToUniversalTime().Ticks)"
    $state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8
}
if ($Mcp) {
    $mcpProcess = Start-Process -FilePath $PythonExe -ArgumentList @(
        '-m', 'src.mcp.server', '--transport', 'streamable-http'
    ) -WorkingDirectory $root -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $runtime 'mcp.stdout.log') `
        -RedirectStandardError (Join-Path $runtime 'mcp.stderr.log')
    $state.mcp_pid = $mcpProcess.Id
    $state.mcp_started_ticks = "$($mcpProcess.StartTime.ToUniversalTime().Ticks)"
    $state.mcp_url = 'http://127.0.0.1:8090/mcp'
    $state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8
}
$state | ConvertTo-Json
