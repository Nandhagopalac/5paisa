$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = Join-Path $projectRoot ".venv_5paisa\Scripts\python.exe"
$closeScript = Join-Path $PSScriptRoot "Close_position.py"

if (-not (Test-Path -LiteralPath $python)) {
    Write-Error "Python environment not found: $python"
    exit 1
}
if (-not (Test-Path -LiteralPath $closeScript)) {
    Write-Error "Position-close script not found: $closeScript"
    exit 1
}

$previousConfig = $env:FP_CONFIG
try {
    $env:FP_CONFIG = Join-Path $projectRoot "config.ini"
    & $python $closeScript
    $result = $LASTEXITCODE
}
finally {
    $env:FP_CONFIG = $previousConfig
}

exit $result
