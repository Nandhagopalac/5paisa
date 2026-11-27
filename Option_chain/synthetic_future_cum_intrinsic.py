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
LOOKBACK = 10  # BUY needs the current value above each of the last LOOKBACK entries
STATE_DIR = HISTORY_PATH.parent

_lock = threading.Lock()
_state = {}  # day -> {"ce","pe","count","since","last_second","saved_at"}


def _path(day):
    return STATE_DIR / f"nifty_cum_intrinsic_{day}.json"


def _recent(day):
    """Last LOOKBACK CE / PE intrinsic values from today's log (so a restart keeps the window)."""
    try:
        with open(log_path(day), encoding="utf-8") as handle:
            lines = handle.read().splitlines()[1:][-LOOKBACK:]
        columns = [line.split(",") for line in lines]
        return ([float(c[5]) for c in columns], [float(c[6]) for c in columns])
    except (OSError, ValueError, IndexError):
        return [], []


def _load(day):
    try:
        data = json.loads(_path(day).read_text())
        return {"ce": float(data["ce"]), "pe": float(data["pe"]), "count": int(data["count"]),
                "since": data.get("since", ""), "last_second": data.get("last_second", ""), "saved_at": 0.0,
                "win_ce": _recent(day)[0], "win_pe": _recent(day)[1]}
    except (OSError, ValueError, KeyError):
        return {"ce": 0.0, "pe": 0.0, "count": 0, "since": "", "last_second": "", "saved_at": 0.0,
                "win_ce": [], "win_pe": []}


def _save(day, state):
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        keys = ("ce", "pe", "count", "since", "last_second")
        _path(day).write_text(json.dumps({k: state[k] for k in keys}))
    except OSError:
        pass  # the in-memory total still works


LOG_COLUMNS = ["time", "spot", "strike", "ce", "pe", "ce_intrinsic", "pe_intrinsic",
               "ce_signal", "pe_signal", "cum_ce", "cum_pe"]


def log_path(day):
    return STATE_DIR / f"nifty_intrinsic_signals_{day}.csv"


def _append_log(day, now, state, extra):
    """One line per counted second: prices, intrinsic, BUY / NO BUY for CE and PE, running totals."""
    row = [now.strftime("%H:%M:%S"), extra.get("spot", ""), extra.get("strike", ""),
           extra.get("ce", ""), extra.get("pe", ""), state["cur_ce"], state["cur_pe"],
           state["sig_ce"], state["sig_pe"],
           round(state["ce"], 2), round(state["pe"], 2)]
    try:
        path = log_path(day)
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.is_file() or path.stat().st_size == 0
        with open(path, "a", encoding="utf-8", newline="") as handle:
            if new:
                handle.write(",".join(LOG_COLUMNS) + "\n")
            handle.write(",".join(str(v) for v in row) + "\n")
    except OSError:
        pass  # the live totals still work


def add_second(now, ce_intrinsic, pe_intrinsic, only_market_hours=True, extra=None):
    """Add this second's intrinsic to today's running totals (once per second) and return them."""
    day, second = now.date().isoformat(), now.strftime("%H:%M:%S")
    with _lock:
        for old in [d for d in _state if d != day]:
            del _state[old]  # a new day starts from zero
        state = _state.setdefault(day, _load(day))
        if second != state["last_second"] and (in_market_hours(now) or not only_market_hours):
            # signal: this second's intrinsic vs the last LOOKBACK entries, CE and PE separately
            state["win_ce"], state["win_pe"] = state.get("win_ce", []), state.get("win_pe", [])
            state["cur_ce"], state["cur_pe"] = float(ce_intrinsic), float(pe_intrinsic)
            # compared with the window BEFORE this second is added to it
            state["sig_ce"] = signal(state["win_ce"], state["cur_ce"])
            state["sig_pe"] = signal(state["win_pe"], state["cur_pe"])
            state["ref_ce"] = max(state["win_ce"]) if len(state["win_ce"]) >= LOOKBACK else None
            state["ref_pe"] = max(state["win_pe"]) if len(state["win_pe"]) >= LOOKBACK else None
            state["win_ce"] = (state["win_ce"] + [state["cur_ce"]])[-LOOKBACK:]
            state["win_pe"] = (state["win_pe"] + [state["cur_pe"]])[-LOOKBACK:]
            state["ce"] += float(ce_intrinsic)
            state["pe"] += float(pe_intrinsic)
            state["count"] += 1
            state["last_second"] = second
            state["since"] = state["since"] or second
            _append_log(day, now, state, extra or {})
            if state["saved_at"] == 0.0 or now.timestamp() - state["saved_at"] >= SAVE_EVERY_SECONDS:
                state["saved_at"] = now.timestamp()
                _save(day, state)
        return dict(state)


def signal(window, current):
    """'BUY' when the current intrinsic is above every one of the last LOOKBACK entries.

    Needs a full window of LOOKBACK earlier entries; before that it stays 'NO BUY' (warming up)."""
    window = list(window or [])
    if current is None or len(window) < LOOKBACK:
        return "NO BUY"
    return "BUY" if current > max(window[-LOOKBACK:]) else "NO BUY"


def _badge(label, text, reference, current, filled):
    if reference is None:
        detail = f"warming up {filled}/{LOOKBACK}"
    else:
        detail = f"{current:,.2f} vs top of last {LOOKBACK}: {reference:,.2f}"
    if text == "BUY":
        box = ('<div style="background:#16a36a;color:#fff;font-weight:800;font-size:13px;padding:2px 8px;'
               'border-radius:6px;display:inline-block;letter-spacing:.5px">✔ BUY</div>')
    else:
        box = ('<div style="background:#f1f5f9;color:#94a3b8;font-weight:600;font-size:11px;padding:2px 8px;'
               'border-radius:6px;display:inline-block">NO BUY</div>')
    return (f'<div style="min-width:0"><div style="font-size:9px;color:#64748b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{html.escape(label)}</div>'
            f'{box}<div style="font-size:10px;color:#64748b;margin-top:2px">{detail}</div></div>')


def cum_html(state, now):
    net = state["pe"] - state["ce"]
    bias = "PUT intrinsic leads" if net > 0 else "CALL intrinsic leads" if net < 0 else "Balanced"

    def cell(label, value, color="#0f172a", sub=""):
        return (f'<div style="min-width:0"><div style="font-size:9px;color:#64748b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{html.escape(label)}</div>'
                f'<div style="font-size:13px;font-weight:700;color:{color}">{value}</div>'
                f'<div style="font-size:10px;color:#64748b">{html.escape(sub)}</div></div>')
    since = state["since"] or "—"
    return (
        '<div style="background:#fff;border:1px solid #dde5f0;border-radius:8px;padding:6px 10px;margin-top:6px">'
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(96px,1fr));gap:8px 14px">'
        + cell("Cumulative CALL intrinsic", f'{state["ce"]:,.2f}', "#16a36a", "sum of every second")
        + cell("Cumulative PUT intrinsic", f'{state["pe"]:,.2f}', "#e34b4b", "sum of every second")
        + cell("PUT − CALL", f'{net:+,.2f}', "#2563eb", bias)
        + _badge(f"CALL vs last {LOOKBACK}", state.get("sig_ce", "NO BUY"), state.get("ref_ce"),
                 state.get("cur_ce"), len(state.get("win_ce", [])))
        + _badge(f"PUT vs last {LOOKBACK}", state.get("sig_pe", "NO BUY"), state.get("ref_pe"),
                 state.get("cur_pe"), len(state.get("win_pe", [])))
        + cell("Seconds counted", f'{state["count"]:,}', sub=f"since {since} · now {now:%H:%M:%S}")
        + '</div></div>')


def _render(live_rows):
    now = datetime.now(INDIA_TIME)
    atm = next((r for r in (live_rows or []) if r.get("mode") == "ATM"), None)
    if atm:
        values = leg_values(atm["strike"], atm["ce"], atm["pe"])
        state = add_second(now, values["ce_intrinsic"], values["pe_intrinsic"],
                           extra={k: atm.get(k, "") for k in ("spot", "strike", "ce", "pe")})
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
