"""Streamlit view: CE vs PE volume of NSE's top 20 contracts over time."""
import altair as alt
import pandas as pd
import streamlit as st

from Option_chain.derivatives_history import HISTORY_PATH, INTERVAL_MINUTES, load_history
from Option_chain.nse_equity_derivatives_volume import format_indian

CE_COLOR, PE_COLOR = "#16a36a", "#e34b4b"


def _time_axis():
    return alt.Axis(format="%H:%M", labelAngle=0, title=None, grid=False)


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

    lines = frame.melt("Time", ["CE", "PE"], var_name="Side", value_name="Contracts")
    colours = alt.Scale(domain=["CE", "PE"], range=[CE_COLOR, PE_COLOR])
    volume_chart = (
        alt.Chart(lines).mark_line(point=True, strokeWidth=2.5)
        .encode(x=alt.X("Time:T", axis=_time_axis()),
                y=alt.Y("Contracts:Q", title="Contracts (cumulative)", scale=alt.Scale(zero=False)),
                color=alt.Color("Side:N", scale=colours, legend=alt.Legend(orient="top", title=None)),
                tooltip=[alt.Tooltip("Time:T", format="%H:%M"), "Side:N",
                         alt.Tooltip("Contracts:Q", format=",.0f")])
        .properties(height=260, title="CE vs PE volume through the day")
    )
    st.altair_chart(volume_chart, use_container_width=True)

    left, right = st.columns(2)
    lead_chart = (
        alt.Chart(frame).mark_bar()
        .encode(x=alt.X("Time:T", axis=_time_axis()),
                y=alt.Y("Lead:Q", title="CE minus PE"),
                color=alt.condition(alt.datum.Lead > 0, alt.value(CE_COLOR), alt.value(PE_COLOR)),
                tooltip=[alt.Tooltip("Time:T", format="%H:%M"),
                         alt.Tooltip("Lead:Q", format=",.0f", title="CE minus PE")])
        .properties(height=220, title="Who leads at each reading (green: CE, red: PE)")
    )
    left.altair_chart(lead_chart, use_container_width=True)

    added = frame.dropna(subset=["CE added"]).melt("Time", ["CE added", "PE added"],
                                                  var_name="Side", value_name="Added")
    added["Side"] = added["Side"].str.replace(" added", "", regex=False)
    added["Slot"] = added["Time"].dt.strftime("%H:%M")
    if added.empty:
        right.caption("The change between readings appears after the second reading.")
    else:
        change_chart = (
            alt.Chart(added).mark_bar()
            .encode(x=alt.X("Slot:O", sort=None, axis=alt.Axis(labelAngle=-90, title=None, labelOverlap=True)),
                    xOffset="Side:N",
                    y=alt.Y("Added:Q", title="Contracts added"),
                    color=alt.Color("Side:N", scale=colours, legend=None),
                    tooltip=["Slot:O", "Side:N", alt.Tooltip("Added:Q", format=",.0f")])
            .properties(height=220, title=f"Added since the previous reading (about {INTERVAL_MINUTES} min)")
        )
        right.altair_chart(change_chart, use_container_width=True)

    with st.expander("All readings"):
        table = frame[["Time", "CE", "PE", "Lead", "CE added", "PE added"]].copy()
        table["Time"] = table["Time"].dt.strftime("%d %b %H:%M")
        st.dataframe(table.iloc[::-1], hide_index=True, use_container_width=True)
        st.download_button("Download all history (CSV)", data=history.to_csv(index=False),
                           file_name="nse_top20_ce_pe_history.csv", mime="text/csv")
