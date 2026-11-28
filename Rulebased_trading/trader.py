"""Rule-based NIFTY option entry. Watches your rules and asks YOU before every order.

    python -m Rulebased_trading.trader            # PAPER mode: shows what it would do, sends nothing
    python -m Rulebased_trading.trader --live     # real market orders, still one keypress per order

It needs the Streamlit dashboard running (it supplies the BUY signals and the market snapshot).
Orders are sent by your own Order/market/Place_marketorder.py. There is no exit / stop-loss logic here.
"""
import argparse
import csv
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Option_chain import synthetic_future as core  # noqa: E402
from Rulebased_trading import rules  # noqa: E402
from Rulebased_trading.snapshot import read_snapshot  # noqa: E402

ORDER_SCRIPT = PROJECT_ROOT / "Order" / "market" / "Place_marketorder.py"
SIGNAL_LOG = "nifty_intrinsic_signals_{day}.csv"
TRADE_LOG = "rule_trades_{day}.csv"
HISTORY_DIR = PROJECT_ROOT / "data" / "history"
SIGNAL_COLUMNS = ["time", "spot", "strike", "ce", "pe", "ce_intrinsic", "pe_intrinsic",
                  "ce_signal", "pe_signal", "cum_ce", "cum_pe"]


def read_signal_rows(day, count=8, directory=HISTORY_DIR):
    """Last `count` rows of today's second-by-second signal log (written by the dashboard)."""
    path = Path(directory) / SIGNAL_LOG.format(day=day)
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - 4096))
            lines = handle.read().decode("utf-8", "ignore").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines[-count:]:
        parts = line.split(",")
        if len(parts) == len(SIGNAL_COLUMNS) and parts[0] != "time":
            rows.append(dict(zip(SIGNAL_COLUMNS, parts)))
    return rows


def pick_contract(contracts, expiry, side, spot, steps=rules.ITM_STEPS):
    """(strike, scrip code) of the in-the-money option for `side`."""
    strike = rules.itm_strike(spot, side, steps=steps)
    codes = core.option_codes(contracts, expiry, strike)
    if codes is None:
        raise RuntimeError(f"No {side} contract for strike {strike} on {expiry}. "
                           "Refresh scrip_master.csv (python Cache/cachefile.py --refresh-cache).")
    return strike, codes[0 if side == "CE" else 1]


def order_command(scrip_code, intraday=False, live=False):
    """The exact command sent to your Place_marketorder.py (--confirm only in live mode)."""
    command = [sys.executable, str(ORDER_SCRIPT), "--scripcode", str(scrip_code),
               "--qty", str(rules.LOT_SIZE * rules.LOTS), "--side", "B", "--exch", "N", "--exchtype", "D"]
    if intraday:
        command.append("--intraday")
    if live:
        command.append("--confirm")
    return command


def entry_allowed_now(moment, last_entry):
    """Market hours and the 'no new entries after' time (HH:MM)."""
    if not core.in_market_hours(moment):
        return False, "market closed"
    hour, minute = (int(part) for part in last_entry.split(":"))
    if (moment.hour, moment.minute) >= (hour, minute):
        return False, f"no new entries after {last_entry}"
    return True, ""


def press_key(prompt):
    """One keypress. Anything pressed before the prompt is discarded; only 'Y' confirms."""
    print(prompt, end="", flush=True)
    try:
        import msvcrt  # Windows
        while msvcrt.kbhit():
            msvcrt.getwch()
        key = msvcrt.getwch()
    except ImportError:
        key = (input() or " ")[:1]
    print(key)
    return key.upper() == "Y"


def log_trade(row, day, directory=HISTORY_DIR):
    path = Path(directory) / TRADE_LOG.format(day=day)
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if new:
            writer.writerow(["time", "side", "strike", "scrip_code", "qty", "mode", "result"])
        writer.writerow(row)


def show(checks):
    for check in checks:
        print(f"   {'✔' if check.ok else '✘'} {check.name:<38} {check.detail}")


def run(args):
    contracts = core.load_contracts()
    expiries = core.upcoming_expiries(contracts)
    expiry = args.expiry or (expiries[0] if expiries else None)
    if expiry is None:
        raise RuntimeError("No upcoming NIFTY expiry in scrip_master.csv.")
    mode = "LIVE (real orders)" if args.live else "PAPER (nothing is sent)"
    print(f"Rule-based trader · {mode} · expiry {expiry:%d %b %Y} · 1 lot = {rules.LOT_SIZE} qty · market order · "
          f"ITM strike · max {args.max_orders} orders/day")
    print("Needs the dashboard running. Ctrl+C to stop.\n")
    armed = {"CE": True, "PE": True}
    placed = 0
    last_line = ""
    while True:
        moment = datetime.now(core.INDIA_TIME)
        day = moment.date().isoformat()
        seconds = rules.now_seconds(moment)
        signal_rows = read_signal_rows(day)
        snapshot, _ = read_snapshot()
        for side in ("CE", "PE"):  # a leg re-arms once its BUY streak has broken
            if not signal_rows or signal_rows[-1].get("ce_signal" if side == "CE" else "pe_signal") != "BUY":
                armed[side] = True
        side = rules.candidate_side(signal_rows, seconds)
        allowed, why = entry_allowed_now(moment, args.last_entry)
        if side is None:
            line = f"{moment:%H:%M:%S}  waiting for {rules.BUY_STREAK} BUY in a row (CE or PE, not both)"
        else:
            checks = rules.evaluate(side, signal_rows, snapshot, seconds)
            ready = all(c.ok for c in checks) and allowed and armed[side] and placed < args.max_orders
            line = f"{moment:%H:%M:%S}  {side} signal - " + ("ALL RULES OK" if ready else "rules not all met")
            if ready:
                print("\n" + line)
                show(checks)
                placed += handle_entry(args, contracts, expiry, side, signal_rows, moment, day)
                armed[side] = False
                last_line = ""
                continue
            if line != last_line:
                print("\n" + line + ("" if allowed else f" ({why})"))
                show(checks)
        if side is None and line != last_line:
            print(line, end="\r", flush=True)
        last_line = line
        time.sleep(1)


def handle_entry(args, contracts, expiry, side, signal_rows, moment, day):
    """Show the order, wait for the keypress, re-check the rules, then send. Returns 1 if sent."""
    spot = float(signal_rows[-1]["spot"])
    strike, code = pick_contract(contracts, expiry, side, spot)
    qty = rules.LOT_SIZE * rules.LOTS
    mode = "LIVE" if args.live else "PAPER"
    print(f"\n   ORDER  BUY {side} {strike} · expiry {expiry:%d %b %Y} · scrip {code} · "
          f"{rules.LOTS} lot ({qty}) · MARKET · NIFTY {spot:,.2f} · {mode}")
    if not press_key("   Press  Y  to place this market order, any other key to skip: "):
        print("   Skipped. Nothing sent.")
        log_trade([f"{moment:%H:%M:%S}", side, strike, code, qty, mode, "skipped"], day)
        return 0
    # the market moved while you decided: the rules must still hold right now
    now = datetime.now(core.INDIA_TIME)
    rows = read_signal_rows(day)
    snapshot, _ = read_snapshot()
    still = all(c.ok for c in rules.evaluate(side, rows, snapshot, rules.now_seconds(now)))
    if not still or not entry_allowed_now(now, args.last_entry)[0]:
        print("   Rules no longer hold - order NOT sent.")
        log_trade([f"{now:%H:%M:%S}", side, strike, code, qty, mode, "cancelled: rules changed"], day)
        return 0
    env = dict(os.environ, FP_CONFIG=str(PROJECT_ROOT / "config.ini"))
    result = subprocess.run(order_command(code, args.intraday, args.live), env=env, cwd=str(PROJECT_ROOT))
    status = "sent" if (args.live and result.returncode == 0) else ("failed" if args.live else "paper")
    log_trade([f"{now:%H:%M:%S}", side, strike, code, qty, mode, status], day)
    return 1 if args.live and result.returncode == 0 else 0


def main():
    parser = argparse.ArgumentParser(description="Rule-based NIFTY option entries (asks before each order).")
    parser.add_argument("--live", action="store_true", help="send real orders (default is paper mode)")
    parser.add_argument("--expiry", type=lambda text: datetime.strptime(text, "%Y-%m-%d").date(),
                        help="YYYY-MM-DD (default: nearest expiry)")
    parser.add_argument("--intraday", action="store_true", help="intraday (MIS) instead of delivery/NRML")
    parser.add_argument("--max-orders", type=int, default=3, help="stop after this many orders in a day")
    parser.add_argument("--last-entry", default="15:15", help="no new entries from this time (HH:MM)")
    args = parser.parse_args()
    try:
        run(args)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
