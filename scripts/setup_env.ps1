param(
    [string]$CondaExe = "conda",
    [string]$EnvRoot = "F:\code\homework\conda-envs\agent-membrane",
    [string]$PackageRoot = "F:\code\homework\conda-pkgs",
    [string]$PipCache = "F:\code\homework\pip-cache",
    [switch]$Minimal
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $EnvRoot | Out-Null
New-Item -ItemType Directory -Force -Path $PackageRoot | Out-Null
New-Item -ItemType Directory -Force -Path $PipCache | Out-Null

$env:CONDA_PKGS_DIRS = $PackageRoot
$env:PIP_CACHE_DIR = $PipCache

if (-not (Test-Path -LiteralPath (Join-Path $EnvRoot "python.exe"))) {
    & $CondaExe create --prefix $EnvRoot python=3.12.13 pip -y
}
& $CondaExe run --prefix $EnvRoot python -m pip install --upgrade pip
$requirements = if ($Minimal) { "requirements-dev.txt" } else { "requirements-full.txt" }
& $CondaExe run --prefix $EnvRoot python -m pip install -r "$(Join-Path $PSScriptRoot "..\$requirements")"

& $CondaExe run --prefix $EnvRoot python -m pip check

Write-Host "Environment ready: $EnvRoot ($requirements)"
