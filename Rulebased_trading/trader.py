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
from Rulebased_trading import config, rules  # noqa: E402
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


def pick_contract(contracts, expiry, side, spot, settings=None):
    """(strike, scrip code): the in-the-money option for `side` (or the ATM one if use_itm is unticked)."""
    cfg = settings or config.Settings()
    strike = rules.itm_strike(spot, side, steps=cfg.itm_steps) if cfg.use_itm else core.atm_strike(spot)
    codes = core.option_codes(contracts, expiry, strike)
    if codes is None:
        raise RuntimeError(f"No {side} contract for strike {strike} on {expiry}. "
                           "Refresh scrip_master.csv (python Cache/cachefile.py --refresh-cache).")
    return strike, codes[0 if side == "CE" else 1]


def order_command(scrip_code, intraday=False, live=False, qty=rules.LOT_SIZE * rules.LOTS):
    """The exact command sent to your Place_marketorder.py (--confirm only in live mode)."""
    command = [sys.executable, str(ORDER_SCRIPT), "--scripcode", str(scrip_code),
               "--qty", str(qty), "--side", "B", "--exch", "N", "--exchtype", "D"]
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


def load_current_settings(last_error):
    """(settings or None, error text). A broken entry_rules.md pauses trading instead of guessing."""
    try:
        return config.load_settings(), ""
    except (ValueError, OSError) as error:
        if str(error) != last_error:
            print(f"\n!! {error} - fix the file; no orders while it is broken.")
        return None, str(error)


def describe(cfg, expiry):
    return (f"expiry {expiry:%d %b %Y} · {cfg.lots} lot = {cfg.lots * cfg.lot_size} qty · market order · "
            f"{'ITM' if cfg.use_itm else 'ATM'} strike · max {cfg.max_orders} orders/day · last entry {cfg.last_entry}")


def run(args):
    contracts = core.load_contracts()
    expiries = core.upcoming_expiries(contracts)
    expiry = args.expiry or (expiries[0] if expiries else None)
    if expiry is None:
        raise RuntimeError("No upcoming NIFTY expiry in scrip_master.csv.")
    mode = "LIVE (real orders)" if args.live else "PAPER (nothing is sent)"
    cfg, error = load_current_settings("")
    print(f"Rule-based trader · {mode}" + (f" · {describe(cfg, expiry)}" if cfg else ""))
    print("Rules come from Rulebased_trading/entry_rules.md (re-read every second). "
          "Needs the dashboard running. Ctrl+C to stop.\n")
    armed = {"CE": True, "PE": True}
    placed = 0
    last_line = ""
    last_error = error
    shown_cfg = cfg
    while True:
        cfg, last_error = load_current_settings(last_error)
        if cfg is None:
            time.sleep(1)
            continue
        if shown_cfg is not None and cfg != shown_cfg:
            print(f"\nRules changed: {describe(cfg, expiry)}")
        shown_cfg = cfg
        moment = datetime.now(core.INDIA_TIME)
        day = moment.date().isoformat()
        seconds = rules.now_seconds(moment)
        signal_rows = read_signal_rows(day)
        snapshot, _ = read_snapshot()
        for side in ("CE", "PE"):  # a leg re-arms once its BUY streak has broken
            if not signal_rows or signal_rows[-1].get("ce_signal" if side == "CE" else "pe_signal") != "BUY":
                armed[side] = True
        side = rules.candidate_side(signal_rows, seconds, cfg.buy_streak)
        allowed, why = entry_allowed_now(moment, cfg.last_entry)
        if side is None:
            line = f"{moment:%H:%M:%S}  waiting for {cfg.buy_streak} BUY in a row (CE or PE, not both)"
        else:
            checks = rules.evaluate(side, signal_rows, snapshot, seconds, cfg)
            ready = all(c.ok for c in checks) and allowed and armed[side] and placed < cfg.max_orders
            line = f"{moment:%H:%M:%S}  {side} signal - " + ("ALL RULES OK" if ready else "rules not all met")
            if ready:
                print("\n" + line)
                show(checks)
                placed += handle_entry(args, cfg, contracts, expiry, side, signal_rows, moment, day)
                armed[side] = False
                last_line = ""
                continue
            if line != last_line:
                print("\n" + line + ("" if allowed else f" ({why})")
                      + (f" (max {cfg.max_orders} orders reached)" if placed >= cfg.max_orders else ""))
                show(checks)
        if side is None and line != last_line:
            print(line, end="\r", flush=True)
        last_line = line
        time.sleep(1)


def handle_entry(args, cfg, contracts, expiry, side, signal_rows, moment, day):
    """Show the order, wait for the keypress, re-check the rules, then send. Returns 1 if sent."""
    spot = float(signal_rows[-1]["spot"])
    strike, code = pick_contract(contracts, expiry, side, spot, cfg)
    qty = cfg.lots * cfg.lot_size
    mode = "LIVE" if args.live else "PAPER"
    print(f"\n   ORDER  BUY {side} {strike} · expiry {expiry:%d %b %Y} · scrip {code} · "
          f"{cfg.lots} lot ({qty}) · MARKET · {'intraday' if cfg.intraday else 'delivery/NRML'} · "
          f"NIFTY {spot:,.2f} · {mode}")
    if not press_key("   Press  Y  to place this market order, any other key to skip: "):
        print("   Skipped. Nothing sent.")
        log_trade([f"{moment:%H:%M:%S}", side, strike, code, qty, mode, "skipped"], day)
        return 0
    # the market (or your rules file) changed while you decided: everything must still hold right now
    now = datetime.now(core.INDIA_TIME)
    fresh, _ = load_current_settings("")
    rows = read_signal_rows(day)
    snapshot, _ = read_snapshot()
    still = fresh is not None and all(
        c.ok for c in rules.evaluate(side, rows, snapshot, rules.now_seconds(now), fresh))
    if not still or not entry_allowed_now(now, fresh.last_entry)[0] or (fresh.lots, fresh.lot_size) != (cfg.lots, cfg.lot_size):
        print("   Rules no longer hold - order NOT sent.")
        log_trade([f"{now:%H:%M:%S}", side, strike, code, qty, mode, "cancelled: rules changed"], day)
        return 0
    env = dict(os.environ, FP_CONFIG=str(PROJECT_ROOT / "config.ini"))
    result = subprocess.run(order_command(code, cfg.intraday, args.live, qty), env=env, cwd=str(PROJECT_ROOT))
    status = "sent" if (args.live and result.returncode == 0) else ("failed" if args.live else "paper")
    log_trade([f"{now:%H:%M:%S}", side, strike, code, qty, mode, status], day)
    return 1 if args.live and result.returncode == 0 else 0


def main():
    parser = argparse.ArgumentParser(
        description="Rule-based NIFTY option entries (asks before each order). Rules: entry_rules.md")
    parser.add_argument("--live", action="store_true", help="send real orders (default is paper mode)")
    parser.add_argument("--expiry", type=lambda text: datetime.strptime(text, "%Y-%m-%d").date(),
                        help="YYYY-MM-DD (default: nearest expiry)")
    args = parser.parse_args()
    try:
        run(args)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
