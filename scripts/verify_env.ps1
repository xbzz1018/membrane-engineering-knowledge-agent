param(
    [string]$PythonExe = "F:\code\homework\conda-envs\agent-membrane\python.exe"
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "Project Python was not found: $PythonExe"
}

$expected = [IO.Path]::GetFullPath((Split-Path -Parent $PythonExe))
$probePath = Join-Path $PSScriptRoot "verify_env.py"
$output = & $PythonExe $probePath
$output | Write-Output
if ($LASTEXITCODE -ne 0) { throw "Project environment validation failed" }
$joinedOutput = $output -join [Environment]::NewLine
if ($joinedOutput.IndexOf($expected, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
    throw "Python executable does not use the requested project prefix: $expected"
}
& $PythonExe -m pip check
if ($LASTEXITCODE -ne 0) { throw "pip check failed" }
