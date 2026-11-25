"""Streamlit tab: NIFTY synthetic future (live, every second) and strike monitor.

Live part: spot -> ATM strike -> synthetic future = ATM strike + CE - PE, plus the
intrinsic / extrinsic split for the monitored strike.
History part: one reading every 5 minutes from 09:15 to 15:30 (see synthetic_future.py).
Charts are inline SVG (no altair dependency).
"""
import html
import time
from datetime import datetime

import pandas as pd
import streamlit as st

from Option_chain.derivatives_history_view import (
    BOTTOM, GRID, LEFT, RIGHT, TEXT, TOP, W, _frame, _wrap,
)
from Option_chain.synthetic_future import (
    HISTORY_PATH, INDIA_TIME, SLOT_MINUTES, STRIKE_STEP, atm_strike, load_contracts,
    load_history, record_reading, take_reading, upcoming_expiries, in_market_hours,
)
from Option_chain import synthetic_future as _core

LIVE_REFRESH_SECONDS = 1
GREEN, RED, BLUE, ORANGE, PURPLE = "#16a36a", "#e34b4b", "#2563eb", "#ea580c", "#7c3aed"
FOLLOW_ATM = "ATM (follows spot)"


@st.cache_data(show_spinner=False)
def _contracts(path, mtime):
    return load_contracts(path)


def _num(value, decimals=2):
    return "-" if value is None or pd.isna(value) else f"{value:,.{decimals}f}"


def _signed(value, decimals=2):
    return "-" if value is None or pd.isna(value) else f"{value:+,.{decimals}f}".replace("-", "−")


def _tone(value):
    return GREEN if value > 0 else RED if value < 0 else "#475569"


# ---------------- live ----------------
def _cell(label, value, sub="", color="#0f172a"):
    return (f'<div style="min-width:110px"><div style="font-size:10px;color:#64748b">{html.escape(label)}</div>'
            f'<div style="font-size:15px;font-weight:700;color:{color};font-variant-numeric:tabular-nums">{value}</div>'
            f'<div style="font-size:10px;color:#64748b">{sub}</div></div>')


def _dash(value, decimals=2):
    return "-" if not value else f"{value:,.{decimals}f}"


def _calc_rows(rows):
    """rows: [{time, strike, ce, pe}] -> display dicts in the 'future / premium / intrinsic / extrinsic' layout."""
    out = []
    for r in rows:
        strike, ce, pe = float(r["strike"]), float(r["ce"]), float(r["pe"])
        legs = _core.leg_values(strike, ce, pe)
        diff = ce - pe
        future = strike + diff
        out.append({
            "time": r["time"], "strike": strike, "ce": ce, "pe": pe, "future": future,
            "ce_state": "ITM" if diff > 0 else "ATM" if diff == 0 else "OTM",
            "pe_state": "ITM" if diff < 0 else "ATM" if diff == 0 else "OTM",
            "how": f"{strike:,.0f} + {ce:,.2f} − {pe:,.2f} = {future:,.2f}", **legs,
        })
    return out


def _calc_table(rows, max_height=None):
    """Call | Strike | Put table: Future(strike+IV), ITM/OTM, premium, intrinsic, extrinsic."""
    th = "padding:3px 7px;border:1px solid #d5dce8;font-size:10px;color:#334155;white-space:nowrap;"
    td = "padding:3px 7px;border:1px solid #e3e8f0;font-size:11px;text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap;"
    call_bg, put_bg, mid_bg = "#f0fdf4", "#fef2f2", "#f1f5f9"
    head = (
        f'<tr><th style="{th}background:#fff" rowspan="2">Time</th>'
        f'<th style="{th}background:{call_bg};color:{GREEN}" colspan="5">CALL</th>'
        f'<th style="{th}background:{mid_bg}" rowspan="2">STRIKE</th>'
        f'<th style="{th}background:{put_bg};color:{RED}" colspan="5">PUT</th>'
        f'<th style="{th}background:#fff" rowspan="2">How it is calculated</th></tr><tr>'
        + "".join(f'<th style="{th}background:{call_bg}">{h}</th>' for h in
                  ("FUTURE (Strike + IV)", "ITM / OTM", "Premium", "Intrinsic", "Extrinsic"))
        + "".join(f'<th style="{th}background:{put_bg}">{h}</th>' for h in
                  ("Intrinsic", "Extrinsic", "Premium", "ITM / OTM", "FUTURE (Strike − IV)"))
        + '</tr>')
    body = []
    for r in rows:
        call_future = f'<b style="color:{GREEN}">{r["future"]:,.2f}</b>' if r["ce_state"] != "OTM" else "-"
        put_future = f'<b style="color:{RED}">{r["future"]:,.2f}</b>' if r["pe_state"] == "ITM" else "-"
        ci = f'<b style="color:{BLUE}">{r["ce_intrinsic"]:,.2f}</b>' if r["ce_intrinsic"] else "-"
        pi = f'<b style="color:{BLUE}">{r["pe_intrinsic"]:,.2f}</b>' if r["pe_intrinsic"] else "-"
        body.append(
            f'<tr><td style="{td}text-align:left">{html.escape(r["time"])}</td>'
            f'<td style="{td}background:{call_bg}">{call_future}</td>'
            f'<td style="{td}background:{call_bg};text-align:center">{r["ce_state"]}</td>'
            f'<td style="{td}background:{call_bg}"><b>{r["ce"]:,.2f}</b></td>'
            f'<td style="{td}background:{call_bg}">{ci}</td>'
            f'<td style="{td}background:{call_bg}">{r["ce_extrinsic"]:,.2f}</td>'
            f'<td style="{td}background:{mid_bg};text-align:center"><b>{r["strike"]:,.0f}</b></td>'
            f'<td style="{td}background:{put_bg}">{pi}</td>'
            f'<td style="{td}background:{put_bg}">{r["pe_extrinsic"]:,.2f}</td>'
            f'<td style="{td}background:{put_bg}"><b>{r["pe"]:,.2f}</b></td>'
            f'<td style="{td}background:{put_bg};text-align:center">{r["pe_state"]}</td>'
            f'<td style="{td}background:{put_bg}">{put_future}</td>'
            f'<td style="{td}text-align:left;color:#64748b">{html.escape(r["how"])}</td></tr>')
    box = f"max-height:{max_height}px;overflow:auto;" if max_height else ""
    return (f'<div style="{box}border:1px solid #dde5f0;border-radius:6px;background:#fff">'
            '<table style="border-collapse:collapse;width:100%;font-family:sans-serif">'
            f'<thead style="position:sticky;top:0;z-index:1">{head}</thead><tbody>{"".join(body)}</tbody></table></div>')


def _live_card(rows):
    r = rows[0]  # the ATM row (always present)
    leader = "CE" if r["atm_ce"] > r["atm_pe"] else "PE" if r["atm_pe"] > r["atm_ce"] else "Equal"
    lead = abs(r["atm_ce"] - r["atm_pe"])
    top = "".join([
        _cell("NIFTY spot", _num(r["spot"])),
        _cell("ATM strike", f'{r["atm"]:,}', f'CE {_num(r["atm_ce"])} · PE {_num(r["atm_pe"])}'),
        _cell("Synthetic future (ATM)", _num(r["synthetic"]),
              f'{r["atm"]:,} {"+" if leader != "PE" else "−"} {_num(lead)} ({leader} leads)', ORANGE),
        _cell("Synthetic − spot", _signed(r["basis"]), "premium over spot" if r["basis"] >= 0 else "discount to spot",
              _tone(r["basis"])),
        _cell("Total extrinsic (ATM)", _num(r["total_extrinsic"]), f'straddle {_num(r["straddle"])}', PURPLE),
    ])
    shown = _calc_rows([
        {"time": ("ATM " if x["mode"] == "ATM" else "Fixed ") + x["recorded_at"][11:],
         "strike": x["strike"], "ce": x["ce"], "pe": x["pe"]} for x in rows])
    return (
        '<div style="background:#fff;border:1px solid #dde5f0;border-radius:8px;padding:8px 12px">'
        f'<div style="display:flex;gap:28px;flex-wrap:wrap">{top}</div>'
        '<div style="height:8px"></div>' + _calc_table(shown) +
        f'<div style="font-size:10px;color:#64748b;margin-top:4px">'
        f'ATM always follows the spot. Intrinsic = CE − PE on the ITM leg (the leg with the higher premium); '
        f'extrinsic = premium − intrinsic. Expiry {html.escape(r["expiry"])} · saved every {SLOT_MINUTES} min '
        f'between 09:15 and 15:30.</div></div>'
    )


def _live(client, contracts):
    expiry = st.session_state.get("syn_expiry")
    fixed = int(st.session_state.get("syn_strike") or 0) or None
    try:
        rows = take_reading(client, contracts, expiry, fixed,
                            last_spot=st.session_state.get("syn_last_spot"))
        st.session_state.syn_last_spot = rows[0]["spot"]
        st.session_state.syn_rows = rows
        last_seen = st.session_state.setdefault("syn_last_seen", {})
        log = st.session_state.setdefault("syn_log", [])
        st.session_state.syn_error = None
        for row in rows:
            token = (row["strike"], row["ce"], row["pe"])
            if last_seen.get(row["mode"]) != token:  # keep every price change in memory for the day
                last_seen[row["mode"]] = token
                log.append({"mode": row["mode"], "time": row["recorded_at"][11:], "strike": row["strike"],
                            "ce": row["ce"], "pe": row["pe"]})
            try:
                record_reading(row)
            except OSError as error:
                st.session_state.syn_error = f"Could not save history: {error}"
        del log[:-40000]
    except Exception as error:  # network / API hiccups must not break the page
        st.session_state.syn_error = str(error)

    if st.session_state.get("syn_error"):
        st.warning(st.session_state.syn_error)
    rows = st.session_state.get("syn_rows")
    if rows:
        if fixed and not any(r["mode"] == "FIXED" for r in rows):
            st.caption(f"No price for strike {fixed:,} yet (not listed for this expiry or no trades).")
        st.markdown(_live_card(rows), unsafe_allow_html=True)
    elif not st.session_state.get("syn_error"):
        st.info("Waiting for prices...")


# ---------------- history charts ----------------
def _lines(frame, series, title, height=150):
    """series: [(column, colour, label)]. One point per saved reading; hover shows all values."""
    times = list(frame["Time"])
    values = [v for c, _, _ in series for v in frame[c].dropna()]
    low, high = min(values), max(values)
    pad = (high - low) * 0.1 or 1
    decimals = 1 if (high - low) < 20 else 0
    parts, x, y = _frame(height, low - pad, high + pad, times, lambda v: f"{v:,.{decimals}f}")
    for column, colour, _ in series:
        points = [(i, v) for i, v in enumerate(frame[column]) if pd.notna(v)]
        if len(points) > 1:
            parts.append('<polyline fill="none" stroke="%s" stroke-width="2" points="%s"/>' % (
                colour, " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in points)))
        for i, v in points:
            parts.append(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="2.2" fill="{colour}"/>')
    slot = (W - LEFT - RIGHT) / len(times)
    for i in range(len(times)):
        text = f"{times[i]:%H:%M}  " + "  ".join(f"{label} {_num(frame[c].iloc[i])}" for c, _, label in series)
        parts.append(f'<rect x="{x(i) - slot / 2:.1f}" y="{TOP}" width="{slot:.1f}" height="{height - TOP - BOTTOM}" '
                     f'fill="#000" fill-opacity="0" onmouseover="this.setAttribute(\'fill-opacity\',0.06)" '
                     f'onmouseout="this.setAttribute(\'fill-opacity\',0)"><title>{html.escape(text)}</title></rect>')
    legend = " ".join(f'<span style="color:{c}">&#9679; {html.escape(l)}</span>' for _, c, l in series)
    return _wrap(title, height, parts, legend)


def _session_log(choice):
    """In-memory price changes: ATM rows, or the rows of one fixed strike."""
    if choice == FOLLOW_ATM:
        return [r for r in st.session_state.get("syn_log", []) if r.get("mode") == "ATM"]
    strike = float(choice.replace(",", ""))
    return [r for r in st.session_state.get("syn_log", [])
            if r.get("mode") == "FIXED" and float(r["strike"]) == strike]


def _history():
    history = load_history()
    st.markdown("**History · every 5 minutes, 09:15 – 15:30**")
    if history.empty:
        st.info("No readings saved yet. They are saved every 5 minutes between 09:15 and 15:30 while this "
                "dashboard is open. To keep collecting with it closed, run "
                "`python .\\Option_chain\\synthetic_future.py` in a terminal.")
        log = _session_log(FOLLOW_ATM)
        if log:
            st.caption(f"{len(log)} ATM price changes kept in memory since this page was opened.")
            st.markdown(_calc_table(_calc_rows(log[-400:])[::-1], 340), unsafe_allow_html=True)
        return

    days = sorted(history["Time"].dt.date.unique(), reverse=True)
    pick_day, pick_strike, note = st.columns([1, 1, 4])
    day = pick_day.selectbox("Day", days, format_func=lambda d: f"{d:%a %d %b %Y}", key="syn_day")
    day_rows = history[history["Time"].dt.date == day]
    fixed_strikes = sorted(day_rows.loc[day_rows["mode"] == "FIXED", "strike"].unique())
    options = [FOLLOW_ATM] + [f"{int(s):,}" for s in fixed_strikes]
    choice = pick_strike.selectbox("Strike", options, key="syn_hist_strike")
    frame = day_rows[day_rows["mode"] == "ATM"] if choice == FOLLOW_ATM else \
        day_rows[(day_rows["mode"] == "FIXED") & (day_rows["strike"] == float(choice.replace(",", "")))]
    frame = frame.reset_index(drop=True)
    if frame.empty:
        st.info("No readings for this choice.")
        return
    note.caption(f"{len(frame)} readings · first {frame['Time'].iloc[0]:%H:%M}, last {frame['Time'].iloc[-1]:%H:%M} IST. "
                 "Intrinsic = CE − PE on the ITM leg; extrinsic = premium − intrinsic.")

    c1, c2, c3 = st.columns(3)
    c1.markdown(_lines(frame, [("spot", BLUE, "Spot"), ("synthetic", ORANGE, "Synthetic future")],
                       "Spot vs synthetic future"), unsafe_allow_html=True)
    c2.markdown(_lines(frame, [("ce_extrinsic", GREEN, "CE ext"), ("pe_extrinsic", RED, "PE ext"),
                               ("total_extrinsic", PURPLE, "Total")],
                       "Extrinsic (time) value melting"), unsafe_allow_html=True)
    c3.markdown(_lines(frame, [("ce", GREEN, "CE"), ("pe", RED, "PE"), ("straddle", PURPLE, "Straddle")],
                       "Option prices at the strike"), unsafe_allow_html=True)

    view = st.radio("Calculation history", ["Every 5 minutes (saved all day)", "Every price change (this browser session)"],
                    horizontal=True, key="syn_view")
    if view.startswith("Every 5"):
        rows = [{"time": f"{t:%H:%M}", "strike": k, "ce": c, "pe": p}
                for t, k, c, p in zip(frame["Time"], frame["strike"], frame["ce"], frame["pe"])]
        st.markdown(_calc_table(_calc_rows(rows)[::-1], 340), unsafe_allow_html=True)
    else:
        log = _session_log(choice)
        st.caption(f"{len(log)} price changes kept in memory since this page was opened "
                   "(lost when the page is reloaded; the 5-minute history above is saved on disk).")
        if log:
            st.markdown(_calc_table(_calc_rows(log[-400:])[::-1], 340), unsafe_allow_html=True)
    st.download_button("Download 5-minute history (CSV)", data=history.drop(columns=["Time"]).to_csv(index=False),
                       file_name="nifty_synthetic_future_history.csv", mime="text/csv")


# ---------------- tab ----------------
def _use_atm():
    last = st.session_state.get("syn_last_spot")
    if last:
        st.session_state.syn_strike = atm_strike(last)


def _controls(expiries):
    e_col, s_col, b_col, _ = st.columns([1, 1.2, 0.8, 3])
    e_col.selectbox("Weekly expiry", expiries, format_func=lambda d: f"{d:%a %d %b %Y}", key="syn_expiry")
    st.session_state.setdefault("syn_strike", 0)
    s_col.number_input("Also monitor a fixed strike (0 = none)", min_value=0, step=STRIKE_STEP,
                       key="syn_strike")
    b_col.button("Use current ATM", on_click=_use_atm)
    st.caption("ATM always follows the spot and is always recorded. A fixed strike is recorded next to it, "
               "so you can watch how its time value melts all day.")
    if not in_market_hours(datetime.now(INDIA_TIME).replace(tzinfo=None)):
        st.caption("Market is closed: prices show the last quotes and nothing is saved until 09:15.")


def render_synthetic_tab(client):
    mtime = _core.SCRIP_MASTER_PATH.stat().st_mtime if _core.SCRIP_MASTER_PATH.exists() else 0
    try:
        contracts = _contracts(str(_core.SCRIP_MASTER_PATH), mtime)
    except Exception as error:
        st.error(f"Could not read scrip_master.csv: {error}")
        return
    expiries = upcoming_expiries(contracts)
    if not expiries:
        st.error("No upcoming NIFTY expiry in scrip_master.csv. Run "
                 "`python Cache/cachefile.py --refresh-cache` to download the latest contracts.")
        return

    st.markdown(
        "<style>div[class*='st-key-synthetic'] [data-testid='stSelectbox'] label p,"
        "div[class*='st-key-synthetic'] label p{font-size:.75rem}</style>", unsafe_allow_html=True)
    with st.container(key="synthetic"):
        if hasattr(st, "fragment"):
            # Controls live in a fragment so using them reruns only this panel; a full rerun
            # would make Streamlit jump back to the first ("Live") tab.
            st.fragment(_controls)(expiries)
            st.fragment(run_every=LIVE_REFRESH_SECONDS)(_live)(client, contracts)
            st.fragment(run_every=5)(_history)()
        else:  # old Streamlit: one pass per rerun
            _controls(expiries)
            _live(client, contracts)
            _history()
