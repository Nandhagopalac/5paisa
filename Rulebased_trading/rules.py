"""Your entry rules as plain, testable functions (no orders are placed here).

Direction comes from the second-by-second BUY signals; the other rules must agree:

              CALL (CE) entry                    PUT (PE) entry
  signal      3 BUY in a row on CE signal        3 BUY in a row on PE signal
  top 3       top 3 of TOP 5 NOW all positive    top 3 of TOP 5 NOW all negative
  impact      Top-5 impact > 0                   Top-5 impact < 0
  breadth     advancing stocks  > 15             advancing stocks <= 15

Strike is always one step in the money, quantity always 1 lot, order type always market.
"""
import math
from dataclasses import dataclass
from datetime import datetime

LOT_SIZE = 65          # NIFTY lot size (same default as Order/market/market.ps1)
LOTS = 1
STRIKE_STEP = 50
ITM_STEPS = 1          # 1 = the first strike in the money
BUY_STREAK = 3         # consecutive BUY seconds needed
BREADTH_UP_MIN = 15    # CE needs more than this many advancing stocks, PE needs this many or fewer
TOP_N = 3              # how many of the top-5 stocks must agree
MAX_SIGNAL_AGE = 5.0   # seconds; older signal rows mean the dashboard stopped
MAX_GAP = 3            # seconds allowed between two signal rows to still count as "in a row"


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def seconds_of_day(text):
    hour, minute, second = (int(part) for part in str(text).split(":")[:3])
    return hour * 3600 + minute * 60 + second


def streak(rows, side, now_seconds, max_age=MAX_SIGNAL_AGE, max_gap=MAX_GAP):
    """How many BUY rows in a row, ending at the newest row, for side 'CE' or 'PE'.

    rows: chronological dicts with 'time' (HH:MM:SS) and 'ce_signal' / 'pe_signal'.
    Returns 0 if the newest row is stale, is not BUY, or the rows are not consecutive seconds."""
    key = "ce_signal" if side == "CE" else "pe_signal"
    if not rows or now_seconds - seconds_of_day(rows[-1]["time"]) > max_age:
        return 0
    count, newer = 0, None
    for row in reversed(rows):
        stamp = seconds_of_day(row["time"])
        if row.get(key) != "BUY" or (newer is not None and newer - stamp > max_gap):
            break
        count, newer = count + 1, stamp
    return count


def itm_strike(spot, side, step=STRIKE_STEP, steps=ITM_STEPS):
    """First strike strictly in the money: below spot for CE, above spot for PE."""
    spot = float(spot)
    if side == "CE":
        return int((math.ceil(spot / step) - 1) * step - (steps - 1) * step)
    return int((math.floor(spot / step) + 1) * step + (steps - 1) * step)


def evaluate(side, rows, snapshot, now_seconds):
    """All rule checks for one side. The entry is allowed only when every check is ok."""
    sign = 1 if side == "CE" else -1
    run = streak(rows, side, now_seconds)
    checks = [Check(f"{BUY_STREAK} BUY in a row ({side} signal)", run >= BUY_STREAK, f"{run} in a row")]
    if snapshot is None:
        checks.append(Check("Live dashboard data (< 5 s old)", False, "no fresh data - is the dashboard running?"))
        return checks
    top = snapshot.get("top5") or []
    first = top[:TOP_N]
    word = "positive" if side == "CE" else "negative"
    ok_top = len(first) == TOP_N and all(sign * float(item["pct"]) > 0 for item in first)
    checks.append(Check(f"Top {TOP_N} of TOP 5 NOW {word}", ok_top,
                        ", ".join(f'{item["sym"]} {float(item["pct"]):+.2f}%' for item in first) or "no data"))
    net = float(snapshot.get("net_impact", 0.0))
    checks.append(Check(f"Top-5 impact {'> 0' if side == 'CE' else '< 0'}", sign * net > 0, f"{net:+.3f} pp"))
    up = int(snapshot.get("gainers", 0))
    ok_breadth = up > BREADTH_UP_MIN if side == "CE" else up <= BREADTH_UP_MIN
    checks.append(Check(f"Market breadth: up {'>' if side == 'CE' else '<='} {BREADTH_UP_MIN}", ok_breadth,
                        f"{up} up / {int(snapshot.get('losers', 0))} down"))
    return checks


def candidate_side(rows, now_seconds):
    """'CE' or 'PE' when exactly one leg has the BUY streak; None when none or both (ambiguous)."""
    ce = streak(rows, "CE", now_seconds) >= BUY_STREAK
    pe = streak(rows, "PE", now_seconds) >= BUY_STREAK
    if ce == pe:
        return None
    return "CE" if ce else "PE"


def now_seconds(moment=None):
    moment = moment or datetime.now()
    return moment.hour * 3600 + moment.minute * 60 + moment.second
