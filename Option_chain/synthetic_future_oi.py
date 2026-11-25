"""Live NIFTY option OI table for ATM and five strikes on either side."""
import math
from datetime import datetime

import pandas as pd
import streamlit as st

from Option_chain import synthetic_future as core

STRIKES_EACH_SIDE = 5
REFRESH_SECONDS = 1


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _oi_values(tick):
    tick = tick or {}
    oi = _number(tick.get("OpenInterest"))
    change = _number(tick.get("ChangeInOI"))
    if change is None and oi is not None:
        previous = _number(tick.get("Prev_OI"))
        if previous is not None:
            change = oi - previous
    return oi, change


def take_oi_snapshot(client, contracts, expiry, last_spot=None):
    """Fetch OI for the ATM strike and five strikes either side."""
    spot = last_spot
    if spot is None:
        quotes = core.fetch_quotes(client, [core.SPOT_REQUEST])
        spot = _number((quotes.get(core.SPOT_REQUEST["ScripCode"]) or {}).get("LastRate"))
        if spot is None:
            raise RuntimeError("Could not read the NIFTY spot price (index code 999920000).")

    for _ in range(2):
        atm = core.atm_strike(spot)
        strikes = [atm + core.STRIKE_STEP * offset
                   for offset in range(-STRIKES_EACH_SIDE, STRIKES_EACH_SIDE + 1)]
        codes = {strike: core.option_codes(contracts, expiry, strike) for strike in strikes}
        if codes.get(atm) is None:
            raise RuntimeError(f"No CE/PE contracts for ATM strike {atm} on {expiry}. "
                               "Refresh scrip_master.csv.")
        requests = [core.SPOT_REQUEST]
        for pair in codes.values():
            if pair:
                requests.extend(
                    {"Exch": "N", "ExchType": "D", "ScripCode": code}
                    for code in pair
                )
        unique = {(request["ExchType"], request["ScripCode"]): request for request in requests}
        quotes = core.fetch_quotes(client, list(unique.values()))
        new_spot = _number((quotes.get(core.SPOT_REQUEST["ScripCode"]) or {}).get("LastRate"))
        if new_spot is None:
            raise RuntimeError("Could not read the NIFTY spot price (index code 999920000).")
        if core.atm_strike(new_spot) == atm:
            spot = new_spot
            break
        spot = new_spot

    rows = []
    for strike in strikes:
        pair = codes.get(strike)
        ce_tick = quotes.get(pair[0]) if pair else None
        pe_tick = quotes.get(pair[1]) if pair else None
        ce_oi, ce_change = _oi_values(ce_tick)
        pe_oi, pe_change = _oi_values(pe_tick)
        rows.append({
            "strike": strike,
            "is_atm": strike == atm,
            "ce_oi": ce_oi,
            "ce_change": ce_change,
            "pe_change": pe_change,
            "pe_oi": pe_oi,
        })
    return {"expiry": expiry, "spot": spot, "atm": atm, "rows": rows}


def oi_totals(rows):
    """Return totals only when every requested strike has a value."""
    totals = {}
    for key in ("ce_oi", "ce_change", "pe_change", "pe_oi"):
        values = [row[key] for row in rows]
        totals[key] = sum(values) if values and all(value is not None for value in values) else None
    return totals


def _fmt(value, signed=False):
    if value is None:
        return "—"
    return f"{value:+,.0f}" if signed else f"{value:,.0f}"


def _live_oi(client, contracts):
    expiry = st.session_state.get("oi_expiry")
    try:
        data = take_oi_snapshot(
            client, contracts, expiry, last_spot=st.session_state.get("oi_last_spot")
        )
        data["updated_at"] = datetime.now(core.INDIA_TIME)
        st.session_state.oi_last_spot = data["spot"]
        st.session_state.oi_data = data
        st.session_state.oi_error = None
    except Exception as error:
        st.session_state.oi_error = str(error)

    if st.session_state.get("oi_error"):
        st.warning(st.session_state.oi_error)
    data = st.session_state.get("oi_data")
    if not data:
        if not st.session_state.get("oi_error"):
            st.info("Waiting for live OI quotes...")
        return

    rows = data["rows"]
    totals = oi_totals(rows)
    oi_values = [row["ce_oi"] for row in rows] + [row["pe_oi"] for row in rows]
    if not any(value is not None for value in oi_values):
        st.warning("5paisa returned option prices without OpenInterest values for these strikes.")
    elif any(value is None for value in oi_values):
        st.warning("Some strike OI values are unavailable; affected cumulative totals are withheld.")

    pe_change, ce_change = totals["pe_change"], totals["ce_change"]
    if pe_change is None or ce_change is None:
        bias = "Unavailable"
    elif pe_change > ce_change:
        bias = "Bullish bias (PE ΔOI leads)"
    elif ce_change > pe_change:
        bias = "Bearish bias (CE ΔOI leads)"
    else:
        bias = "Balanced"

    metrics = st.columns(5)
    metrics[0].metric("CE cumulative OI", _fmt(totals["ce_oi"]))
    metrics[1].metric("CE cumulative ΔOI", _fmt(ce_change, signed=True))
    metrics[2].metric("PE cumulative OI", _fmt(totals["pe_oi"]))
    metrics[3].metric("PE cumulative ΔOI", _fmt(pe_change, signed=True))
    metrics[4].metric("OI bias · PE ΔOI − CE ΔOI", bias)

    table = pd.DataFrame([{
        "Call OI": row["ce_oi"],
        "Call ΔOI": row["ce_change"],
        "Strike": f'{row["strike"]:,}' + (" (ATM)" if row["is_atm"] else ""),
        "Put ΔOI": row["pe_change"],
        "Put OI": row["pe_oi"],
    } for row in rows])
    st.dataframe(table, use_container_width=True, hide_index=True)
    st.caption(
        f'NIFTY {data["spot"]:,.2f} · ATM {data["atm"]:,} · Expiry {data["expiry"]:%d %b %Y} · '
        f'Updated {data["updated_at"]:%H:%M:%S} IST. '
        "Cumulative totals cover ATM ±5 strikes. ΔOI is 5paisa's change from previous OI "
        "(or current OI minus Prev_OI when available). PE ΔOI leading is only a bullish bias; "
        "OI alone does not confirm market direction."
    )


@st.cache_data(show_spinner=False)
def _contracts(path, mtime):
    return core.load_contracts(path)


def render_oi_tab(client):
    path = core.SCRIP_MASTER_PATH
    try:
        contracts = _contracts(str(path), path.stat().st_mtime if path.exists() else 0)
    except Exception as error:
        st.error(f"Could not read scrip_master.csv: {error}")
        return
    expiries = core.upcoming_expiries(contracts)
    if not expiries:
        st.error("No upcoming NIFTY expiry in scrip_master.csv. Refresh the contract master.")
        return
    st.selectbox("Weekly expiry", expiries,
                 format_func=lambda day: f"{day:%a %d %b %Y}", key="oi_expiry")
    st.caption("Live option-chain OI around ATM: five strikes above and below, plus ATM.")
    if hasattr(st, "fragment"):
        st.fragment(run_every=REFRESH_SECONDS)(_live_oi)(client, contracts)
    else:
        _live_oi(client, contracts)
