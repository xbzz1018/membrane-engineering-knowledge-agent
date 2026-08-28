param(
    [string]$TargetFile = ".env",
    [switch]$EnableTemporal
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $TargetFile)) {
    throw "Target env file does not exist. Run import_api_env.ps1 first."
}

$updates = [ordered]@{
    "RUNTIME_MODE" = "full"
    "REDIS_PORT" = "16379"
    "MINIO_ENDPOINT" = "localhost:19000"
    "PARSER_MODE" = "basic"
    "TEMPORAL_ENABLED" = $EnableTemporal.ToString().ToLowerInvariant()
    "AUTH_ENABLED" = "true"
}
$lines = @(Get-Content -LiteralPath $TargetFile)
$written = [System.Collections.Generic.HashSet[string]]::new()
$output = foreach ($line in $lines) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=') {
        $name = $Matches[1]
        if ($updates.Contains($name)) {
            $written.Add($name) | Out-Null
            "$name=$($updates[$name])"
            continue
        }
    }
    $line
}
foreach ($name in $updates.Keys) {
    if (-not $written.Contains($name)) {
        $output += "$name=$($updates[$name])"
    }
}
Set-Content -LiteralPath $TargetFile -Value $output -Encoding utf8
Write-Host "Configured Full-mode local endpoints. Secret values were not displayed."
