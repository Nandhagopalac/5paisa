"""Two pages that rearrange existing pieces (no calculation changes):

* Live decision page  - everything that updates live, one screen, most important first:
  expiry / fixed-strike controls -> cumulative intrinsic BUY / NO BUY strip ->
  synthetic future card (ATM table) -> TradingView-style synthetic future table with OI.
* History page - every history view in one place (synthetic 5-minute / every-change history,
  second-by-second signal history, and any extra history renderer passed in).
"""
import streamlit as st

from Option_chain import synthetic_future as core
from Option_chain import synthetic_future_panel as panel
from Option_chain import synthetic_future_view as view
from Option_chain.synthetic_future import upcoming_expiries
from Option_chain.synthetic_future_cum_intrinsic import render_cum_intrinsic
from Option_chain.synthetic_future_signal_history import render_signal_history_tab


def _panel_live(client, contracts, futures):
    """The table shares the page's expiry instead of showing a second expiry box."""
    expiry = st.session_state.get("syn_expiry")
    if expiry is None:
        st.info("Waiting for the expiry...")
        return
    st.session_state.pn_expiry = expiry
    panel._live(client, contracts, futures)


def render_live_page(client):
    path = core.SCRIP_MASTER_PATH
    mtime = path.stat().st_mtime if path.exists() else 0
    try:
        contracts = view._contracts(str(path), mtime)
        panel_contracts, futures = panel._load(str(path), mtime)
    except Exception as error:
        st.error(f"Could not read scrip_master.csv: {error}")
        return
    expiries = upcoming_expiries(contracts)
    if not expiries:
        st.error("No upcoming NIFTY expiry in scrip_master.csv. Run "
                 "`python Cache/cachefile.py --refresh-cache` to download the latest contracts.")
        return
    st.markdown(
        "<style>div[class*='st-key-livepage'] [data-testid='stVerticalBlock']{gap:.4rem}"
        "div[class*='st-key-livepage'] label p{font-size:.75rem}</style>", unsafe_allow_html=True)
    with st.container(key="livepage"):
        if hasattr(st, "fragment"):
            # each block is its own fragment: refreshing one never resets the page or another block
            st.fragment(view._controls)(expiries)
            render_cum_intrinsic()                                  # BUY / NO BUY first
            st.fragment(run_every=view.LIVE_REFRESH_SECONDS)(view._live)(client, contracts)
            st.fragment(run_every=panel.REFRESH_SECONDS)(_panel_live)(client, panel_contracts, futures)
        else:  # old Streamlit: one pass per rerun
            view._controls(expiries)
            render_cum_intrinsic()
            view._live(client, contracts)
            _panel_live(client, panel_contracts, futures)


def render_history_page(extra_history=None):
    """All history, newest information first. `extra_history` is an optional extra renderer."""
    with st.expander("🧭 Synthetic future history (every 5 minutes / every price change)", expanded=True):
        if hasattr(st, "fragment"):
            st.fragment(run_every=5)(view._history)()
        else:
            view._history()
    with st.expander("📈 Intrinsic BUY / NO BUY signals, second by second", expanded=True):
        render_signal_history_tab()
    if extra_history is not None:
        with st.expander("📊 NSE derivatives volume history", expanded=False):
            if hasattr(st, "fragment"):
                st.fragment(run_every=60)(extra_history)()
            else:
                extra_history()
