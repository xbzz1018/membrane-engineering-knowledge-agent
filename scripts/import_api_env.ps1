param(
    [Parameter(Mandatory = $true)]
    [string]$SourceFile,
    [string]$TargetFile = ".env"
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $SourceFile)) { throw "Source env file does not exist: $SourceFile" }

$allowed = @(
    "DASHSCOPE_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY",
    "BASE_URL_CHAT", "CHAT_MODEL", "EMBEDDING_MODEL", "VL_MODEL",
    "MINERU_API_URL"
)
$sourceValues = @{}
foreach ($line in Get-Content -LiteralPath $SourceFile) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') {
        $name = $Matches[1]
        if ($allowed -contains $name) { $sourceValues[$name] = $Matches[2] }
    }
}

$targetLines = if (Test-Path -LiteralPath $TargetFile) { @(Get-Content -LiteralPath $TargetFile) } else { @() }
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
foreach ($name in $allowed) {
    if ($sourceValues.ContainsKey($name) -and -not $written.Contains($name)) {
        $output += "$name=$($sourceValues[$name])"
    }
}

Set-Content -LiteralPath $TargetFile -Value $output -Encoding utf8
Write-Host "Imported API configuration names: $($sourceValues.Keys -join ', ')"
Write-Host "Values were written only to the local target file and were not displayed."
