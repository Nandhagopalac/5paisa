# A+ Trading Journal

A local Streamlit journal for daily trading plans, a customizable rules
checklist (including your own definition of the 1:1:1 rule), trade notes,
screenshots, and a color-coded monthly trade calendar. The calendar is the
landing page: click a day to add or review trades without leaving it. It does
not connect to a broker or place orders.

The inline trade form records instrument, CE/PE, lots, buy price, and sell
price. Each NIFTY lot is 65 units and each BANKNIFTY lot is 30 units; other
instruments default to 1 unit per lot. Quantity and gross P&L are calculated
automatically, with P&L equal to
`(sell price - buy price) × lots × lot size`, before fees and taxes. Every trade row has its own **Edit** button.

Under the trades, each trade has its own journal, written right after the trade:
feeling at entry and after, what you were thinking, what you would do
differently, which of your rules you followed, and screenshots.

Each row also has a **Delete** button. After you confirm, the trade, its
journal and its screenshot files are removed.

The **Strategies** page lists your strategies with trades, win rate, net P&L,
profit factor and average winner / loser, plus cards for the best, least
performing, most active and best win rate strategy. Pick a strategy to edit
its **Entry and Exit Rules** (market conditions, entry rules, exit rules). Each
rule shows its follow rate, net P&L, profit factor and win rate, worked out from
the trades you journalled. Every trade is saved under a strategy, and its
journal shows that strategy's rules as checkboxes. The day plan and review is
in the **Day plan & review** box on the Trade calendar page.

Trade entries include instrument, CE/PE, quantity in units, buy price, and sell
price. Gross P&L is calculated automatically as `(sell price - buy price) ×
quantity`, before fees and taxes.

Run from the project root:

```powershell
streamlit run .\Tradezella\tradingjourney.py
```

Each day's journal and trades are stored as a JSON file in
`Tradezella\data\journals\`. Rules are in `settings.json`, and screenshots
are saved in `Tradezella\data\screenshots\`. This uses ordinary local files:
no database server or additional storage package is needed. The data stays on
this computer and is excluded from Git. Back up the `data` folder to preserve
entries across device changes.

The 1:1:1 checklist item is intentionally not given a trading interpretation.
Use **Rules** to write what it means for your process and edit any other daily
checklist items.

Run the journal tests from the project root:

```powershell
python -m unittest discover -s .\Tradezella -p "test_*.py"
```
