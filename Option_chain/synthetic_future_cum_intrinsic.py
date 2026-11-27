"""Live cumulative intrinsic value for the NIFTY synthetic-future table.

Every second the live ATM reading's CE and PE intrinsic (|CE - PE| on the ITM leg, see
synthetic_future.leg_values) is added on top of the running total, e.g.
    09:15:00  CE 23  -> total 23
    09:15:01  CE  2  -> total 25
The total is kept in memory (shared by every browser session of this server), written to a
small per-day file so a restart continues instead of starting from zero, and resets each day.
Each second is added only once, however many sessions or reruns see it.
Counting starts from the first live reading after the dashboard starts; nothing is back-filled.
"""
import html
import json
import threading
from datetime import datetime

import streamlit as st

from Option_chain.synthetic_future import (
    HISTORY_PATH, INDIA_TIME, in_market_hours, leg_values,
)

REFRESH_SECONDS = 1
SAVE_EVERY_SECONDS = 5
STATE_DIR = HISTORY_PATH.parent

_lock = threading.Lock()
_state = {}  # day -> {"ce","pe","count","since","last_second","saved_at"}


def _path(day):
    return STATE_DIR / f"nifty_cum_intrinsic_{day}.json"


def _load(day):
    try:
        data = json.loads(_path(day).read_text())
        return {"ce": float(data["ce"]), "pe": float(data["pe"]), "count": int(data["count"]),
                "since": data.get("since", ""), "last_second": data.get("last_second", ""), "saved_at": 0.0}
    except (OSError, ValueError, KeyError):
        return {"ce": 0.0, "pe": 0.0, "count": 0, "since": "", "last_second": "", "saved_at": 0.0}


def _save(day, state):
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        keys = ("ce", "pe", "count", "since", "last_second")
        _path(day).write_text(json.dumps({k: state[k] for k in keys}))
    except OSError:
        pass  # the in-memory total still works


def add_second(now, ce_intrinsic, pe_intrinsic, only_market_hours=True):
    """Add this second's intrinsic to today's running totals (once per second) and return them."""
    day, second = now.date().isoformat(), now.strftime("%H:%M:%S")
    with _lock:
        for old in [d for d in _state if d != day]:
            del _state[old]  # a new day starts from zero
        state = _state.setdefault(day, _load(day))
        if second != state["last_second"] and (in_market_hours(now) or not only_market_hours):
            state["ce"] += float(ce_intrinsic)
            state["pe"] += float(pe_intrinsic)
            state["count"] += 1
            state["last_second"] = second
            state["since"] = state["since"] or second
            if state["saved_at"] == 0.0 or now.timestamp() - state["saved_at"] >= SAVE_EVERY_SECONDS:
                state["saved_at"] = now.timestamp()
                _save(day, state)
        return dict(state)


def cum_html(state, now):
    net = state["pe"] - state["ce"]
    bias = "PUT intrinsic leads" if net > 0 else "CALL intrinsic leads" if net < 0 else "Balanced"

    def cell(label, value, color="#0f172a", sub=""):
        return (f'<div style="min-width:130px"><div style="font-size:10px;color:#64748b">{html.escape(label)}</div>'
                f'<div style="font-size:15px;font-weight:700;color:{color}">{value}</div>'
                f'<div style="font-size:10px;color:#64748b">{html.escape(sub)}</div></div>')
    since = state["since"] or "—"
    return (
        '<div style="background:#fff;border:1px solid #dde5f0;border-radius:8px;padding:8px 12px;margin-top:6px">'
        '<div style="display:flex;gap:28px;flex-wrap:wrap">'
        + cell("Cumulative CALL intrinsic", f'{state["ce"]:,.2f}', "#16a36a", "sum of every second")
        + cell("Cumulative PUT intrinsic", f'{state["pe"]:,.2f}', "#e34b4b", "sum of every second")
        + cell("PUT − CALL", f'{net:+,.2f}', "#2563eb", bias)
        + cell("Seconds counted", f'{state["count"]:,}', sub=f"since {since} · now {now:%H:%M:%S}")
        + '</div></div>')


def _render(live_rows):
    now = datetime.now(INDIA_TIME)
    atm = next((r for r in (live_rows or []) if r.get("mode") == "ATM"), None)
    if atm:
        values = leg_values(atm["strike"], atm["ce"], atm["pe"])
        state = add_second(now, values["ce_intrinsic"], values["pe_intrinsic"])
    else:
        state = dict(_state.get(now.date().isoformat()) or _load(now.date().isoformat()))
    st.markdown(cum_html(state, now), unsafe_allow_html=True)
    if not in_market_hours(now):
        st.caption("Market is closed: the cumulative totals only grow between 09:15 and 15:30.")


def render_cum_intrinsic():
    """Reads the latest live rows the main live panel stored in session_state."""
    def run():
        _render(st.session_state.get("syn_rows"))
    if hasattr(st, "fragment"):
        st.fragment(run_every=REFRESH_SECONDS)(run)()
    else:
        run()
