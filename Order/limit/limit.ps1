param(
    [ValidateRange(1, [int]::MaxValue)]
    [int] $Quantity = 65,

    [ValidateScript({ $_ -gt 0 })]
    [decimal] $Price,

    [ValidateSet("B", "S")]
    [string] $Side = "B",

    [switch] $Intraday
)

function Read-PositivePrice([string] $Prompt) {
    while ($true) {
        $inputPrice = Read-Host $Prompt
        $parsedPrice = [decimal]::Zero
        $validPrice = [decimal]::TryParse(
            $inputPrice,
            [Globalization.NumberStyles]::AllowDecimalPoint,
            [Globalization.CultureInfo]::InvariantCulture,
            [ref] $parsedPrice
        )
        if ($validPrice -and $parsedPrice -gt 0) {
            return $parsedPrice.ToString("0.################", [cultureinfo]::InvariantCulture)
        }
        Write-Host "Enter a positive price using a decimal point (for example, 92.5)." -ForegroundColor Red
    }
}

$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = Join-Path $projectRoot ".venv_5paisa\Scripts\python.exe"
$orderScript = Join-Path $PSScriptRoot "Place_limitorder.py"
$reportDirectory = Join-Path $projectRoot "Cache"

if (-not (Test-Path -LiteralPath $python)) {
    Write-Error "Python environment not found: $python"
    exit 1
}
if (-not (Test-Path -LiteralPath $orderScript)) {
    Write-Error "Order script not found: $orderScript"
    exit 1
}
if (-not (Test-Path -LiteralPath $reportDirectory -PathType Container)) {
    Write-Error "Contract report directory not found: $reportDirectory. Run Cache\cachefile.py first."
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
    Write-Host "Choose an option contract for a regular limit order  (Up/Down to move, Enter to select, Esc to cancel)" -ForegroundColor Cyan
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
$expiryDate = [datetime]::MinValue
if (-not [datetime]::TryParseExact(
    $contract.Expiry,
    "yyyy-MM-dd",
    [Globalization.CultureInfo]::InvariantCulture,
    [Globalization.DateTimeStyles]::None,
    [ref] $expiryDate
)) {
    Write-Error "Invalid expiry in $($report.Name): $($contract.Expiry)"
    exit 1
}
$symbolDate = $expiryDate.ToString("dd MMM yyyy", [Globalization.CultureInfo]::InvariantCulture).ToUpperInvariant()
$symbolStrike = ([decimal]::Parse($contract.StrikePrice, [Globalization.CultureInfo]::InvariantCulture)).ToString(
    "0.00",
    [Globalization.CultureInfo]::InvariantCulture
)
$marketFeedSymbol = "NIFTY $symbolDate $($contract.OptionType) $symbolStrike"
$marketFeedExpiry = $expiryDate.ToString("yyyyMMdd", [Globalization.CultureInfo]::InvariantCulture)
$marketFeedStrike = ([decimal]::Parse($contract.StrikePrice, [Globalization.CultureInfo]::InvariantCulture)).ToString(
    "0.##",
    [Globalization.CultureInfo]::InvariantCulture
)
$previousConfig = $env:FP_CONFIG
try {
    $env:FP_CONFIG = Join-Path $projectRoot "config.ini"
    $quoteOutput = & $python $orderScript `
        --ltp-only `
        --scripcode $contract.ScripCode `
        --exch $contract.Exchange `
        --exchtype $contract.ExchangeType `
        --symbol $marketFeedSymbol `
        --expiry $marketFeedExpiry `
        --strike $marketFeedStrike `
        --option-type $contract.OptionType
    $quoteExitCode = $LASTEXITCODE
}
finally {
    $env:FP_CONFIG = $previousConfig
}
if ($quoteExitCode -ne 0) {
    Write-Error "Could not retrieve LTP for ScripCode $($contract.ScripCode). No order was sent."
    exit $quoteExitCode
}
$quoteText = ($quoteOutput -join "`n")
$ltpMatch = [regex]::Match($quoteText, "(?m)^LTP=([0-9]+(?:\.[0-9]+)?)\s*$")
if (-not $ltpMatch.Success) {
    Write-Error "The quote response did not contain a usable LTP. No order was sent."
    exit 1
}
$ltpText = $ltpMatch.Groups[1].Value
$orderSide = "Buy"
if ($Side -eq "S") {
    $orderSide = "Sell"
}

Write-Host ""
Write-Host "Selected limit-order contract:" -ForegroundColor Cyan
Write-Host ("  {0} {1} {2} | ScripCode {3}" -f `
    $contract.OptionType, $contract.StrikePrice, $contract.Expiry, $contract.ScripCode)
Write-Host ("  LTP: {0}" -f $ltpText) -ForegroundColor Yellow
Write-Host ("  {0} {1} | Qty {2} | Exchange {3}/{4}" -f `
    $orderSide, $contract.OptionType, $Quantity, $contract.Exchange, $contract.ExchangeType)
if ($PSBoundParameters.ContainsKey("Price")) {
    $priceText = $Price.ToString("0.################", [cultureinfo]::InvariantCulture)
}
else {
    $priceText = Read-PositivePrice "Enter limit price"
}
Write-Host ("  Limit price {0}" -f $priceText)

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
