# 5paisa

Order scripts are grouped by order type under `Order\`:

- `Order\amo\` - place and cancel after-market orders
- `Order\limit\` - place regular limit orders
- `Order\market\` - place market orders and close a selected open position

Cancel all pending AMO orders (no per-order confirmation) with:

```powershell
.\Order\amo\amo_cancel.ps1
```

Place an AMO from the option selector with `.\Order\amo\amo.ps1`. It fetches
the selected contract's LTP, then prompts for the limit and stop-loss trigger
prices before submitting.

The regular limit-order shortcut displays the selected contract's LTP when
available. If 5paisa has no current quote, enter the limit price manually; the
script does not infer a price.

The shortcut also asks for a stop-loss percentage based on the entry limit
price. It monitors the entry and submits a stop-market exit for each reported
fill. Keep the PowerShell window and PC running while the entry is pending.
Stop-market orders prioritize execution after the trigger but cannot guarantee
the fill price; gaps and thin liquidity can cause slippage.

PowerShell shortcuts can be run from the project root or another working
directory, for example:

```powershell
.\Order\market\market.ps1 -Quantity 65 -Side B
.\Order\limit\limit.ps1 -Quantity 65 -Side B -StopLossPercent 2
```

### NIFTY ATM options monitor

Run the read-only, polling Streamlit dashboard from the project root:

```powershell
streamlit run .\Streaming\nifty\app.py
```

It reads the 5paisa credentials and access token from `config.ini`, uses
`scrip_master.csv` to find the nearest ATM NIFTY call and put for the selected
expiry, and polls the index and option quotes every five seconds by default.
The polling interval and index scrip code can be changed in the sidebar. Refresh
the local contract master with
`python .\Cache\cachefile.py --refresh-cache` when it is out of date.

The dashboard only displays market data; it does not place orders or generate
trade-entry recommendations. Polling is not a guaranteed tick-by-tick feed, and
quotes can be delayed or unavailable. Validate the quotes, liquidity, and your
own risk controls before trading.

### Sensibull option-chain screenshots

The `.github/workflows/sensibull-screenshot.yml` workflow captures the
Sensibull option-chain page every 10 minutes on weekdays from 09:15 through
15:25 IST. GitHub scheduled workflows are best-effort and may start late.
It requires a Windows self-hosted Actions runner on an always-on device you
control; it will not run while that device is off.

On the runner device, install the dependencies and browser, then open a
browser to log in once for the day:

```powershell
python -m pip install -r .\Option_chain\requirements.txt
python -m playwright install chromium
python .\Option_chain\sensibull_screenshot.py --login
```

Configure the self-hosted runner to run under the same Windows account used
for this login. Register it from the repository's **Settings > Actions >
Runners** page, and keep the runner process online. The workflow reuses that
account's local browser profile and saves screenshots under
`%USERPROFILE%\SensibullScreenshots`; it does not upload screenshots or login
data to GitHub. If the daily session expires, run the login command again. The
workflow only captures the page and does not place orders. Check Sensibull's
terms before automating access.

The Python scripts default to a dry run. Add `--confirm` only when ready to
submit an order. The PowerShell market-order shortcut submits immediately
without an additional confirmation prompt.

To close an open position, run `.\Order\market\close.ps1`. Select a position
from the current position book; the script submits an opposite-side market
order for its net quantity without another confirmation prompt. Positions
cannot be closed by this script if 5paisa's RMS rejects the market order.