param(
    [ValidateRange(1, [int]::MaxValue)]
    [int] $Quantity = 65,

    [ValidateRange(0, [double]::MaxValue)]
    [double] $Price = 12.5,

    [ValidateSet("B", "S")]
    [string] $Side = "B",

    [switch] $Intraday
)

$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = Join-Path $projectRoot ".venv_5paisa\Scripts\python.exe"
$orderScript = Join-Path $PSScriptRoot "Place_AMOorder.py"
$reportDirectory = Join-Path $projectRoot "Cache"

if (-not (Test-Path -LiteralPath $python)) {
    Write-Error "Python environment not found: $python"
    exit 1
}
if (-not (Test-Path -LiteralPath $orderScript)) {
    Write-Error "Order script not found: $orderScript"
    exit 1
}

$reports = @(Get-ChildItem -LiteralPath $reportDirectory -Filter "option_scripcodes_*.html" -File |
    Sort-Object LastWriteTime -Descending)
if ($reports.Count -eq 0) {
    Write-Error "No option contract report found in $reportDirectory. Run Cache\cachefile.py first."
    exit 1
}
$report = $reports[0]
$html = Get-Content -LiteralPath $report.FullName -Raw
$rowMatches = [regex]::Matches($html, "(?is)<tr\b[^>]*>(.*?)</tr>")
$contracts = @()
$expectedHeaders = @("Exch", "ExchType", "ScripCode", "Strike Price", "Expiry", "ScripType")

foreach ($rowMatch in $rowMatches) {
    $cells = @([regex]::Matches($rowMatch.Groups[1].Value, "(?is)<t[hd]\b[^>]*>(.*?)</t[hd]>") |
        ForEach-Object { [System.Net.WebUtility]::HtmlDecode($_.Groups[1].Value.Trim()) })
    if ($cells.Count -eq 0) {
        continue
    }
    if ($cells[0] -eq "Exch") {
        if (($cells -join "|") -ne ($expectedHeaders -join "|")) {
            Write-Error "Unexpected columns in option report: $($cells -join ', ')"
            exit 1
        }
        continue
    }
    if ($cells.Count -ne $expectedHeaders.Count) {
        Write-Error "Malformed contract row in $($report.Name)."
        exit 1
    }
    $code = 0
    if (-not [int]::TryParse($cells[2], [ref] $code) -or $code -le 0) {
        Write-Error "Invalid scrip code in $($report.Name): $($cells[2])"
        exit 1
    }
    if ($cells[5] -notin @("CE", "PE")) {
        Write-Error "Invalid option type in $($report.Name): $($cells[5])"
        exit 1
    }
    $contracts += [pscustomobject]@{
        Exchange = $cells[0]
        ExchangeType = $cells[1]
        ScripCode = $code
        StrikePrice = $cells[3]
        Expiry = $cells[4]
        OptionType = $cells[5]
    }
}

if ($contracts.Count -eq 0) {
    Write-Error "No contracts found in $($report.FullName)."
    exit 1
}

$selectedIndex = 0
$selected = $false
while (-not $selected) {
    Clear-Host
    Write-Host "Choose an option contract  (Up/Down to move, Enter to select, Esc to cancel)" -ForegroundColor Cyan
    Write-Host "Report: $($report.Name)"
    Write-Host ""
    for ($index = 0; $index -lt $contracts.Count; $index++) {
        $contract = $contracts[$index]
        $marker = "  "
        if ($index -eq $selectedIndex) {
            $marker = "> "
        }
        $contractLabel = "{0,-3} {1,8}  {2,-10}  ScripCode {3}" -f `
            $contract.OptionType, $contract.StrikePrice, $contract.Expiry, $contract.ScripCode
        if ($index -eq $selectedIndex) {
            Write-Host "$marker$contractLabel" -ForegroundColor Yellow
        }
        elseif ($contract.OptionType -eq "CE") {
            Write-Host "$marker$contractLabel" -ForegroundColor Green
        }
        else {
            Write-Host "$marker$contractLabel" -ForegroundColor Red
        }
    }

    $key = [Console]::ReadKey($true)
    switch ($key.Key) {
        "UpArrow" {
            $selectedIndex = ($selectedIndex - 1 + $contracts.Count) % $contracts.Count
        }
        "DownArrow" {
            $selectedIndex = ($selectedIndex + 1) % $contracts.Count
        }
        "Enter" {
            $selected = $true
        }
        "Escape" {
            Write-Host "`nCancelled; no order was sent."
            exit 0
        }
    }
}

$contract = $contracts[$selectedIndex]
$priceText = $Price.ToString("0.################", [cultureinfo]::InvariantCulture)
$orderSide = "Buy"
if ($Side -eq "S") {
    $orderSide = "Sell"
}

Write-Host ""
Write-Host "Submitting selected AMO:" -ForegroundColor Cyan
Write-Host ("  {0} {1} {2} | ScripCode {3}" -f `
    $contract.OptionType, $contract.StrikePrice, $contract.Expiry, $contract.ScripCode)
Write-Host ("  {0} {1} | Qty {2} | Price {3} | Exchange {4}/{5}" -f `
    $orderSide, $contract.OptionType, $Quantity, $priceText, $contract.Exchange, $contract.ExchangeType)

$pythonArgs = @(
    $orderScript,
    "--scripcode", $contract.ScripCode,
    "--qty", $Quantity,
    "--price", $priceText,
    "--side", $Side,
    "--exch", $contract.Exchange,
    "--exchtype", $contract.ExchangeType,
    "--confirm"
)
if ($Intraday) {
    $pythonArgs += "--intraday"
}

$previousConfig = $env:FP_CONFIG
try {
    $env:FP_CONFIG = Join-Path $projectRoot "config.ini"
    & $python @pythonArgs
    $result = $LASTEXITCODE
}
finally {
    $env:FP_CONFIG = $previousConfig
}

exit $result
