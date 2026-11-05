# 5paisa

Order scripts are grouped by order type under `Order\`:

- `Order\amo\` - place and cancel after-market orders
- `Order\limit\` - place regular limit orders
- `Order\market\` - place market orders and close a selected open position

PowerShell shortcuts can be run from the project root or another working
directory, for example:

```powershell
.\Order\market\market.ps1 -Quantity 65 -Side B
```

The Python scripts default to a dry run. Add `--confirm` only when ready to
submit an order. The PowerShell market-order shortcut submits immediately
without an additional confirmation prompt.

To close an open position, run `.\Order\market\close.ps1`. Select a position
from the current position book; the script submits an opposite-side market
order for its net quantity without another confirmation prompt. Positions
cannot be closed by this script if 5paisa's RMS rejects the market order.