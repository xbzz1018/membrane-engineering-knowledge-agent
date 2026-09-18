param(
    [string]$TargetFile = ".env",
    [switch]$EnableTemporal
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $TargetFile)) {
    throw "Target env file does not exist. Run sync_api_config.ps1 first."
}

$updates = [ordered]@{
    "RUNTIME_MODE" = "full"
    "REDIS_PORT" = "16379"
    "MINIO_ENDPOINT" = "localhost:19000"
    "PARSER_MODE" = "mineru"
    "TEMPORAL_ENABLED" = $EnableTemporal.ToString().ToLowerInvariant()
    "AUTH_ENABLED" = "true"
}
$lines = @(Get-Content -LiteralPath $TargetFile)
$current = @{}
foreach ($line in $lines) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') {
        $current[$Matches[1]] = $Matches[2]
    }
}
if ($current.ContainsKey("EMBEDDING_API_BASE") -and $current.ContainsKey("EMBEDDING_API_KEY")) {
    $embeddingBase = $current["EMBEDDING_API_BASE"].TrimEnd('/')
    $embeddingKey = $current["EMBEDDING_API_KEY"]
    if ($embeddingBase -match '/compatible-mode/v1$' -and -not [string]::IsNullOrWhiteSpace($embeddingKey)) {
        $workspaceRoot = $embeddingBase -replace '/compatible-mode/v1$', ''
        $updates["RERANKER_ENABLED"] = "true"
        $updates["RERANKER_PROVIDER"] = "dashscope"
        $updates["RERANKER_API_BASE"] = "$workspaceRoot/compatible-api/v1/reranks"
        $updates["RERANKER_API_KEY"] = $embeddingKey
        $updates["RERANKER_MODEL"] = "qwen3-rerank"
        $updates["REVIEW_API_BASE"] = $embeddingBase
        $updates["REVIEW_API_KEY"] = $embeddingKey
        $updates["REVIEW_MODEL"] = "qwen3.7-flash"
        $updates["REVIEW_MAX_TOKENS"] = "8192"
    }
}
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
