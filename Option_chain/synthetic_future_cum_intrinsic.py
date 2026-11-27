"""Cumulative intrinsic value for the NIFTY synthetic-future table.

Adds up the CE and PE intrinsic columns of today's saved ATM readings (one per 5 minutes)
and adds the live reading on top, so the totals move every refresh.
Intrinsic is measured as in synthetic_future.leg_values: |CE - PE| on the ITM leg.
"""
import html
from datetime import datetime

import streamlit as st

from Option_chain.synthetic_future import INDIA_TIME, leg_values, load_history

REFRESH_SECONDS = 1


def today_readings(history, day):
    """ATM rows of `day` from the saved history -> [(time, ce_intrinsic, pe_intrinsic)]."""
    if history is None or history.empty:
        return []
    frame = history[(history["Time"].dt.date == day) & (history["mode"] == "ATM")]
    return [(row.Time, float(row.ce_intrinsic), float(row.pe_intrinsic)) for row in frame.itertuples()]


def cumulative(readings, live=None):
    """Totals of saved readings plus the live (not yet saved) ATM reading, if given as (ce, pe)."""
    ce = sum(r[1] for r in readings)
    pe = sum(r[2] for r in readings)
    count = len(readings)
    if live is not None:
        ce, pe, count = ce + live[0], pe + live[1], count + 1
    net = pe - ce
    bias = "PE intrinsic leads (puts ITM more often → bearish pull)" if net > 0 else \
           "CE intrinsic leads (calls ITM more often → bullish pull)" if net < 0 else "Balanced"
    return {"ce": ce, "pe": pe, "net": net, "count": count, "bias": bias}


def cum_html(totals, updated):
    def cell(label, value, color="#0f172a", sub=""):
        return (f'<div style="min-width:130px"><div style="font-size:10px;color:#64748b">{html.escape(label)}</div>'
                f'<div style="font-size:15px;font-weight:700;color:{color}">{value}</div>'
                f'<div style="font-size:10px;color:#64748b">{html.escape(sub)}</div></div>')
    return (
        '<div style="background:#fff;border:1px solid #dde5f0;border-radius:8px;padding:8px 12px;margin-top:6px">'
        '<div style="display:flex;gap:28px;flex-wrap:wrap">'
        + cell("Cumulative CALL intrinsic (today)", f'{totals["ce"]:,.2f}', "#16a36a")
        + cell("Cumulative PUT intrinsic (today)", f'{totals["pe"]:,.2f}', "#e34b4b")
        + cell("PUT − CALL", f'{totals["net"]:+,.2f}', "#2563eb", totals["bias"])
        + cell("Readings added", f'{totals["count"]}', sub=f"5-min ATM rows + live · updated {updated:%H:%M:%S}")
        + '</div></div>')


def _render(live_rows):
    now = datetime.now(INDIA_TIME)
    readings = today_readings(load_history(), now.date())
    live = None
    atm = next((r for r in (live_rows or []) if r.get("mode") == "ATM"), None)
    if atm:
        values = leg_values(atm["strike"], atm["ce"], atm["pe"])
        live = (values["ce_intrinsic"], values["pe_intrinsic"])
        # the live row is already counted once its 5-minute slot is saved
        if readings and readings[-1][0].strftime("%H:%M") == str(atm["recorded_at"])[11:16]:
            live = None
    st.markdown(cum_html(cumulative(readings, live), now), unsafe_allow_html=True)


def render_cum_intrinsic():
    """Reads the latest live rows the main live panel stored in session_state."""
    def run():
        _render(st.session_state.get("syn_rows"))
    if hasattr(st, "fragment"):
        st.fragment(run_every=REFRESH_SECONDS)(run)()
    else:
        run()
