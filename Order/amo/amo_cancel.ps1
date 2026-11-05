$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = Join-Path $projectRoot ".venv_5paisa\Scripts\python.exe"
$cancelScript = Join-Path $PSScriptRoot "Cancel_AMOorder.py"

if (-not (Test-Path -LiteralPath $python)) {
    Write-Error "Python environment not found: $python"
    exit 1
}
if (-not (Test-Path -LiteralPath $cancelScript)) {
    Write-Error "AMO cancellation script not found: $cancelScript"
    exit 1
}

$previousConfig = $env:FP_CONFIG
try {
    $env:FP_CONFIG = Join-Path $projectRoot "config.ini"
    & $python $cancelScript
    $result = $LASTEXITCODE
}
finally {
    $env:FP_CONFIG = $previousConfig
}

exit $result
