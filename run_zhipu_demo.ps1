param(
    [string]$Task = "",
    [string]$Workspace = ".",
    [string]$Model = "glm-4.5-air",
    [string]$BaseUrl = "https://open.bigmodel.cn/api/paas/v4",
    [string]$ApiKey = "",
    [int]$MaxSteps = 8,
    [switch]$Chat,
    [switch]$ShowExecutionDiff,
    [switch]$MergeBack,
    [switch]$NoMergeBack,
    [string[]]$MergeVerify = @(),
    [switch]$RollbackOnMergeVerificationFailure,
    [switch]$NoRollbackOnMergeVerificationFailure,
    [switch]$DryRun,
    [switch]$SmokeNative,
    [switch]$PrintConfig,
    [switch]$CheckOnly,
    [string]$Session = ""
)

$localConfigPath = Join-Path $PSScriptRoot ".mini_claw\\openai_compatible.local.json"
$localConfig = $null
if (Test-Path $localConfigPath) {
    try {
        $localConfig = Get-Content $localConfigPath -Raw | ConvertFrom-Json
    }
    catch {
        Write-Error "Failed to parse local config: $localConfigPath"
        exit 1
    }
}

if ($ApiKey) {
    $env:MINI_CLAW_API_KEY = $ApiKey
}
elseif (-not $env:MINI_CLAW_API_KEY -and -not $env:OPENAI_API_KEY -and $localConfig -and $localConfig.api_key) {
    $env:MINI_CLAW_API_KEY = [string]$localConfig.api_key
}

if (-not $BaseUrl -and $localConfig -and $localConfig.base_url) {
    $BaseUrl = [string]$localConfig.base_url
}

if ($PrintConfig) {
    $keyPresent = [bool]($env:MINI_CLAW_API_KEY -or $env:OPENAI_API_KEY)
    Write-Host "provider=openai-compatible"
    Write-Host "model=$Model"
    Write-Host "base_url=$BaseUrl"
    Write-Host "api_key_present=$keyPresent"
}

if (-not $env:MINI_CLAW_API_KEY -and -not $env:OPENAI_API_KEY) {
    Write-Error "Set MINI_CLAW_API_KEY or OPENAI_API_KEY before running this script."
    exit 1
}

if ($CheckOnly) {
    Write-Host "config_check=ok"
    exit 0
}

$workspacePath = Resolve-Path -LiteralPath $Workspace
$workspaceRoot = [string]$workspacePath
$shouldChat = [bool]$Chat
if (-not $shouldChat -and -not $SmokeNative -and -not $Task) {
    $shouldChat = $true
}

$shouldMergeBack = -not $NoMergeBack.IsPresent
if ($MergeBack.IsPresent) {
    $shouldMergeBack = $true
}
$shouldRollbackOnVerificationFailure = -not $NoRollbackOnMergeVerificationFailure.IsPresent
if ($RollbackOnMergeVerificationFailure.IsPresent) {
    $shouldRollbackOnVerificationFailure = $true
}

$resolvedMergeVerify = @($MergeVerify | Where-Object { $_ -and $_.Trim() })
if ($shouldMergeBack -and $resolvedMergeVerify.Count -eq 0) {
    $testsPath = Join-Path $workspaceRoot "tests"
    if (Test-Path -LiteralPath $testsPath) {
        $resolvedMergeVerify = @("python -m unittest discover -s tests -q")
    }
}

$env:MINI_CLAW_BASE_URL = $BaseUrl

$args = @("-S", "-m", "mini_claw")

if ($shouldChat) {
    $args += @(
        "chat",
        "--workspace", $Workspace,
        "--provider", "openai-compatible",
        "--model", $Model,
        "--max-steps", $MaxSteps,
        "--session-name", "zhipu-chat"
    )

    if ($Session) {
        $args += @("--session", $Session)
    }

    if (-not $shouldMergeBack) {
        $args += "--no-merge-back"
    }

    foreach ($verify in $resolvedMergeVerify) {
        $args += @("--merge-verify", $verify)
    }

    if (-not $shouldRollbackOnVerificationFailure) {
        $args += "--no-rollback-on-merge-verification-failure"
    }
}
elseif ($SmokeNative) {
    $args += @(
        "smoke",
        "--workspace", $Workspace,
        "--provider", "openai-compatible",
        "--model", $Model,
        "--timeout", 30,
        "--max-rounds", $MaxSteps
    )
}
else {
    if (-not $Task) {
        Write-Error "Provide -Task for one-shot mode, or omit -Task to enter chat mode."
        exit 1
    }

    $effectiveTask = @"
Focus on the main Mini Claw-Coder repository.
Ignore .external and sibling-project unless the task explicitly asks for them.

User task:
$Task
"@

    $args += @(
        "run", $effectiveTask,
        "--workspace", $Workspace,
        "--provider", "openai-compatible",
        "--model", $Model,
        "--max-steps", $MaxSteps
    )

    if ($Session) {
        $args += @("--session", $Session)
    }

    if ($ShowExecutionDiff) {
        $args += "--show-execution-diff"
    }

    if ($shouldMergeBack) {
        $args += "--merge-back"
    }

    foreach ($verify in $resolvedMergeVerify) {
        $args += @("--merge-verify", $verify)
    }

    if ($shouldRollbackOnVerificationFailure) {
        $args += "--rollback-on-merge-verification-failure"
    }

    if ($DryRun) {
        $args += "--dry-run"
    }
}

& python @args
exit $LASTEXITCODE
