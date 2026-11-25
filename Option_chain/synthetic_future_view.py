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


def _live_card(r):
    leader = "CE" if r["atm_ce"] > r["atm_pe"] else "PE" if r["atm_pe"] > r["atm_ce"] else "Equal"
    lead = abs(r["atm_ce"] - r["atm_pe"])
    top = "".join([
        _cell("NIFTY spot", _num(r["spot"])),
        _cell("ATM strike", f'{r["atm"]:,}', f'CE {_num(r["atm_ce"])} · PE {_num(r["atm_pe"])}'),
        _cell("Synthetic future", _num(r["synthetic"]),
              f'{r["atm"]:,} {"+" if leader != "PE" else "−"} {_num(lead)} ({leader} leads)', ORANGE),
        _cell("Synthetic − spot", _signed(r["basis"]), "premium over spot" if r["basis"] >= 0 else "discount to spot",
              _tone(r["basis"])),
    ])
    bottom = "".join([
        _cell(f'Monitored strike {r["strike"]:,}', f'CE {_num(r["ce"])} · PE {_num(r["pe"])}',
              f'straddle {_num(r["straddle"])}'),
        _cell("CE intrinsic / extrinsic", f'{_num(r["ce_intrinsic"])} / {_num(r["ce_extrinsic"])}', "", GREEN),
        _cell("PE intrinsic / extrinsic", f'{_num(r["pe_intrinsic"])} / {_num(r["pe_extrinsic"])}', "", RED),
        _cell("Total extrinsic", _num(r["total_extrinsic"]), "time value left in the straddle", PURPLE),
    ])
    return (
        '<div style="background:#fff;border:1px solid #dde5f0;border-radius:8px;padding:8px 12px">'
        f'<div style="display:flex;gap:28px;flex-wrap:wrap">{top}</div>'
        '<div style="border-top:1px solid #e8edf5;margin:6px 0"></div>'
        f'<div style="display:flex;gap:28px;flex-wrap:wrap">{bottom}</div>'
        f'<div style="font-size:10px;color:#64748b;margin-top:4px">'
        f'Updated {html.escape(r["recorded_at"][11:])} IST · expiry {html.escape(r["expiry"])} · '
        f'saved every {SLOT_MINUTES} min between 09:15 and 15:30</div></div>'
    )


def _live(client, contracts):
    expiry = st.session_state.get("syn_expiry")
    mode = "FIXED" if st.session_state.get("syn_mode") == "Fixed strike" else "ATM"
    last_spot = st.session_state.get("syn_last_spot")
    # Until a strike is typed in, a fixed monitor starts at the current ATM strike.
    fixed = int(st.session_state.get("syn_strike", 0)) or (atm_strike(last_spot) if last_spot else None)
    if mode == "FIXED" and fixed is None:
        mode = "ATM"  # first reading only: learn the spot, then switch to the fixed strike
    try:
        reading = take_reading(client, contracts, expiry, mode, fixed,
                               last_spot=st.session_state.get("syn_last_spot"))
        st.session_state.syn_last_spot = reading["spot"]
        st.session_state.syn_reading = reading
        st.session_state.syn_error = None
        try:
            record_reading(reading)
        except OSError as error:
            st.session_state.syn_error = f"Could not save history: {error}"
    except Exception as error:  # network / API hiccups must not break the page
        st.session_state.syn_error = str(error)

    if st.session_state.get("syn_error"):
        st.warning(st.session_state.syn_error)
    reading = st.session_state.get("syn_reading")
    if reading:
        st.markdown(_live_card(reading), unsafe_allow_html=True)
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


def _history():
    history = load_history()
    st.markdown("**History · every 5 minutes, 09:15 – 15:30**")
    if history.empty:
        st.info("No readings saved yet. They are saved every 5 minutes between 09:15 and 15:30 while this "
                "dashboard is open. To keep collecting with it closed, run "
                "`python .\\Option_chain\\synthetic_future.py` in a terminal.")
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
    frame["melt"] = frame["total_extrinsic"].diff()
    note.caption(f"{len(frame)} readings · first {frame['Time'].iloc[0]:%H:%M}, last {frame['Time'].iloc[-1]:%H:%M} IST. "
                 "Extrinsic = premium − intrinsic; the 'Melt' column is the change in total extrinsic since the previous reading.")

    c1, c2, c3 = st.columns(3)
    c1.markdown(_lines(frame, [("spot", BLUE, "Spot"), ("synthetic", ORANGE, "Synthetic future")],
                       "Spot vs synthetic future"), unsafe_allow_html=True)
    c2.markdown(_lines(frame, [("ce_extrinsic", GREEN, "CE ext"), ("pe_extrinsic", RED, "PE ext"),
                               ("total_extrinsic", PURPLE, "Total")],
                       "Extrinsic (time) value melting"), unsafe_allow_html=True)
    c3.markdown(_lines(frame, [("ce", GREEN, "CE"), ("pe", RED, "PE"), ("straddle", PURPLE, "Straddle")],
                       "Option prices at the strike"), unsafe_allow_html=True)

    table = frame[["Time", "spot", "synthetic", "basis", "strike", "ce", "pe", "ce_intrinsic",
                   "ce_extrinsic", "pe_intrinsic", "pe_extrinsic", "total_extrinsic", "melt"]].copy()
    table["Time"] = table["Time"].dt.strftime("%H:%M")
    table.columns = ["Time", "Spot", "Synthetic", "Syn−Spot", "Strike", "CE", "PE", "CE intr.",
                     "CE ext.", "PE intr.", "PE ext.", "Total ext.", "Melt"]
    st.dataframe(table.iloc[::-1].round(2), hide_index=True, use_container_width=True, height=240)
    st.download_button("Download history (CSV)", data=history.drop(columns=["Time"]).to_csv(index=False),
                       file_name="nifty_synthetic_future_history.csv", mime="text/csv")


# ---------------- tab ----------------
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
        e_col, m_col, s_col, _ = st.columns([1, 1.3, 1, 3])
        e_col.selectbox("Weekly expiry", expiries, format_func=lambda d: f"{d:%a %d %b %Y}", key="syn_expiry")
        m_col.radio("Strike to monitor", [FOLLOW_ATM, "Fixed strike"], key="syn_mode", horizontal=True,
                    label_visibility="visible")
        last = st.session_state.get("syn_last_spot")
        s_col.number_input("Fixed strike", min_value=0, step=STRIKE_STEP, key="syn_strike",
                           value=atm_strike(last) if last else 0,
                           disabled=st.session_state.get("syn_mode") != "Fixed strike")

        if not in_market_hours(datetime.now(INDIA_TIME).replace(tzinfo=None)):
            st.caption("Market is closed: prices show the last quotes and nothing is saved until 09:15.")
        if hasattr(st, "fragment"):
            st.fragment(run_every=LIVE_REFRESH_SECONDS)(_live)(client, contracts)
            st.fragment(run_every=60)(_history)()
        else:  # old Streamlit: one pass per rerun
            _live(client, contracts)
            _history()
