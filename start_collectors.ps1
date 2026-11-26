# Starts the three data collectors (NSE top 20, synthetic future, cumulative OI) in their own
# minimised windows, after stopping any copies left over from yesterday.
# Run it every morning AFTER you have refreshed the access_token in config.ini:
#   powershell -ExecutionPolicy Bypass -File C:\dev\5paisa\start_collectors.ps1
# For a fixed strike next to ATM add  --strike 25350  to the synthetic_future line below.
$root   = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".venv_5paisa\Scripts\python.exe"
$logs   = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null

# stop old copies (they hold yesterday's access token)
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'Option_chain[\\.](derivatives_history|synthetic_future_cum_oi|synthetic_future)' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

$collectors = @(
    @{ Name = "nse_top20";         Module = "Option_chain.derivatives_history" },
    @{ Name = "synthetic_future";  Module = "Option_chain.synthetic_future" },
    @{ Name = "cumulative_oi";     Module = "Option_chain.synthetic_future_cum_oi" }
)
foreach ($c in $collectors) {
    $log = Join-Path $logs "$($c.Name).log"
    $cmd = "Set-Location '$root'; `$Host.UI.RawUI.WindowTitle = '$($c.Name)'; & '$python' -u -m $($c.Module) *>&1 | Tee-Object -FilePath '$log' -Append"
    Start-Process powershell -WindowStyle Minimized -ArgumentList "-NoProfile", "-Command", $cmd
}
Write-Host "Collectors started. Logs: $logs"
