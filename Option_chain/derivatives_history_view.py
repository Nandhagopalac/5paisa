"""Streamlit view: CE vs PE volume of NSE's top 20 contracts over time.

Charts are drawn as inline SVG so they do not depend on altair/vega
(which breaks on some Python/library combinations).
"""
import html

import pandas as pd
import streamlit as st

from Option_chain.derivatives_history import HISTORY_PATH, INTERVAL_MINUTES, load_history
from Option_chain.nse_equity_derivatives_volume import format_indian

CE_COLOR, PE_COLOR = "#16a36a", "#e34b4b"
GRID, TEXT = "#d9dee7", "#5b6577"
W, LEFT, RIGHT, TOP, BOTTOM = 560, 44, 8, 8, 20


def _nice_ticks(low, high, count=4):
    if high == low:
        high = low + 1
    step = (high - low) / count
    if low <= 0 <= high:  # keep a tick exactly on zero
        return [i * step for i in range(int(low // step), int(high // step) + 1)]
    return [low + step * i for i in range(count + 1)]


def _short(value):
    value = float(value)
    for limit, suffix in ((1e7, "Cr"), (1e5, "L"), (1e3, "K")):
        if abs(value) >= limit:
            return f"{value / limit:.1f}".rstrip("0").rstrip(".") + suffix
    return f"{value:.0f}"


def _frame(height, low, high, times):
    """Axes, grid and time labels. Returns (svg_parts, x(i), y(v))."""
    n = len(times)
    inner_w, inner_h = W - LEFT - RIGHT, height - TOP - BOTTOM

    def x(i):
        return LEFT + (inner_w * (i + 0.5) / n)

    def y(v):
        return TOP + inner_h * (1 - (v - low) / (high - low))

    parts = []
    for tick in _nice_ticks(low, high):
        parts.append(f'<line x1="{LEFT}" x2="{W - RIGHT}" y1="{y(tick):.1f}" y2="{y(tick):.1f}" stroke="{GRID}"/>')
        parts.append(f'<text x="{LEFT - 6}" y="{y(tick) + 4:.1f}" text-anchor="end" font-size="10" fill="{TEXT}">{_short(tick)}</text>')
    every = max(1, n // 8)
    for i in range(0, n, every):
        parts.append(f'<text x="{x(i):.1f}" y="{height - 8}" text-anchor="middle" font-size="10" fill="{TEXT}">{times[i]:%H:%M}</text>')
    return parts, x, y


def _hover(frame, x, height):
    """Invisible full-height strip per reading; hovering shows every value."""
    n = len(frame)
    slot = (W - LEFT - RIGHT) / n
    parts = []
    for i, row in frame.reset_index(drop=True).iterrows():
        text = f"{row['Time']:%H:%M}  CE {format_indian(row['CE'])}  PE {format_indian(row['PE'])}  Lead {format_indian(row['Lead'])}"
        if pd.notna(row.get("CE added")):
            text += f"  | in 10 min: CE {_signed(row['CE added'])}  PE {_signed(row['PE added'])}"
        parts.append(f'<rect x="{x(i) - slot / 2:.1f}" y="{TOP}" width="{slot:.1f}" height="{height - TOP - BOTTOM}" '
                     f'fill="#000" fill-opacity="0" onmouseover="this.setAttribute(\'fill-opacity\',0.06)" '
                     f'onmouseout="this.setAttribute(\'fill-opacity\',0)"><title>{html.escape(text)}</title></rect>')
    return parts


def _wrap(title, height, parts, legend=""):
    svg = (f'<svg viewBox="0 0 {W} {height}" width="100%" xmlns="http://www.w3.org/2000/svg" '
           f'style="font-family:sans-serif">{"".join(parts)}</svg>')
    return f'<div style="margin:6px 0 14px"><b>{html.escape(title)}</b> {legend}{svg}</div>'


def _legend():
    return (f'<span style="color:{CE_COLOR}">&#9679; CE</span> '
            f'<span style="color:{PE_COLOR}">&#9679; PE</span>')


def line_chart(frame, title, height=200):
    times = list(frame["Time"])
    values = list(frame["CE"]) + list(frame["PE"])
    low, high = min(values), max(values)
    pad = (high - low) * 0.08 or 1
    parts, x, y = _frame(height, low - pad, high + pad, times)
    for column, colour in (("CE", CE_COLOR), ("PE", PE_COLOR)):
        points = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(frame[column]))
        parts.append(f'<polyline points="{points}" fill="none" stroke="{colour}" stroke-width="2"/>')
        for i, v in enumerate(frame[column]):
            parts.append(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="2.5" fill="{colour}">'
                         f'<title>{column} {times[i]:%H:%M}: {format_indian(v)}</title></circle>')
    parts += _hover(frame, x, height)
    return _wrap(title, height, parts, _legend())


def bar_chart(frame, columns, title, height=170, legend=""):
    """Bars per time slot; one bar per column (grouped side by side)."""
    times = list(frame["Time"])
    values = [v for c in columns for v in frame[c]]
    low, high = min(0, min(values)), max(0, max(values))
    parts, x, y = _frame(height, low, high, times)
    slot = (W - LEFT - RIGHT) / len(times)
    bar = max(2.0, slot * 0.8 / len(columns))
    zero = y(0)
    for k, column in enumerate(columns):
        for i, v in enumerate(frame[column]):
            colour = (CE_COLOR if v > 0 else PE_COLOR) if len(columns) == 1 \
                else (CE_COLOR if column.startswith("CE") else PE_COLOR)
            left = x(i) - bar * len(columns) / 2 + k * bar
            top, bottom = sorted((y(v), zero))
            parts.append(f'<rect x="{left:.1f}" y="{top:.1f}" width="{bar:.1f}" height="{max(bottom - top, 0.5):.1f}" '
                         f'fill="{colour}"><title>{column} {times[i]:%H:%M}: {format_indian(v)}</title></rect>')
    parts.append(f'<line x1="{LEFT}" x2="{W - RIGHT}" y1="{zero:.1f}" y2="{zero:.1f}" stroke="{TEXT}"/>')
    parts += _hover(frame, x, height)
    return _wrap(title, height, parts, legend)


def _signed(value):
    return ("+" if value >= 0 else "−") + format_indian(abs(value))


def render_history(path=HISTORY_PATH):
    history = load_history(path)
    st.markdown("#### NSE equity derivatives · Top 20 contracts · history")
    if history.empty:
        st.info(
            f"No history saved yet. A reading is saved about every {INTERVAL_MINUTES} minutes "
            "while this dashboard is open. To keep saving when it is closed, run "
            "`python .\\Option_chain\\derivatives_history.py` in a terminal."
        )
        return

    days = sorted(history["Time"].dt.date.unique(), reverse=True)
    picker, summary = st.columns([1, 4])
    day = picker.selectbox("Day", days, format_func=lambda d: f"{d:%a %d %b %Y}", key="history_day")
    frame = history[history["Time"].dt.date == day].reset_index(drop=True)
    frame["CE added"] = frame["CE"].diff()
    frame["PE added"] = frame["PE"].diff()

    last = frame.iloc[-1]
    previous = frame.iloc[-2] if len(frame) > 1 else None
    ratio = last["PE"] / last["CE"] if last["CE"] else 0
    with summary:
        cells = st.columns(4)
        cells[0].metric("CE volume", format_indian(last["CE"]),
                        None if previous is None else _signed(last["CE"] - previous["CE"]),
                        delta_color="off")
        cells[1].metric("PE volume", format_indian(last["PE"]),
                        None if previous is None else _signed(last["PE"] - previous["PE"]),
                        delta_color="off")
        cells[2].metric("PE / CE", f"{ratio:.2f}")
        who = "CE" if last["Lead"] > 0 else "PE" if last["Lead"] < 0 else "Equal"
        cells[3].metric("Leader now", who, format_indian(abs(last["Lead"])) if who != "Equal" else None,
                        delta_color="off")
    st.caption(f"{len(frame)} readings on {day:%d %b %Y}, first {frame['Time'].iloc[0]:%H:%M}, "
               f"last {frame['Time'].iloc[-1]:%H:%M} IST.")

    top_left, top_right = st.columns([3, 2])
    top_left.markdown(line_chart(frame, "CE vs PE volume (hover for values)"), unsafe_allow_html=True)
    recent = frame.iloc[::-1].copy()  # whole day, latest first
    recent["Time"] = recent["Time"].dt.strftime("%H:%M")
    for col in ("CE", "PE", "CE added", "PE added"):
        recent[col] = recent[col].map(
            lambda v: "" if pd.isna(v) else (_signed(v) if col.endswith("added") else format_indian(v)))
    gaps = int((frame["Time"].diff() > pd.Timedelta(minutes=INTERVAL_MINUTES * 2)).sum())
    top_right.markdown(f"**Every {INTERVAL_MINUTES} min, whole day ({len(frame)} readings, latest first)**")
    if gaps:
        top_right.caption(f"{gaps} gap(s) where the dashboard was not running; the change after a gap covers the whole gap.")
    top_right.dataframe(
        recent[["Time", "CE", "PE", "CE added", "PE added"]].rename(
            columns={"CE added": "CE +", "PE added": "PE +"}),
        hide_index=True, use_container_width=True, height=300)

    left, right = st.columns(2)
    left.markdown(bar_chart(frame, ["Lead"], "Who leads (CE minus PE)"), unsafe_allow_html=True)
    changes = frame.dropna(subset=["CE added"])
    if changes.empty:
        right.caption("The change between readings appears after the second reading.")
    else:
        right.markdown(bar_chart(changes, ["CE added", "PE added"],
                                 f"Added in each {INTERVAL_MINUTES} min", legend=_legend()),
                       unsafe_allow_html=True)

    with st.expander("All readings"):
        table = frame[["Time", "CE", "PE", "Lead", "CE added", "PE added"]].copy()
        table["Time"] = table["Time"].dt.strftime("%d %b %H:%M")
        st.dataframe(table.iloc[::-1], hide_index=True, use_container_width=True)
        st.download_button("Download all history (CSV)", data=history.to_csv(index=False),
                           file_name="nse_top20_ce_pe_history.csv", mime="text/csv")
