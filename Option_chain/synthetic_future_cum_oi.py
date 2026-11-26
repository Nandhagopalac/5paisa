"""Cumulative open interest (OI) around ATM for the synthetic-future table.

Cumulative OI CE / PE = the sum of OI over ATM and the 3 strikes above and below it.
Rule of thumb used on the table:
    PE OI higher than CE OI  -> put writers dominate -> bias is up (bullish)
    CE OI higher than PE OI  -> call writers dominate -> bias is down (bearish)
This is an indicator, not a trading signal.

Live change: every 5 minutes (09:15-15:30) the OI of the ATM +-10 strikes is saved to
data/history/nifty_oi_snapshots.csv. The change shown on the table is measured on the same
strikes, against the previous 5-minute snapshot and against the first snapshot of the day,
so a moving ATM does not fake a change.

Run  python .\\Option_chain\\synthetic_future_cum_oi.py  to keep saving snapshots with the dashboard closed.
"""
import csv
import html
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from Option_chain.synthetic_future import (
    HISTORY_PATH, INDIA_TIME, SLOT_MINUTES, _client_from_config, in_market_hours,
    load_contracts, upcoming_expiries,
)

OI_STRIKES_EACH_SIDE = 3
OI_PATH = HISTORY_PATH.parent / "nifty_oi_snapshots.csv"
COLUMNS = ["recorded_at", "expiry", "strike", "type", "oi"]
# Field names 5paisa's market feed may use for open interest
OI_KEYS = ("OpenInterest", "OI", "OpenInt", "Oi", "OpenInterestQty")


def oi_from_tick(tick):
    """Open interest from a quote dict, or None if the feed has no OI field."""
    for key in OI_KEYS:
        value = (tick or {}).get(key)
        if value not in (None, ""):
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


# ---------------- calculation ----------------
def summarize(chain, atm, each_side=OI_STRIKES_EACH_SIDE, step=50):
    """Cumulative OI of ATM +- each_side strikes from the panel chain.

    chain: [{"strike", "ce": {"oi"}, "pe": {"oi"}}, ...] (more strikes than needed is fine).
    Returns {"available", "strikes", "ce", "pe", "oi_map"}; oi_map has every strike in the chain.
    """
    window = {atm + step * k for k in range(-each_side, each_side + 1)}
    oi_map = {}
    for row in chain:
        for kind in ("ce", "pe"):
            value = row[kind].get("oi")
            if value is not None:
                oi_map[(float(row["strike"]), kind.upper())] = value
    strikes = sorted(s for s in window if (float(s), "CE") in oi_map and (float(s), "PE") in oi_map)
    return {
        "available": bool(strikes), "strikes": strikes,
        "ce": sum(oi_map[(float(s), "CE")] for s in strikes),
        "pe": sum(oi_map[(float(s), "PE")] for s in strikes),
        "oi_map": oi_map,
    }


def bias(ce, pe):
    """(text, colour) for the CE/PE OI comparison."""
    if pe > ce:
        return "PE OI higher: bias UP", "#009b7d"
    if ce > pe:
        return "CE OI higher: bias DOWN", "#c62828"
    return "CE and PE OI equal: neutral", "#787b86"


# ---------------- snapshots ----------------
def _slot(moment):
    return moment.replace(minute=moment.minute // SLOT_MINUTES * SLOT_MINUTES, second=0, microsecond=0)


def load_snapshots(day, path=OI_PATH):
    """Saved snapshots of one day (columns recorded_at, expiry, strike, type, oi)."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        return pd.DataFrame(columns=COLUMNS)
    frame = pd.read_csv(path)
    frame["recorded_at"] = pd.to_datetime(frame["recorded_at"], errors="coerce")
    return frame[frame["recorded_at"].dt.date == day].dropna(subset=["recorded_at"])


def record_snapshot(oi_map, expiry, now=None, path=OI_PATH):
    """Save the OI of all strikes in oi_map once per 5-minute slot. Returns True if saved."""
    now = (now or datetime.now(INDIA_TIME)).replace(tzinfo=None)
    if not oi_map or not in_market_hours(now):
        return False
    slot = _slot(now)
    existing = load_snapshots(now.date(), path)
    if not existing.empty and (existing["recorded_at"].map(_slot) == slot).any():
        return False
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.is_file() or path.stat().st_size == 0
    stamp = slot.isoformat(sep=" ")  # one timestamp per snapshot (the slot start)
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if new_file:
            writer.writerow(COLUMNS)
        for (strike, kind), oi in sorted(oi_map.items()):
            writer.writerow([stamp, expiry, int(strike), kind, oi])
    return True


def _sum_at(frame, moment, strikes, kind):
    rows = frame[(frame["recorded_at"] == moment) & (frame["type"] == kind) & (frame["strike"].isin(strikes))]
    return dict(zip(rows["strike"].astype(float), rows["oi"]))


def changes(summary, snapshots, now=None):
    """Change of cumulative CE/PE OI vs the previous snapshot and vs the first one of the day.

    Compared strike by strike on the strikes both moments have, so a moving ATM is not counted.
    Returns {"prev": (ce, pe) or None, "open": (ce, pe) or None}.
    """
    now = (now or datetime.now(INDIA_TIME)).replace(tzinfo=None)
    result = {"prev": None, "open": None}
    if snapshots.empty or not summary["available"]:
        return result
    times = [pd.Timestamp(t) for t in sorted(snapshots["recorded_at"].unique())]
    earlier = [t for t in times if t < _slot(now)]
    picks = {"prev": earlier[-1] if earlier else None, "open": earlier[0] if earlier else None}
    for name, moment in picks.items():
        if moment is None:
            continue
        delta = []
        for kind in ("CE", "PE"):
            before = _sum_at(snapshots, moment, summary["strikes"], kind)
            now_oi = {float(s): summary["oi_map"][(float(s), kind)] for s in summary["strikes"]}
            common = [s for s in now_oi if s in before]
            delta.append(sum(now_oi[s] - before[s] for s in common) if common else None)
        if None not in delta:
            result[name] = tuple(delta)
    return result


# ---------------- table rows (HTML) ----------------
def _lakh(value, signed=False):
    sign = ("+" if value > 0 else "−" if value < 0 else "") if signed else ""
    number = abs(value)
    if number >= 1e7:
        text = f"{number / 1e7:.2f} Cr"
    elif number >= 1e5:
        text = f"{number / 1e5:.2f} L"
    else:
        text = f"{number:,.0f}"
    return sign + text


def rows_html(d, row):
    """Extra summary rows for panel_html: cumulative OI CE, PE and the bias. `row` = panel's _row."""
    oi = d.get("oi")
    if not oi or not oi["available"]:
        return row("Cumulative OI (ATM ±3)", "OI not in the quote feed")
    delta = d.get("oi_change") or {}

    def line(index):
        bits = []
        for label, key in (("5m", "prev"), ("open", "open")):
            pair = delta.get(key)
            if pair:
                bits.append(f"{label} {_lakh(pair[index], True)}")
        extra = f' <span style="opacity:.8">({" · ".join(bits)})</span>' if bits else ""
        return f"{_lakh(oi['ce' if index == 0 else 'pe'])}{extra}"

    text, colour = bias(oi["ce"], oi["pe"])
    low, high = oi["strikes"][0], oi["strikes"][-1]
    return (row(f"Cumulative OI CE ({low}–{high})", line(0))
            + row(f"Cumulative OI PE ({low}–{high})", line(1))
            + row("PE − CE OI", f"{_lakh(oi['pe'] - oi['ce'], True)} · {html.escape(text)}", colour, colour))


# ---------------- stand-alone collector ----------------
def main():
    """Save an OI snapshot every 5 minutes (09:15-15:30) even when the dashboard is closed."""
    from Option_chain.synthetic_future_panel import load_futures, take_panel
    contracts, futures = load_contracts(), load_futures()
    expiry, client, last_spot = upcoming_expiries(contracts)[0], _client_from_config(), None
    print(f"Saving NIFTY OI snapshots for expiry {expiry} every {SLOT_MINUTES} minutes.")
    while True:
        now = datetime.now(INDIA_TIME)
        if in_market_hours(now.replace(tzinfo=None)):
            try:
                data = take_panel(client, contracts, futures, expiry, last_spot)
                last_spot = data["spot"]
                saved = record_snapshot(data["oi"]["oi_map"], expiry, now)
                print(f"{now:%H:%M:%S} CE OI {data['oi']['ce']:,.0f} PE OI {data['oi']['pe']:,.0f} "
                      f"{'saved' if saved else 'skipped'}")
            except Exception as error:
                print(f"{now:%H:%M:%S} {error}")
        time.sleep(30)


if __name__ == "__main__":
    main()
