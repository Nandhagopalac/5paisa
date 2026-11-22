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
`(sell price - buy price) × lots × lot size`, before fees and taxes. Select a
saved trade under its date to edit it.

Trade entries include instrument, CE/PE, quantity in units, buy price, and sell
price. Gross P&L is calculated automatically as `(sell price - buy price) ×
quantity`, before fees and taxes.

Run from the project root:

```powershell
streamlit run .\A_plus_setup\tradingjourney.py
```

Each day's journal and trades are stored as a JSON file in
`A_plus_setup\data\journals\`. Rules are in `settings.json`, and screenshots
are saved in `A_plus_setup\data\screenshots\`. This uses ordinary local files:
no database server or additional storage package is needed. The data stays on
this computer and is excluded from Git. Back up the `data` folder to preserve
entries across device changes.

The 1:1:1 checklist item is intentionally not given a trading interpretation.
Use **Rules** to write what it means for your process and edit any other daily
checklist items.

Run the journal tests from the project root:

```powershell
python -m unittest discover -s .\A_plus_setup -p "test_*.py"
```
