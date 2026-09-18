param(
    [string]$PythonExe = "F:\code\homework\conda-envs\agent-membrane\python.exe",
    [ValidateSet("stdio", "streamable-http")]
    [string]$Transport = "streamable-http"
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ($Transport -eq "stdio") {
    & $PythonExe -m src.mcp.server --transport stdio
    exit $LASTEXITCODE
}
$logRoot = Join-Path $root "data\runtime"
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
Start-Process -FilePath $PythonExe `
    -ArgumentList "-m", "src.mcp.server", "--transport", "streamable-http" `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logRoot "mcp.stdout.log") `
    -RedirectStandardError (Join-Path $logRoot "mcp.stderr.log") |
    Select-Object Id
