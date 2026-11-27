"""Keeps a history of NSE's "Top 20 contracts" CE vs PE volume.

One reading is saved about every 10 minutes into data/history/nse_top20_ce_pe.csv
(that folder is git-ignored, so the history stays on your computer).

The dashboard calls record_sample() by itself while it is open. To keep building
history when the dashboard is closed, run this file in a terminal:

    python .\\Option_chain\\derivatives_history.py
"""
import argparse
import csv
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

INDIA_TIME = timezone(timedelta(hours=5, minutes=30), name="IST")
HISTORY_PATH = Path(__file__).resolve().parents[1] / "data" / "history" / "nse_top20_ce_pe.csv"
INTERVAL_MINUTES = 10
COLUMNS = ["recorded_at", "nse_timestamp", "ce", "pe", "ce_rows", "pe_rows", "market_status"]


def _bucket(moment):
    """The 10-minute slot a moment belongs to, e.g. 09:57 -> 09:50."""
    return moment.replace(minute=moment.minute // INTERVAL_MINUTES * INTERVAL_MINUTES,
                          second=0, microsecond=0, tzinfo=None)


def _last_row(path):
    if not path.is_file() or path.stat().st_size == 0:
        return None
    with path.open("rb") as handle:
        handle.seek(max(path.stat().st_size - 2048, 0))
        lines = [ln for ln in handle.read().decode("utf-8", "ignore").splitlines() if ln.strip()]
    if not lines or lines[-1].startswith("recorded_at"):
        return None
    row = next(csv.reader([lines[-1]]))
    return dict(zip(COLUMNS, row)) if len(row) == len(COLUMNS) else None


def record_sample(totals, row_counts, timestamp, market_status, path=HISTORY_PATH, now=None):
    """Save one reading. Returns True if a new row was written.

    A reading is saved at most once per 10-minute slot, and never twice for the
    same NSE timestamp (so nothing is repeated while the market is closed).
    """
    now = now or datetime.now(INDIA_TIME)
    path = Path(path)
    if not (totals.get("Call") or totals.get("Put")):
        return False  # NSE sends 0 / 0 before the market opens: nothing worth saving
    nse_stamp = str(timestamp or "")
    last = _last_row(path)
    if last:
        try:
            last_bucket = _bucket(datetime.fromisoformat(last["recorded_at"]))
        except ValueError:
            last_bucket = None
        if last_bucket is not None and _bucket(now) <= last_bucket:
            return False
        if nse_stamp and nse_stamp == last["nse_timestamp"]:
            return False

    status = market_status.get("marketStatusMessage", "") if isinstance(market_status, dict) else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.is_file() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if is_new:
            writer.writerow(COLUMNS)
        writer.writerow([now.strftime("%Y-%m-%d %H:%M:%S"), nse_stamp, totals["Call"],
                         totals["Put"], row_counts["Call"], row_counts["Put"], status])
    return True


def load_history(path=HISTORY_PATH):
    """All saved readings as a table (empty if nothing has been saved yet)."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        return pd.DataFrame(columns=["Time", "CE", "PE", "Lead", "Status"])
    raw = pd.read_csv(path)
    frame = pd.DataFrame({
        "Time": pd.to_datetime(raw["recorded_at"], errors="coerce"),
        "CE": pd.to_numeric(raw["ce"], errors="coerce"),
        "PE": pd.to_numeric(raw["pe"], errors="coerce"),
        "Status": raw["market_status"].fillna(""),
    }).dropna(subset=["Time", "CE", "PE"])
    frame = frame[(frame["CE"] > 0) | (frame["PE"] > 0)]  # ignore empty pre-open readings
    frame["Lead"] = frame["CE"] - frame["PE"]
    return frame.sort_values("Time").reset_index(drop=True)


def _market_is_open(now):
    minutes = now.hour * 60 + now.minute
    return now.weekday() < 5 and 9 * 60 <= minutes <= 15 * 60 + 40


def main():
    from Option_chain.nse_equity_derivatives_volume import fetch_market_data

    parser = argparse.ArgumentParser(description="Save NSE top-20 CE/PE volume every 10 minutes.")
    parser.add_argument("--always", action="store_true",
                        help="also save outside market hours (weekdays 09:00-15:40 IST by default)")
    parser.add_argument("--once", action="store_true", help="save one reading and stop")
    args = parser.parse_args()

    while True:
        now = datetime.now(INDIA_TIME)
        if args.always or _market_is_open(now):
            try:
                saved = record_sample(*fetch_market_data())
                print(f"{now:%H:%M:%S} {'saved' if saved else 'already have this reading'}")
            except RuntimeError as error:
                print(f"{now:%H:%M:%S} could not fetch: {error}")
        if args.once:
            return
        # wake up every 30 seconds so a new 10-minute slot is caught quickly
        time.sleep(30)


if __name__ == "__main__":
    main()
