import argparse
import configparser
from html import escape
import sys
import time
from pathlib import Path

import pandas as pd
from py5paisa import FivePaisaClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
SCRIP_MASTER_CACHE = PROJECT_ROOT / "scrip_master.csv"

target_strike = 25200
target_expiry = pd.to_datetime("2026-11-23")
underlying = "NIFTY"
option_types = ("CE", "PE")
itm_strike_step = 100
itm_strikes_per_side = 5

REQUIRED_COLUMNS = {
    "Exch",
    "ExchType",
    "ScripCode",
    "Expiry",
    "ScripType",
    "StrikeRate",
    "SymbolRoot",
}


def fetch_scrip_master():
    config = configparser.ConfigParser(interpolation=None)
    config_path = PROJECT_ROOT / "config.ini"
    if not config.read(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    section = "5paise_login"
    if not config.has_section(section):
        raise configparser.NoSectionError(section)

    settings = config[section]
    credentials = {
        key: settings[key].strip()
        for key in ("APP_NAME", "APP_SOURCE", "USER_ID", "PASSWORD", "USER_KEY", "ENCRYPTION_KEY")
    }
    client = FivePaisaClient(cred=credentials)
    client.set_access_token(settings["access_token"].strip(), settings["CLIENT_CODE"].strip())

    for attempt in range(1, 4):
        scrips = client.get_scrips()
        if scrips is not None:
            if not isinstance(scrips, pd.DataFrame):
                raise TypeError(
                    f"Expected get_scrips() to return a pandas DataFrame, "
                    f"got {type(scrips).__name__}."
                )
            missing = REQUIRED_COLUMNS.difference(scrips.columns)
            if missing:
                raise ValueError(f"Scrip master is missing columns: {', '.join(sorted(missing))}")
            scrips.to_csv(SCRIP_MASTER_CACHE, index=False)
            print(f"Fetched and cached {len(scrips)} scrips at {SCRIP_MASTER_CACHE}.")
            return scrips
        if attempt < 3:
            print(f"Scrip fetch timed out (attempt {attempt}/3); retrying in 3 seconds.")
            time.sleep(3)

    raise RuntimeError("5paisa did not return the scrip list after 3 attempts.")


def load_scrip_master(refresh):
    if not refresh and SCRIP_MASTER_CACHE.exists():
        scrips = pd.read_csv(SCRIP_MASTER_CACHE)
        missing = REQUIRED_COLUMNS.difference(scrips.columns)
        if missing:
            raise ValueError(
                f"Scrip master cache is missing columns: {', '.join(sorted(missing))}. "
                "Run with --refresh-cache to replace it."
            )
        print(f"Using cached scrip master: {SCRIP_MASTER_CACHE}")
        return scrips
    return fetch_scrip_master()


def remove_stale_reports(current_output):
    for stale_report in SCRIPT_DIR.glob("option_scripcodes_*.html"):
        if stale_report != current_output:
            stale_report.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Save the target NIFTY strike with three CE strikes below and three PE "
            "strikes above, spaced 200 points apart."
        )
    )
    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help="fetch the scrip master again instead of using the local CSV cache",
    )
    args = parser.parse_args()

    scrips = load_scrip_master(args.refresh_cache)
    expiry = target_expiry.date()
    contracts = scrips[
        scrips["SymbolRoot"].fillna("").astype(str).str.upper().eq(underlying.upper())
        & scrips["Exch"].fillna("").astype(str).str.upper().eq("N")
        & scrips["ExchType"].fillna("").astype(str).str.upper().eq("D")
        & pd.to_datetime(scrips["Expiry"], errors="coerce").dt.date.eq(expiry)
        & scrips["ScripType"].fillna("").astype(str).str.upper().isin(option_types)
    ].copy()
    contracts["StrikeRate"] = pd.to_numeric(contracts["StrikeRate"], errors="coerce")
    contracts = contracts.dropna(subset=["StrikeRate", "ScripCode"])

    selected_rows = []
    selected_contracts = [
        (target_strike - itm_strike_step * step, "CE")
        for step in range(itm_strikes_per_side, 0, -1)
    ]
    selected_contracts.extend(
        (target_strike, option_type) for option_type in option_types
    )
    selected_contracts.extend(
        (target_strike + itm_strike_step * step, "PE")
        for step in range(1, itm_strikes_per_side + 1)
    )

    for strike, option_type in selected_contracts:
        strike_rows = contracts[
            contracts["StrikeRate"].eq(strike)
            & contracts["ScripType"].astype(str).str.upper().eq(option_type)
        ].copy()
        if strike_rows.empty:
            raise LookupError(
                f"No {option_type} contract found at strike {strike:g} "
                f"for {underlying} expiry {expiry}."
            )
        if len(strike_rows) != 1:
            raise LookupError(
                f"Expected one {option_type} contract at strike {strike:g}, "
                f"found {len(strike_rows)}."
            )
        selected_rows.append(strike_rows)

    result = pd.concat(selected_rows, ignore_index=True)
    result["ScripType"] = result["ScripType"].astype(str).str.upper()
    result["_OptionOrder"] = result["ScripType"].map({"CE": 0, "PE": 1})
    result = result.sort_values(["StrikeRate", "_OptionOrder"]).drop(
        columns="_OptionOrder"
    ).reset_index(drop=True)

    display_columns = ["Exch", "ExchType", "ScripCode", "StrikeRate", "Expiry", "ScripType"]
    display_result = result[display_columns].rename(columns={"StrikeRate": "Strike Price"})
    table_rows = []
    for row in display_result.itertuples(index=False, name=None):
        option_type = row[-1]
        cells = []
        for index, value in enumerate(row):
            if index == 3:
                color_class = "strike-ce" if option_type == "CE" else "strike-pe"
                cells.append(f'<td class="{color_class}">{escape(str(value))}</td>')
            else:
                cells.append(f"<td>{escape(str(value))}</td>")
        table_rows.append(f"<tr>{''.join(cells)}</tr>")

    output_file = SCRIPT_DIR / (
        f"option_scripcodes_{underlying}_{target_strike}_{expiry.isoformat()}.html"
    )
    remove_stale_reports(output_file)
    headers = "".join(f"<th scope=\"col\">{column}</th>" for column in display_result.columns)
    report = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>{escape(underlying)} option contracts</title>
  <style>
    :root {{
      font-family: "Segoe UI", Inter, system-ui, -apple-system, sans-serif;
      color: #172b4d;
      background: #edf2f8;
      font-synthesis: none;
      text-rendering: optimizeLegibility;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      min-height: 100vh;
      margin: 0;
      padding: clamp(20px, 5vw, 64px);
      background:
        radial-gradient(ellipse at 12% 0%, #dcecff 0, transparent 42%),
        #edf2f8;
    }}
    main {{ max-width: 1120px; margin: 0 auto; }}
    .eyebrow {{
      margin: 0 0 10px;
      color: #5272a0;
      font-size: 12px;
      font-weight: 750;
      letter-spacing: .16em;
      text-transform: uppercase;
    }}
    h1 {{
      margin: 0;
      color: #102444;
      font-size: clamp(30px, 5vw, 46px);
      letter-spacing: -.045em;
    }}
    .subtitle {{ margin: 10px 0 28px; color: #64748b; font-size: 15px; }}
    .panel {{
      overflow: hidden;
      border: 1px solid #dfe7f1;
      border-radius: 18px;
      background: #fff;
      box-shadow: 0 18px 50px #17345a12, 0 2px 8px #17345a08;
    }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; text-align: left; }}
    thead {{ background: #f6f8fc; }}
    th {{
      padding: 16px 20px;
      color: #6a7d98;
      font-size: 11px;
      font-weight: 750;
      letter-spacing: .09em;
      text-transform: uppercase;
      white-space: nowrap;
    }}
    td {{
      padding: 17px 20px;
      border-top: 1px solid #edf1f6;
      color: #344762;
      font-size: 14px;
      white-space: nowrap;
    }}
    tbody tr {{ transition: background .15s ease; }}
    tbody tr:hover {{ background: #f6faff; }}
    td:nth-child(3) {{
      color: #143c75;
      font-family: "Cascadia Code", Consolas, monospace;
      font-size: 14px;
      font-weight: 750;
    }}
    .strike-ce {{ color: #14532d; font-weight: 750; }}
    .strike-pe {{ color: #7f1d1d; font-weight: 750; }}
    td:last-child {{ color: #087e8b; font-weight: 750; }}
    @media (max-width: 640px) {{
      body {{ padding: 26px 14px; }}
      th, td {{ padding: 14px 15px; }}
      .subtitle {{ margin-bottom: 20px; }}
    }}
  </style>
</head>
<body>
  <main>
    <p class="eyebrow">Option contracts</p>
    <h1>{escape(underlying)} · {target_strike}</h1>
    <p class="subtitle">Expiry {escape(expiry.isoformat())} &nbsp;·&nbsp; CE and PE contracts</p>
    <section class="panel" aria-label="Option contract details">
      <div class="table-wrap">
        <table>
          <thead><tr>{headers}</tr></thead>
          <tbody>
            {"".join(table_rows)}
          </tbody>
        </table>
      </div>
    </section>
  </main>
</body>
</html>
"""
    output_file.write_text(report, encoding="utf-8")
    print(f"\nSaved {len(result)} option contracts to: {output_file}")
    print(display_result.to_string(index=False))


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, KeyError, LookupError, RuntimeError, TypeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
