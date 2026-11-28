# Rule-based trading

Run the dashboard first (it writes the BUY signals and the market snapshot), then in another window:

    .\Rulebased_trading\trade.ps1          # PAPER: shows the order, sends nothing
    .\Rulebased_trading\trade.ps1 -Live    # real market orders, one keypress (Y) per order

Rules (rules.py): CE entry needs 3 BUY in a row on the CE signal, top 3 of TOP 5 NOW positive,
Top-5 impact > 0 and advancing stocks > 15. PE entry is the mirror (3 BUY on PE, top 3 negative,
impact < 0, advancing <= 15). First ITM strike, 1 lot (65), market order, via Order/market/Place_marketorder.py.
Before sending, the rules are checked again after your keypress. No exit / stop-loss logic is included.
Every decision is logged to data/history/rule_trades_<date>.csv.
