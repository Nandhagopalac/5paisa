# Rule-based trader launcher.  Paper mode by default (nothing is sent):
#   .\Rulebased_trading\trade.ps1
# Real market orders (still asks for a keypress every time):
#   .\Rulebased_trading\trade.ps1 -Live
param([switch] $Live)
$root   = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv_5paisa\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { Write-Error "Python environment not found: $python"; exit 1 }
$arguments = @("-u", "-m", "Rulebased_trading.trader")
if ($Live) { $arguments += "--live" }
Set-Location $root
& $python @arguments
