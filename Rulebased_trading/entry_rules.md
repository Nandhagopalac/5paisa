# Entry rules - tick or untick, save the file, done

The trader re-reads this file every second, so a change applies immediately (no restart).
`[x]` = the rule is checked. `[ ]` = the rule is skipped and the trader goes to the next step.
Numbers are the lines with `=`; edit the number only.
Any CE / PE order still needs your **Y** keypress, and real orders only go out with `-Live`.

## Which side may trade
- [x] allow_ce: allow CALL (CE) entries
- [x] allow_pe: allow PUT (PE) entries

## Rules that must pass before an order
- [x] use_top_stocks: top stocks of TOP 5 NOW must agree (positive for CE, negative for PE)
- [x] use_impact: Top-5 impact must agree (above 0 for CE, below 0 for PE)
- [] use_breadth: market breadth must agree (CE: advancing stocks above the number below, PE: at or below it)

## Order settings
- [x] use_itm: buy the in-the-money strike (unticked = the at-the-money strike)
- [ ] intraday: intraday (MIS) order (unticked = delivery / NRML, like your market.ps1)

## Numbers
buy_streak = 1
top_stocks = 3
breadth_up_min = 15
itm_steps = 1
lots = 1
lot_size = 65
last_entry = 15:15
max_orders = 1

## Fixed (not changeable here)
- Order type is always a MARKET order, always a BUY of the option.
- The direction always comes from the BUY signal streak (CE signal -> CE, PE signal -> PE).
- Every order waits for your Y keypress, and the rules are checked again right after it.
