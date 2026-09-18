param(
    [Parameter(Mandatory = $true)]
    [string]$SourceFile,
    [string]$TargetFile = ".env"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $SourceFile -PathType Leaf)) {
    throw "API source file does not exist: $SourceFile"
}

$sourceLines = @(Get-Content -LiteralPath $SourceFile -Encoding utf8)
$chatUrl = $null
$chatKey = $null
$workspaceUrl = $null
$workspaceKey = $null
for ($index = 0; $index -lt $sourceLines.Count; $index++) {
    if ($sourceLines[$index] -match '(https?://\S+)') {
        $candidateUrl = $Matches[0].Trim().TrimEnd(',', ';')
        $candidateKey = $null
        for ($next = $index + 1; $next -lt $sourceLines.Count; $next++) {
            $value = $sourceLines[$next].Trim()
            if ($value -and $value -notmatch 'https?://') {
                $separator = [Math]::Max($value.LastIndexOf([char]0x3a), $value.LastIndexOf([char]0xff1a))
                $candidateKey = if ($separator -ge 0) { $value.Substring($separator + 1).Trim() } else { $value }
                break
            }
        }
        if (-not $chatUrl) {
            $chatUrl = $candidateUrl
            $chatKey = $candidateKey
        } elseif (-not $workspaceUrl) {
            $workspaceUrl = $candidateUrl
            $workspaceKey = $candidateKey
        }
    }
}
if (-not $chatUrl -or -not $workspaceUrl -or -not $chatKey -or -not $workspaceKey) {
    throw "The source file must contain a chat URL and an Alibaba Workspace URL."
}

function Normalize-ChatBase([string]$value) {
    $normalized = $value.Trim().TrimEnd('/')
    if ($normalized -notmatch '/v1$') {
        $normalized = "$normalized/v1"
    }
    return $normalized
}

$chatBase = Normalize-ChatBase $chatUrl
$workspaceBase = $workspaceUrl.TrimEnd('/')
if ($workspaceBase -notmatch '/compatible-mode/v1$') {
    throw "The Alibaba Workspace URL must end with /compatible-mode/v1."
}
$workspaceRoot = $workspaceBase -replace '/compatible-mode/v1$', ''

# Keep one chat endpoint for ordinary Q&A and one Alibaba Workspace endpoint for
# embeddings, reranking and review. The same endpoint can serve concurrent agents;
# application-level limits remain the right place to control concurrency.
$updates = [ordered]@{
    "MODEL_MODE" = "api"
    "MODEL_PROVIDER" = "gateway"
    "GATEWAY_API_BASE" = $chatBase
    "GATEWAY_API_KEY" = $chatKey
    "GATEWAY_MODEL" = "deepseek-v4-flash"
    "GATEWAY_EMBEDDING_MODEL" = "text-embedding-v4"
    "DEEPSEEK_API_BASE" = $chatBase
    "DEEPSEEK_API_KEY" = $chatKey
    "DEEPSEEK_MODEL" = "deepseek-v4-flash"
    "CHAT_MODEL" = "deepseek-v4-flash"
    "DASHSCOPE_API_BASE" = $workspaceBase
    "DASHSCOPE_API_KEY" = $workspaceKey
    "DASHSCOPE_MODEL" = "qwen3.7-flash"
    "EMBEDDING_PROVIDER" = "embedding"
    "EMBEDDING_API_BASE" = $workspaceBase
    "EMBEDDING_API_KEY" = $workspaceKey
    "EMBEDDING_MODEL" = "text-embedding-v4"
    "EMBEDDING_DIMENSIONS" = "1024"
    "RERANKER_ENABLED" = "true"
    "RERANKER_PROVIDER" = "dashscope"
    "RERANKER_API_BASE" = "$workspaceRoot/compatible-api/v1/reranks"
    "RERANKER_API_KEY" = $workspaceKey
    "RERANKER_MODEL" = "qwen3-rerank"
    "REVIEW_API_BASE" = $workspaceBase
    "REVIEW_API_KEY" = $workspaceKey
    "REVIEW_MODEL" = "qwen3.7-flash"
    "REVIEW_MAX_TOKENS" = "8192"
}

$targetLines = if (Test-Path -LiteralPath $TargetFile -PathType Leaf) {
    @(Get-Content -LiteralPath $TargetFile -Encoding utf8)
} else {
    @()
}

$written = [System.Collections.Generic.HashSet[string]]::new()
$output = foreach ($line in $targetLines) {
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
Write-Host "Synchronized model endpoint configuration from $SourceFile."
Write-Host "Credential values were written only to $TargetFile and were not displayed."
