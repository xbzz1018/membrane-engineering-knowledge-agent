param(
    [string]$PythonExe = "F:\code\homework\conda-envs\agent-membrane\python.exe",
    [int]$Port = 8080
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$logRoot = Join-Path $root "data\runtime"
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
$stdout = Join-Path $logRoot "uvicorn.stdout.log"
$stderr = Join-Path $logRoot "uvicorn.stderr.log"
Start-Process -FilePath $PythonExe -ArgumentList "-m", "uvicorn", "src.main:app", "--host", "127.0.0.1", "--port", "$Port" -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr | Select-Object Id
