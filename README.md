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

The Python scripts default to a dry run. Add `--confirm` only when ready to
submit an order. The PowerShell market-order shortcut submits immediately
without an additional confirmation prompt.

To close an open position, run `.\Order\market\close.ps1`. Select a position
from the current position book; the script submits an opposite-side market
order for its net quantity without another confirmation prompt. Positions
cannot be closed by this script if 5paisa's RMS rejects the market order.