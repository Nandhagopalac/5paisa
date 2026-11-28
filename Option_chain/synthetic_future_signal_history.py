"""Tab: second-by-second history of the cumulative-intrinsic BUY / NO BUY signals (CE and PE)."""
import html
from datetime import datetime

import pandas as pd
import streamlit as st

from Option_chain import synthetic_future_cum_intrinsic as ci
from Option_chain.synthetic_future import INDIA_TIME

GREEN, RED = "#16a36a", "#e34b4b"


def available_days():
    """Days that have a signal log, newest first."""
    prefix, suffix = "nifty_intrinsic_signals_", ".csv"
    names = [p.name for p in ci.STATE_DIR.glob(prefix + "*" + suffix)] if ci.STATE_DIR.is_dir() else []
    return sorted((n[len(prefix):-len(suffix)] for n in names), reverse=True)


def load_log(day):
    path = ci.log_path(day)
    if not path.is_file() or path.stat().st_size == 0:
        return pd.DataFrame(columns=ci.LOG_COLUMNS)
    return pd.read_csv(path, on_bad_lines="skip")


def summarize(frame):
    """BUY counts for CE and PE and per-half-hour breakdown."""
    if frame.empty:
        return {"seconds": 0, "ce_buys": 0, "pe_buys": 0, "both": 0, "by_slot": pd.DataFrame()}
    ce, pe = frame["ce_signal"] == "BUY", frame["pe_signal"] == "BUY"
    slot = frame["time"].str[:2] + ":" + (frame["time"].str[3:5].astype(int) // 30 * 30).astype(str).str.zfill(2)
    by_slot = pd.DataFrame({"Half-hour from": slot, "CALL BUY": ce.astype(int), "PUT BUY": pe.astype(int),
                            "Seconds": 1}).groupby("Half-hour from", as_index=False).sum()
    return {"seconds": len(frame), "ce_buys": int(ce.sum()), "pe_buys": int(pe.sum()),
            "both": int((ce & pe).sum()), "by_slot": by_slot}


def _table(frame):
    th = "padding:3px 7px;border:1px solid #d5dce8;font-size:10px;color:#334155;white-space:nowrap;background:#f8fafc;"
    td = "padding:2px 7px;border:1px solid #e3e8f0;font-size:11px;text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums;"
    heads = ["Time", "NIFTY", "Strike", "CE", "PE", "CE intrinsic", "PE intrinsic", "CE signal", "PE signal",
             "Cum CE", "Cum PE"]
    body = []

    def sig(value, leg):
        if value == "BUY":
            return f'<td style="{td}background:{GREEN};color:#fff;font-weight:800;text-align:center">✔ {leg} BUY</td>'
        return f'<td style="{td}color:#94a3b8;text-align:center">NO BUY</td>'

    def num(value):
        try:
            return f"{float(value):,.2f}"
        except (TypeError, ValueError):
            return "-"
    for r in frame.itertuples():
        body.append(
            f'<tr><td style="{td}text-align:left">{html.escape(str(r.time))}</td><td style="{td}">{num(r.spot)}</td>'
            f'<td style="{td}">{num(r.strike).replace(".00", "")}</td><td style="{td}">{num(r.ce)}</td>'
            f'<td style="{td}">{num(r.pe)}</td><td style="{td}">{num(r.ce_intrinsic)}</td>'
            f'<td style="{td}">{num(r.pe_intrinsic)}</td>{sig(r.ce_signal, 'CE')}{sig(r.pe_signal, 'PE')}'
            f'<td style="{td}">{num(r.cum_ce)}</td><td style="{td}">{num(r.cum_pe)}</td></tr>')
    def header(h):
        if h == "CE signal":   # only the two signal headers are coloured: CE green, bold
            return f'<th style="{th}background:#dcfce7;color:#15803d;font-weight:800;font-size:11px">{h}</th>'
        if h == "PE signal":   # PE red, bold
            return f'<th style="{th}background:#fee2e2;color:#b91c1c;font-weight:800;font-size:11px">{h}</th>'
        return f'<th style="{th}">{h}</th>'
    head = "".join(header(h) for h in heads)
    return ('<div style="max-height:460px;overflow:auto;border:1px solid #dde5f0;border-radius:6px;background:#fff">'
            '<table style="border-collapse:collapse;width:100%;font-family:sans-serif">'
            f'<thead style="position:sticky;top:0;z-index:1"><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>')


def _metrics(summary):
    def cell(label, value, color="#0f172a", sub=""):
        return (f'<div style="min-width:0"><div style="font-size:9px;color:#64748b">{html.escape(label)}</div>'
                f'<div style="font-size:18px;font-weight:700;color:{color}">{value}</div>'
                f'<div style="font-size:10px;color:#64748b">{html.escape(sub)}</div></div>')
    n = summary["seconds"] or 1
    return ('<div style="background:#fff;border:1px solid #dde5f0;border-radius:8px;padding:8px 12px">'
            '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:8px 14px">'
            + cell("CALL (CE) BUY signals", f'{summary["ce_buys"]:,}', GREEN, f'{summary["ce_buys"] / n:.1%} of seconds')
            + cell("PUT (PE) BUY signals", f'{summary["pe_buys"]:,}', RED, f'{summary["pe_buys"] / n:.1%} of seconds')
            + cell("Both BUY together", f'{summary["both"]:,}')
            + cell("Seconds recorded", f'{summary["seconds"]:,}') + '</div></div>')


def _body():
    days = available_days()
    today = datetime.now(INDIA_TIME).date().isoformat()
    if today not in days:
        days = [today] + days
    day = st.selectbox("Day", days, key="sig_day")
    frame = load_log(day)
    if frame.empty:
        st.info("No signals recorded for this day yet. Seconds are recorded while the "
                "'Synthetic future & strike monitor' tab is open (09:15 – 15:30).")
        return
    summary = summarize(frame)
    st.markdown(_metrics(summary), unsafe_allow_html=True)
    if not summary["by_slot"].empty:
        st.markdown("**BUY signals per half-hour**")
        st.dataframe(summary["by_slot"], hide_index=True, use_container_width=True)
    st.markdown("**Second by second (newest first)**")
    rows = st.selectbox("Rows shown", [300, 1000, 5000, "All"], key="sig_rows")
    shown = frame.iloc[::-1] if rows == "All" else frame.iloc[::-1].head(int(rows))
    st.markdown(_table(shown), unsafe_allow_html=True)
    st.download_button("Download day as CSV", frame.to_csv(index=False), f"intrinsic_signals_{day}.csv", "text/csv")
    st.caption("BUY = this second's intrinsic value is higher than each of the last 10 entries (CE and PE judged "
               "separately; zero values are skipped, and the first 10 non-zero values only fill the window). It is a rule on one number, "
               "not a prediction or advice.")


def render_signal_history_tab():
    if hasattr(st, "fragment"):
        st.fragment(run_every=2)(_body)()
    else:
        _body()


def _second_by_second():
    today = datetime.now(INDIA_TIME).date().isoformat()
    frame = load_log(today)
    st.markdown("**Second by second (newest first)**")
    if frame.empty:
        st.info("No signals recorded today yet. Seconds are recorded while the dashboard is running "
                "(09:15 – 15:30).")
        return
    rows = st.selectbox("Rows shown", [300, 1000, 5000, "All"], key="live_sig_rows")
    ordered = frame.iloc[::-1]
    st.markdown(_table(ordered if rows == "All" else ordered.head(int(rows))), unsafe_allow_html=True)


def render_second_by_second():
    """Only today's second-by-second table (used on the Live page)."""
    if hasattr(st, "fragment"):
        st.fragment(run_every=2)(_second_by_second)()
    else:
        _second_by_second()
