import configparser
from datetime import datetime
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from py5paisa import FivePaisaClient
from streamlit_autorefresh import st_autorefresh

from options_monitor import (
    available_expiries,
    fetch_quotes,
    index_quote_request,
    load_scrip_master,
    nifty_contracts,
    nse_market_status,
    option_quote_request,
    QuoteDataError,
    select_atm_pair,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = Path(os.environ.get("FP_CONFIG", PROJECT_ROOT / "config.ini"))
SCRIP_MASTER_PATH = PROJECT_ROOT / "scrip_master.csv"
DEFAULT_NIFTY_INDEX_SCRIP_CODE = 999920000

st.set_page_config(
    page_title="NIFTY ATM Options Monitor",
    page_icon="📈",
    layout="wide",
)


@st.cache_resource
def create_client(config_path):
    config = configparser.ConfigParser(interpolation=None)
    if not config.read(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    section_name = "5paise_login"
    if not config.has_section(section_name):
        raise configparser.NoSectionError(section_name)

    section = config[section_name]
    credential_keys = (
        "APP_NAME",
        "APP_SOURCE",
        "USER_ID",
        "PASSWORD",
        "USER_KEY",
        "ENCRYPTION_KEY",
    )
    missing = [key for key in credential_keys if not section.get(key, "").strip()]
    missing.extend(
        key
        for key in ("access_token", "CLIENT_CODE")
        if not section.get(key, "").strip()
    )
    if missing:
        raise ValueError(
            f"Missing required settings in [{section_name}]: {', '.join(missing)}"
        )

    credentials = {key: section[key].strip() for key in credential_keys}
    client = FivePaisaClient(cred=credentials)
    client.set_access_token(
        section["access_token"].strip(),
        section["CLIENT_CODE"].strip(),
    )
    return client


@st.cache_data
def read_contracts(path, modified_time):
    del modified_time
    return nifty_contracts(load_scrip_master(path))


def show_error(error):
    st.error(
        f"Live quote update failed ({type(error).__name__}). "
        "Check the 5paisa access token, contract master, and market/API availability."
    )


def main():
    st.title("NIFTY ATM Options Monitor")
    st.caption(
        "Read-only live monitor for the nearest NIFTY ATM call and put. "
        "It does not place orders or provide entry/exit recommendations."
    )

    with st.sidebar:
        st.header("Monitor settings")
        polling_enabled = st.toggle("Poll live quotes", value=True)
        poll_seconds = st.select_slider(
            "Polling interval",
            options=(3, 5, 10, 15, 30),
            value=5,
            format_func=lambda value: f"{value} seconds",
        )
        index_scrip_code = st.number_input(
            "NIFTY index scrip code",
            min_value=1,
            value=DEFAULT_NIFTY_INDEX_SCRIP_CODE,
            step=1,
            help=(
                "Default: 999920000. Change this only if you have verified a "
                "different 5paisa NIFTY index code."
            ),
        )
        reload_contracts = st.button("Reload local contract master")
        reconnect_client = st.button("Reconnect 5paisa client")

    if int(index_scrip_code) != DEFAULT_NIFTY_INDEX_SCRIP_CODE:
        st.warning(
            f"Using custom NIFTY index code {int(index_scrip_code)}. "
            f"The configured default is {DEFAULT_NIFTY_INDEX_SCRIP_CODE}; "
            "restore it if this custom code is not verified."
        )

    if reload_contracts:
        read_contracts.clear()
    if reconnect_client:
        create_client.clear()

    try:
        modified_time = SCRIP_MASTER_PATH.stat().st_mtime
        contracts = read_contracts(str(SCRIP_MASTER_PATH), modified_time)
        expiries = available_expiries(contracts)
    except Exception as error:
        show_error(error)
        st.stop()

    if not expiries:
        st.error("No unexpired NIFTY option expiries are available in scrip_master.csv.")
        st.stop()

    selected_expiry = st.selectbox(
        "Expiry",
        options=expiries,
        index=0,
        format_func=lambda expiry: expiry.strftime("%d %b %Y"),
    )

    if "option_history" not in st.session_state:
        st.session_state.option_history = []

    market_open, market_message = nse_market_status(
        datetime.now(ZoneInfo("Asia/Kolkata"))
    )
    if market_open:
        st.success(f"{market_message} · India time")
        try:
            client = create_client(str(CONFIG_PATH))
            request_codes = {
                int(index_scrip_code): index_quote_request(index_scrip_code)
            }
            spot = fetch_quotes(client, request_codes)[int(index_scrip_code)]
            atm_strike, pair = select_atm_pair(contracts, selected_expiry, spot)
            option_codes = {
                int(pair[option_type]["ScripCode"]): option_quote_request(
                    pair[option_type]
                )
                for option_type in ("CE", "PE")
            }
            option_quotes = fetch_quotes(client, option_codes)
            ce_code = int(pair["CE"]["ScripCode"])
            pe_code = int(pair["PE"]["ScripCode"])
            ce_ltp = option_quotes[ce_code]
            pe_ltp = option_quotes[pe_code]
        except QuoteDataError as error:
            st.error(f"Market quote unavailable: {error}")
        except Exception as error:
            show_error(error)
        else:
            polled_at = datetime.now(ZoneInfo("Asia/Kolkata"))
            history_contract = (selected_expiry.isoformat(), float(atm_strike))
            if st.session_state.get("history_contract") != history_contract:
                st.session_state.option_history = []
                st.session_state.history_contract = history_contract
            st.session_state.option_history.append(
                {
                    "Time": polled_at,
                    "CE premium": ce_ltp,
                    "PE premium": pe_ltp,
                }
            )
            st.session_state.option_history = st.session_state.option_history[-360:]

            columns = st.columns(4)
            columns[0].metric("NIFTY spot", f"{spot:,.2f}")
            columns[1].metric("ATM strike", f"{atm_strike:,.0f}")
            columns[2].metric("ATM CE", f"₹{ce_ltp:,.2f}")
            columns[3].metric("ATM PE", f"₹{pe_ltp:,.2f}")
            st.caption(
                f"Expiry: {selected_expiry:%d %b %Y} · "
                f"Last successful poll: {polled_at:%H:%M:%S IST}"
            )

            history = pd.DataFrame(st.session_state.option_history).set_index("Time")
            st.subheader("ATM option premium history")
            st.line_chart(history[["CE premium", "PE premium"]], height=360)
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Option": "CE",
                            "Strike": atm_strike,
                            "Scrip code": ce_code,
                            "LTP": ce_ltp,
                        },
                        {
                            "Option": "PE",
                            "Strike": atm_strike,
                            "Scrip code": pe_code,
                            "LTP": pe_ltp,
                        },
                    ]
                ),
                hide_index=True,
                use_container_width=True,
            )
    else:
        st.info(
            f"{market_message}. Live quote requests are paused until the "
            "scheduled weekday session (09:15–15:30 IST)."
        )

    st.caption(
        "Contract metadata comes from the local scrip_master.csv. "
        "Refresh it with `python .\\Cache\\cachefile.py --refresh-cache` if needed. "
        "Polling may be delayed or unavailable outside market hours."
    )
    st.warning(
        "Market data can be delayed, stale, or incomplete. Verify quotes and "
        "liquidity independently before making any trading decision."
    )

    if polling_enabled:
        st_autorefresh(
            interval=poll_seconds * 1000,
            key="nifty-atm-options-poll",
        )


if __name__ == "__main__":
    main()
