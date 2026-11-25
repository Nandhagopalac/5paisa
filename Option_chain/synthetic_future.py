"""NIFTY synthetic future and strike monitor (core logic, no Streamlit).

Synthetic future (put-call parity) for one expiry, taken at the ATM strike:

    synthetic future = ATM strike + CE price - PE price

(If CE > PE this is strike + (CE - PE); if PE > CE it is strike - (PE - CE).)

For any strike you monitor, the premium is split (against that strike's own synthetic future)
    intrinsic value = |CE - PE|, on the leg with the higher premium (the ITM leg)
    extrinsic value = premium - intrinsic  (time value, which melts as expiry nears)

One reading is saved per 5-minute slot between 09:15 and 15:30 IST into
data/history/nifty_synthetic_future.csv (git-ignored). The dashboard saves readings
while it is open; to keep collecting with the dashboard closed run

    python .\\Option_chain\\synthetic_future.py --strike 25200

(ATM, which follows the spot, is always saved; --strike adds a fixed strike next to it.)
"""
import argparse
import configparser
import csv
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

INDIA_TIME = timezone(timedelta(hours=5, minutes=30), name="IST")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIP_MASTER_PATH = PROJECT_ROOT / "scrip_master.csv"
HISTORY_PATH = PROJECT_ROOT / "data" / "history" / "nifty_synthetic_future.csv"

UNDERLYING = "NIFTY"
SPOT_REQUEST = {"Exch": "N", "ExchType": "C", "ScripCode": 999920000}  # NIFTY 50 index
STRIKE_STEP = 50
SLOT_MINUTES = 5
MARKET_OPEN = (9, 15)
MARKET_CLOSE = (15, 30)
COLUMNS = [
    "recorded_at", "expiry", "spot", "atm", "atm_ce", "atm_pe", "synthetic", "basis",
    "mode", "strike", "ce", "pe", "ce_intrinsic", "ce_extrinsic", "pe_intrinsic",
    "pe_extrinsic", "straddle", "total_extrinsic",
]


# ---------------- pure calculations ----------------
def atm_strike(spot, step=STRIKE_STEP):
    """Nearest strike to the spot price."""
    return int(round(float(spot) / step) * step)


def synthetic_future(strike, ce, pe):
    """strike + CE - PE  (= strike + (CE-PE) when CE leads, strike - (PE-CE) when PE leads)."""
    return float(strike) + float(ce) - float(pe)


def leg_values(strike, ce, pe):
    """Intrinsic / extrinsic split of one strike, measured against the synthetic future.

    future = strike + CE - PE.  The leg with the higher premium is in the money (ITM) and its
    intrinsic value is |CE - PE| (= future - strike for a call, strike - future for a put).
    Extrinsic = premium - intrinsic, so both legs end up with the same extrinsic value
    (the cheaper leg's premium), e.g. strike 25350, CE 270.00, PE 229.95:
    CE intrinsic 40.05, CE extrinsic 229.95, PE intrinsic 0, PE extrinsic 229.95.
    """
    ce, pe = float(ce), float(pe)
    diff = ce - pe
    ce_intrinsic, pe_intrinsic = max(diff, 0.0), max(-diff, 0.0)
    ce_extrinsic, pe_extrinsic = ce - ce_intrinsic, pe - pe_intrinsic
    return {
        "ce_intrinsic": ce_intrinsic, "ce_extrinsic": ce_extrinsic,
        "pe_intrinsic": pe_intrinsic, "pe_extrinsic": pe_extrinsic,
        "straddle": ce + pe,
        "total_extrinsic": ce_extrinsic + pe_extrinsic,
    }


# ---------------- contracts (from scrip_master.csv) ----------------
def load_contracts(path=SCRIP_MASTER_PATH):
    """All NIFTY CE/PE contracts: columns Expiry (date), Strike, Type, ScripCode."""
    master = pd.read_csv(path, low_memory=False,
                         usecols=["Exch", "ExchType", "ScripCode", "Expiry", "ScripType",
                                  "StrikeRate", "SymbolRoot"])
    keep = (
        master["SymbolRoot"].fillna("").astype(str).str.upper().eq(UNDERLYING)
        & master["Exch"].eq("N") & master["ExchType"].eq("D")
        & master["ScripType"].isin(["CE", "PE"])
    )
    frame = master[keep].copy()
    frame["Expiry"] = pd.to_datetime(frame["Expiry"], errors="coerce").dt.date
    frame["Strike"] = pd.to_numeric(frame["StrikeRate"], errors="coerce")
    frame = frame.dropna(subset=["Expiry", "Strike", "ScripCode"])
    frame["ScripCode"] = frame["ScripCode"].astype(int)
    return frame.rename(columns={"ScripType": "Type"})[["Expiry", "Strike", "Type", "ScripCode"]]


def upcoming_expiries(contracts, today=None, limit=6):
    """Nearest expiries that have not passed yet (the expiry day itself counts)."""
    today = today or datetime.now(INDIA_TIME).date()
    return [e for e in sorted(contracts["Expiry"].unique()) if e >= today][:limit]


def option_codes(contracts, expiry, strike):
    """(CE scrip code, PE scrip code) for the strike, or None if either is missing."""
    rows = contracts[(contracts["Expiry"] == expiry) & (contracts["Strike"] == strike)]
    ce = rows[rows["Type"] == "CE"]["ScripCode"]
    pe = rows[rows["Type"] == "PE"]["ScripCode"]
    if ce.empty or pe.empty:
        return None
    return int(ce.iloc[0]), int(pe.iloc[0])


# ---------------- live quotes ----------------
def fetch_quotes(client, requests):
    """{token: tick} from one REST market-feed call (ticks carry LastRate, PClose, ...)."""
    response = client.fetch_market_feed_scrip(requests)
    result = {}
    for tick in (response.get("Data") if isinstance(response, dict) else None) or []:
        try:
            result[int(tick.get("Token"))] = tick
        except (TypeError, ValueError):
            continue
    return result


def _price(quotes, code):
    value = (quotes.get(code) or {}).get("LastRate") or 0
    return float(value) if value else None


def take_reading(client, contracts, expiry, fixed_strike=None, last_spot=None, now=None):
    """One live reading as a list of rows: the ATM row first, then (optionally) a fixed-strike row.

    The ATM strike always follows the spot. The synthetic future is always taken at the ATM
    strike. Fixed-strike monitoring is extra and never replaces ATM. Raises RuntimeError with a
    readable reason if the spot or the ATM prices are missing.
    """
    now = now or datetime.now(INDIA_TIME)
    spot = last_spot
    if spot is None:
        spot = _price(fetch_quotes(client, [SPOT_REQUEST]), SPOT_REQUEST["ScripCode"])
        if spot is None:
            raise RuntimeError("Could not read the NIFTY spot price (index code 999920000).")

    for _ in range(2):  # one retry if the spot has moved to a different ATM strike
        atm = atm_strike(spot)
        wanted = {}
        requests = [SPOT_REQUEST]
        for label, strike in (("atm", atm), ("fixed", fixed_strike)):
            if not strike:
                continue
            codes = option_codes(contracts, expiry, strike)
            if codes is None:
                if label == "fixed":
                    continue  # unknown fixed strike: skip it, ATM still works
                raise RuntimeError(f"No CE/PE contracts for strike {strike} on {expiry}. "
                                   "Refresh scrip_master.csv (python Cache/cachefile.py --refresh-cache).")
            wanted[label] = (strike, codes)
            requests += [{"Exch": "N", "ExchType": "D", "ScripCode": c} for c in codes]
        unique = {(r["ExchType"], r["ScripCode"]): r for r in requests}
        quotes = fetch_quotes(client, list(unique.values()))
        new_spot = _price(quotes, SPOT_REQUEST["ScripCode"])
        if new_spot is None:
            raise RuntimeError("Could not read the NIFTY spot price (index code 999920000).")
        same_atm = atm_strike(new_spot) == atm
        spot = new_spot
        if same_atm:
            break  # (otherwise the strike used is one step off; the next reading corrects it)

    atm_strike_value, (atm_ce_code, atm_pe_code) = wanted["atm"]
    atm_ce, atm_pe = _price(quotes, atm_ce_code), _price(quotes, atm_pe_code)
    if atm_ce is None or atm_pe is None:
        raise RuntimeError(f"No price for the ATM {atm_strike_value} CE/PE yet.")
    synthetic = synthetic_future(atm_strike_value, atm_ce, atm_pe)
    common = {
        "recorded_at": now.replace(microsecond=0, tzinfo=None).isoformat(sep=" "),
        "expiry": str(expiry), "spot": spot, "atm": atm_strike_value,
        "atm_ce": atm_ce, "atm_pe": atm_pe, "synthetic": synthetic, "basis": synthetic - spot,
    }

    def row(mode, strike, ce, pe):
        return {**common, "mode": mode, "strike": strike, "ce": ce, "pe": pe,
                **leg_values(strike, ce, pe)}

    rows = [row("ATM", atm_strike_value, atm_ce, atm_pe)]
    if "fixed" in wanted:
        strike, (ce_code, pe_code) = wanted["fixed"]
        ce, pe = _price(quotes, ce_code), _price(quotes, pe_code)
        if ce is not None and pe is not None:
            rows.append(row("FIXED", strike, ce, pe))
    return rows


# ---------------- history (one row per 5-minute slot, 09:15-15:30) ----------------
def _slot(moment):
    return moment.replace(minute=moment.minute // SLOT_MINUTES * SLOT_MINUTES,
                          second=0, microsecond=0, tzinfo=None)


def in_market_hours(moment):
    if moment.weekday() >= 5:
        return False
    minutes = moment.hour * 60 + moment.minute
    return MARKET_OPEN[0] * 60 + MARKET_OPEN[1] <= minutes <= MARKET_CLOSE[0] * 60 + MARKET_CLOSE[1]


def _slot_keys(path):
    """Set of (slot, mode, strike) already saved today (read from the file's tail)."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        return set()
    with path.open("rb") as handle:
        handle.seek(max(path.stat().st_size - 60000, 0))
        lines = handle.read().decode("utf-8", "ignore").splitlines()
    keys = set()
    for row in csv.reader(line for line in lines if line.strip()):
        if len(row) != len(COLUMNS) or row[0] == "recorded_at":
            continue
        try:
            keys.add((_slot(datetime.fromisoformat(row[0])), row[8], float(row[9])))
        except ValueError:
            continue
    return keys


def record_reading(reading, path=HISTORY_PATH):
    """Save the reading if it is inside market hours and its slot is new. Returns True if saved."""
    path = Path(path)
    moment = datetime.fromisoformat(reading["recorded_at"])
    if not in_market_hours(moment):
        return False
    key = (_slot(moment), reading["mode"], float(reading["strike"]))
    if key in _slot_keys(path):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.is_file() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if new_file:
            writer.writerow(COLUMNS)
        writer.writerow([reading.get(c, "") for c in COLUMNS])
    return True


def load_history(path=HISTORY_PATH):
    """History as a DataFrame with a datetime Time column ('' if nothing saved yet)."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        return pd.DataFrame(columns=["Time"] + COLUMNS[1:])
    frame = pd.read_csv(path)
    frame["Time"] = pd.to_datetime(frame["recorded_at"], errors="coerce")
    frame = frame.dropna(subset=["Time"]).sort_values("Time").reset_index(drop=True)
    return frame


# ---------------- stand-alone collector ----------------
def _client_from_config():
    from py5paisa import FivePaisaClient
    config = configparser.ConfigParser(interpolation=None)
    if not config.read(PROJECT_ROOT / "config.ini") or not config.has_section("5paise_login"):
        raise SystemExit("config.ini with a [5paise_login] section was not found.")
    settings = config["5paise_login"]
    cred = {k: settings[k].strip() for k in
            ("APP_NAME", "APP_SOURCE", "USER_ID", "PASSWORD", "USER_KEY", "ENCRYPTION_KEY")}
    client = FivePaisaClient(cred=cred)
    client.set_access_token(settings["access_token"].strip(), settings["CLIENT_CODE"].strip())
    return client


def main():
    parser = argparse.ArgumentParser(description="Save NIFTY synthetic-future readings every 5 minutes.")
    parser.add_argument("--strike", type=int, help="fixed strike to monitor (default: follow ATM)")
    parser.add_argument("--expiry", help="YYYY-MM-DD (default: nearest upcoming expiry)")
    parser.add_argument("--once", action="store_true", help="take one reading and exit")
    args = parser.parse_args()

    contracts = load_contracts()
    expiry = date.fromisoformat(args.expiry) if args.expiry else upcoming_expiries(contracts)[0]
    client, last_spot = _client_from_config(), None
    print(f"Monitoring NIFTY expiry {expiry}: ATM (follows spot)"
          + (f" and fixed strike {args.strike}." if args.strike else "."))
    while True:
        now = datetime.now(INDIA_TIME)
        if in_market_hours(now.replace(tzinfo=None)) or args.once:
            try:
                rows = take_reading(client, contracts, expiry, args.strike, last_spot, now)
                last_spot = rows[0]["spot"]
                saved = [record_reading(r) for r in rows]
                print(f"{rows[0]['recorded_at']} spot {rows[0]['spot']:.2f} synthetic "
                      f"{rows[0]['synthetic']:.2f} {'saved' if any(saved) else 'skipped'}")
            except RuntimeError as error:
                print(f"{now:%H:%M:%S} {error}")
        if args.once:
            return
        time.sleep(30)


if __name__ == "__main__":
    main()
