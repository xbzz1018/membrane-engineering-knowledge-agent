param(
    [Parameter(Mandatory = $true)]
    [string]$SourceFile,
    [string]$TargetFile = ".env",
    [switch]$EnableApiMode
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $SourceFile)) { throw "Source env file does not exist: $SourceFile" }

$allowed = @(
    "DASHSCOPE_API_KEY", "DASHSCOPE_API_BASE", "DASHSCOPE_MODEL",
    "DEEPSEEK_API_KEY", "DEEPSEEK_API_BASE", "DEEPSEEK_MODEL",
    "GATEWAY_API_KEY", "GATEWAY_API_BASE", "GATEWAY_MODEL", "GATEWAY_EMBEDDING_MODEL",
    "EMBEDDING_PROVIDER", "EMBEDDING_API_KEY", "EMBEDDING_API_BASE",
    "EMBEDDING_MODEL", "EMBEDDING_DIMENSIONS", "CHAT_MODEL", "VL_MODEL",
    "MINERU_API_URL"
)
$renamed = @{ "LLM_PROVIDER" = "MODEL_PROVIDER" }
$sourceValues = @{}
foreach ($line in Get-Content -LiteralPath $SourceFile) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') {
        $name = $Matches[1]
        if ($allowed -contains $name) { $sourceValues[$name] = $Matches[2] }
        if ($renamed.ContainsKey($name)) { $sourceValues[$renamed[$name]] = $Matches[2] }
    }
}

$targetLines = if (Test-Path -LiteralPath $TargetFile) {
    @(Get-Content -LiteralPath $TargetFile)
} elseif (Test-Path -LiteralPath ".env.example") {
    @(Get-Content -LiteralPath ".env.example")
} else {
    @()
}
if ($EnableApiMode) { $sourceValues["MODEL_MODE"] = "api" }
$written = [System.Collections.Generic.HashSet[string]]::new()
$output = foreach ($line in $targetLines) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=') {
        $name = $Matches[1]
        if ($sourceValues.ContainsKey($name)) {
            $written.Add($name) | Out-Null
            "$name=$($sourceValues[$name])"
            continue
        }
    }
    $line
}
foreach ($name in @($allowed + $renamed.Values + "MODEL_MODE")) {
    if ($sourceValues.ContainsKey($name) -and -not $written.Contains($name)) {
        $output += "$name=$($sourceValues[$name])"
    }
}

Set-Content -LiteralPath $TargetFile -Value $output -Encoding utf8
Write-Host "Imported API configuration names: $($sourceValues.Keys -join ', ')"
Write-Host "Values were written only to the local target file and were not displayed."
