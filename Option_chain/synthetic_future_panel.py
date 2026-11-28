"""NIFTY synthetic-future panel (a Python version of the TradingView table).

Shows, for one expiry:
    Spot, ATM CE and PE LTP, Strike + (CE - PE), Synthetic future, the near-month future
    with its basis (future - synthetic), the last option trade time, and a small option
    chain around ATM (CE Prev / Chg % / LTP | Strike | PE LTP / Chg % / Prev).

Everything refreshes every second from 5paisa's REST market feed.
"""
import html
import re
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from Option_chain import synthetic_future as core
from Option_chain import synthetic_future_cum_oi as oi_view
from Option_chain.synthetic_future import (
    INDIA_TIME, SPOT_REQUEST, STRIKE_STEP, atm_strike, fetch_quotes, option_codes,
    synthetic_future, upcoming_expiries,
)

STRIKES_EACH_SIDE = 10
REFRESH_SECONDS = 1

# TradingView-like palette
TITLE_BG, LABEL_BG, VALUE_BG = "#2a1b9b", "#787b86", "#787b86"
ORANGE, TEAL = "#f0a868", "#009b7d"
UP_BG, DOWN_BG, PREV_BG, STRIKE_BG = "#2e7d32", "#c62828", "#a24b4b", "#787b86"


# ---------------- data ----------------
def load_futures(path=core.SCRIP_MASTER_PATH):
    """NIFTY futures contracts: columns Expiry (date), ScripCode."""
    master = pd.read_csv(path, low_memory=False,
                         usecols=["Exch", "ExchType", "ScripCode", "Expiry", "ScripType", "SymbolRoot"])
    keep = (master["SymbolRoot"].fillna("").astype(str).str.upper().eq(core.UNDERLYING)
            & master["Exch"].eq("N") & master["ExchType"].eq("D") & master["ScripType"].eq("XX"))
    frame = master[keep].copy()
    frame["Expiry"] = pd.to_datetime(frame["Expiry"], errors="coerce").dt.date
    return frame.dropna(subset=["Expiry", "ScripCode"]).assign(
        ScripCode=lambda f: f["ScripCode"].astype(int)).sort_values("Expiry")[["Expiry", "ScripCode"]]


def near_future(futures, today=None):
    """(expiry, scrip code) of the nearest future that has not expired, or None."""
    today = today or datetime.now(INDIA_TIME).date()
    rows = futures[futures["Expiry"] >= today]
    return None if rows.empty else (rows.iloc[0]["Expiry"], int(rows.iloc[0]["ScripCode"]))


def trade_time(tick, now=None):
    """Time of the last trade from a quote's TickDt ('/Date(ms)/'), shown in IST, or '' if unknown."""
    match = re.search(r"(\d{10,})", str((tick or {}).get("TickDt") or ""))
    if not match:
        return ""
    moment = datetime.fromtimestamp(int(match.group(1)) / 1000, tz=timezone.utc)
    for candidate in (moment.astimezone(INDIA_TIME), moment.replace(tzinfo=INDIA_TIME)):
        if 9 <= candidate.hour <= 15:
            return f"{candidate:%d-%b %H:%M}"  # whichever reading falls inside market hours
    return f"{moment.astimezone(INDIA_TIME):%d-%b %H:%M}"


def _leg(tick):
    ltp = float((tick or {}).get("LastRate") or 0)
    prev = float((tick or {}).get("PClose") or 0)
    chg = (ltp - prev) / prev * 100 if prev and ltp else None
    return {"ltp": ltp or None, "prev": prev or None, "chg": chg, "oi": oi_view.oi_from_tick(tick)}


def take_panel(client, contracts, futures, expiry, last_spot=None):
    """One live snapshot for the panel. Raises RuntimeError with a readable reason."""
    spot = last_spot
    if spot is None:
        spot = fetch_quotes(client, [SPOT_REQUEST]).get(SPOT_REQUEST["ScripCode"], {}).get("LastRate") or None
        if not spot:
            raise RuntimeError("Could not read the NIFTY spot price (index code 999920000).")
    future = near_future(futures)

    for _ in range(2):  # retry once if the spot moved to a new ATM strike
        atm = atm_strike(spot)
        strikes = [atm + STRIKE_STEP * k for k in range(STRIKES_EACH_SIDE, -STRIKES_EACH_SIDE - 1, -1)]
        requests, codes = [SPOT_REQUEST], {}
        for strike in strikes:
            pair = option_codes(contracts, expiry, strike)
            if pair:
                codes[strike] = pair
                requests += [{"Exch": "N", "ExchType": "D", "ScripCode": c} for c in pair]
        if atm not in codes:
            raise RuntimeError(f"No CE/PE contracts for strike {atm} on {expiry}. "
                               "Refresh scrip_master.csv (python Cache/cachefile.py --refresh-cache).")
        if future:
            requests.append({"Exch": "N", "ExchType": "D", "ScripCode": future[1]})
        quotes = fetch_quotes(client, requests)
        new_spot = float((quotes.get(SPOT_REQUEST["ScripCode"]) or {}).get("LastRate") or 0)
        if not new_spot:
            raise RuntimeError("Could not read the NIFTY spot price (index code 999920000).")
        same = atm_strike(new_spot) == atm
        spot = new_spot
        if same:
            break

    chain = []
    for strike in strikes:
        if strike in codes:
            ce_code, pe_code = codes[strike]
            chain.append({"strike": strike, "ce": _leg(quotes.get(ce_code)), "pe": _leg(quotes.get(pe_code))})
    centre = next(r for r in chain if r["strike"] == atm)
    ce, pe = centre["ce"]["ltp"], centre["pe"]["ltp"]
    if ce is None or pe is None:
        raise RuntimeError(f"No price for the ATM {atm} CE/PE yet.")

    oi_diag = oi_view.fill_missing_oi(client, chain, expiry)  # OI usually comes from the option chain
    oi_summary = oi_view.summarize(chain, atm)
    oi_summary["diag"] = oi_diag
    synthetic = synthetic_future(atm, ce, pe)
    fut_price = None
    if future:
        fut_price = float((quotes.get(future[1]) or {}).get("LastRate") or 0) or None
    last_trade = max((trade_time(quotes.get(c)) for c in codes[atm]), default="")
    return {
        "expiry": expiry, "spot": spot, "atm": atm, "ce": ce, "pe": pe,
        "diff": ce - pe, "synthetic": synthetic,
        "future": fut_price, "future_expiry": future[0] if future else None,
        "basis": None if fut_price is None else fut_price - synthetic,
        "last_trade": last_trade, "chain": chain,
        "oi": oi_summary,
    }


# ---------------- drawing ----------------
def _n(value, decimals=2):
    if value is None:
        return "-"
    text = f"{value:.{decimals}f}"
    return text.rstrip("0").rstrip(".") if decimals and "." in text else text


def _row(label, value, value_bg=VALUE_BG, label_bg=LABEL_BG):
    cell = "padding:2px 6px;color:#fff;text-align:center;border:1px solid #fff;font-size:11px;line-height:1.25;"
    return (f'<tr><td style="{cell}background:{label_bg}">{html.escape(label)}</td>'
            f'<td style="{cell}background:{value_bg}">{value}</td></tr>')


def panel_html(d):
    future_text = "-" if d["future"] is None else (
        f'{_n(d["future"])} (basis {d["basis"]:+.2f})' if d["basis"] is not None else _n(d["future"]))
    future_name = (f'NIFTY FUT {d["future_expiry"]:%d %b %Y}' if d["future_expiry"] else "-")
    summary = "".join([
        _row("Spot", _n(d["spot"])),
        _row(f'CE {d["atm"]} LTP', _n(d["ce"])),
        _row(f'PE {d["atm"]} LTP', _n(d["pe"])),
        _row("Strike + (CE-PE)", _n(d["diff"])),
        _row("Synthetic Future", _n(d["synthetic"]), ORANGE, ORANGE),
        _row("Future", future_text, TEAL, TEAL),
        _row("Future symbol", html.escape(future_name)),
        _row("Last option trade", html.escape(d["last_trade"] or "-")),
        oi_view.rows_html(d, _row),
    ])

    cell = "padding:1px 2px;color:#fff;text-align:center;border:1px solid #fff;font-size:10px;line-height:1.2;white-space:nowrap;"
    head_bg = TITLE_BG
    heads = ("CE Prev", "CE Chg %", "CE Ltp", "Strike", "PE Ltp", "PE Chg %", "PE Prev")
    chain = [f'<tr><td colspan="3" style="{cell}background:{head_bg};font-weight:700">CALL</td>'
             f'<td style="{cell}background:{head_bg}"></td>'
             f'<td colspan="3" style="{cell}background:{head_bg};font-weight:700">PUT</td></tr>',
             "<tr>" + "".join(f'<td style="{cell}background:{LABEL_BG}">{h}</td>' for h in heads) + "</tr>"]

    def chg_cell(leg, bg_override=None):
        chg = leg["chg"]
        if bg_override:
            return f'<td style="{cell}background:{bg_override}">{"-" if chg is None else f"{chg:.2f}%"}</td>'
        bg = DOWN_BG if chg is not None and chg < 0 else UP_BG
        return f'<td style="{cell}background:{bg}">{"-" if chg is None else f"{chg:.2f}%"}</td>'

    for r in d["chain"]:
        atm_row = r["strike"] == d["atm"]
        o = ORANGE if atm_row else None
        ce, pe = r["ce"], r["pe"]
        tint = lambda bg: o or bg
        chain.append(
            "<tr>"
            f'<td style="{cell}background:{tint(PREV_BG)}">{_n(ce["prev"])}</td>'
            + chg_cell(ce, o)
            + f'<td style="{cell}background:{tint(UP_BG)}">{_n(ce["ltp"])}</td>'
            f'<td style="{cell}background:{tint(STRIKE_BG)};font-weight:700">{r["strike"]}</td>'
            f'<td style="{cell}background:{tint(UP_BG)}">{_n(pe["ltp"])}</td>'
            + chg_cell(pe, o)
            + f'<td style="{cell}background:{tint(PREV_BG)}">{_n(pe["prev"])}</td></tr>')

    title = (f'<div style="background:{TITLE_BG};color:#fff;text-align:center;padding:3px;font-weight:700;'
             f'font-size:11px;border:1px solid #fff">NIFTY | Synthetic Future | Exp {d["expiry"]:%d-%m-%y}</div>')
    # summary on the left, strike chain on the right; wraps to one column in a narrow / split window
    return (f'<div style="max-width:900px;font-family:sans-serif">{title}'
            '<div style="display:flex;flex-wrap:wrap;gap:8px;align-items:flex-start">'
            f'<div style="flex:1 1 300px;min-width:0"><table style="border-collapse:collapse;width:100%;'
            f'table-layout:fixed;margin:0">{summary}</table></div>'
            f'<div style="flex:1.3 1 380px;min-width:0"><table style="border-collapse:collapse;width:100%;'
            f'table-layout:fixed;margin:0">{"".join(chain)}</table></div></div>'
            f'<div style="font-size:10px;color:#64748b;margin-top:4px">Basis = future − synthetic future. '
            f'Chg % is against the previous close. Updated {datetime.now(INDIA_TIME):%H:%M:%S} IST.</div></div>')


# ---------------- tab ----------------
@st.cache_data(show_spinner=False)
def _load(path, mtime):
    return core.load_contracts(path), load_futures(path)


def _controls(expiries):
    st.selectbox("Expiry", expiries, format_func=lambda d: f"{d:%a %d %b %Y}", key="pn_expiry")


def _live(client, contracts, futures):
    try:
        data = take_panel(client, contracts, futures, st.session_state.get("pn_expiry"),
                          last_spot=st.session_state.get("pn_spot"))
        st.session_state.pn_spot = data["spot"]
        try:  # cumulative OI: live change vs earlier snapshots, then save this slot's snapshot
            today = datetime.now(INDIA_TIME).date()
            data["oi_change"] = oi_view.changes(data["oi"], oi_view.load_snapshots(today))
            oi_view.record_snapshot(data["oi"]["oi_map"], data["expiry"])
            data["oi_update"] = oi_view.track_updates(st.session_state.setdefault("pn_oi_state", {}), data["oi"])
        except Exception:  # OI is extra; never break the table
            data["oi_change"] = {}
        st.session_state.pn_data = data
        st.session_state.pn_error = None
    except Exception as error:  # network / API hiccups must not break the page
        st.session_state.pn_error = str(error)
    if st.session_state.get("pn_error"):
        st.warning(st.session_state.pn_error)
    if st.session_state.get("pn_data"):
        st.markdown(panel_html(st.session_state.pn_data), unsafe_allow_html=True)
    elif not st.session_state.get("pn_error"):
        st.info("Waiting for prices...")


def render_panel_tab(client):
    path = core.SCRIP_MASTER_PATH
    try:
        contracts, futures = _load(str(path), path.stat().st_mtime if path.exists() else 0)
    except Exception as error:
        st.error(f"Could not read scrip_master.csv: {error}")
        return
    expiries = upcoming_expiries(contracts)
    if not expiries:
        st.error("No upcoming NIFTY expiry in scrip_master.csv. Run "
                 "`python Cache/cachefile.py --refresh-cache` to download the latest contracts.")
        return
    left, _ = st.columns([1, 1])
    with left:
        if hasattr(st, "fragment"):
            st.fragment(_controls)(expiries)  # a fragment, so changing it does not jump to the first tab
            st.fragment(run_every=REFRESH_SECONDS)(_live)(client, contracts, futures)
        else:
            _controls(expiries)
            _live(client, contracts, futures)
