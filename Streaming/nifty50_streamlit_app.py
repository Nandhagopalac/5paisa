# streamlit run .\Streaming\nifty50_streamlit_app.py
import streamlit as st
import configparser
import logging
from py5paisa import FivePaisaClient
import json
import queue
from datetime import datetime, timedelta
import time
import threading
import sys
import pandas as pd
import os
from html import escape
from pathlib import Path

# --- Page Configuration ---
st.set_page_config(
    page_title="NIFTY 50 Live Feed",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown(
    """
    <style>
    :root {
        --text-color: #1e293b;
        --background-color: #f3f6fb;
        --secondary-background-color: #ffffff;
    }

    .stApp {
        background: #f3f6fb;
        color: #1e293b !important;
    }

    [data-testid="stAppViewContainer"] {
        background: #f3f6fb;
        color: #1e293b !important;
    }

    [data-testid="stHeader"] {
        background: rgba(243, 246, 251, 0.9);
    }

    [data-testid="stMain"] {
        background: transparent;
    }

    .block-container {
        max-width: 1440px;
        padding-top: 2rem;
        padding-bottom: 3rem;
    }

    [data-testid="stAppViewContainer"] h1,
    [data-testid="stAppViewContainer"] h2,
    [data-testid="stAppViewContainer"] h3 {
        color: #14213d !important;
        letter-spacing: -0.025em;
    }

    [data-testid="stMarkdownContainer"],
    [data-testid="stMarkdownContainer"] p,
    [data-testid="stMarkdownContainer"] li,
    [data-testid="stMarkdownContainer"] span,
    [data-testid="stExpander"] p,
    [data-testid="stExpander"] span,
    [data-testid="stAlert"] p,
    [data-testid="stAlert"] span {
        color: #1e293b !important;
    }

    [data-testid="stMetric"] {
        padding: 1rem 1.15rem;
        background: #ffffff;
        border: 1px solid #e3eaf3;
        border-radius: 14px;
        box-shadow: 0 4px 14px rgba(20, 33, 61, 0.045);
    }

    [data-testid="stMetricLabel"] {
        color: #64748b !important;
    }

    [data-testid="stMetricValue"] {
        color: #14213d !important;
    }

    [data-testid="stDataFrame"] {
        border: 1px solid #e3eaf3;
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 4px 14px rgba(20, 33, 61, 0.04);
    }

    [data-testid="stExpander"] {
        background: #ffffff;
        border: 1px solid #e3eaf3;
        border-radius: 12px;
    }

    [data-testid="stAlert"] {
        border-radius: 10px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- Setup Logging ---
logging.basicConfig(level=logging.ERROR)

# --- Initialize Session State ---
if 'current_data' not in st.session_state:
    st.session_state.current_data = {}
if 'data_received_count' not in st.session_state:
    st.session_state.data_received_count = 0
if 'websocket_started' not in st.session_state:
    st.session_state.websocket_started = False
if 'client' not in st.session_state:
    st.session_state.client = None
if 'instrument_details' not in st.session_state:
    st.session_state.instrument_details = {}
if 'scrip_codes' not in st.session_state:
    st.session_state.scrip_codes = []
if 'req_list' not in st.session_state:
    st.session_state.req_list = []
if 'websocket_status' not in st.session_state:
    st.session_state.websocket_status = "Not Started"
if 'last_message_time' not in st.session_state:
    st.session_state.last_message_time = None
if 'raw_messages' not in st.session_state:
    st.session_state.raw_messages = []
if 'websocket_events' not in st.session_state:
    st.session_state.websocket_events = queue.Queue()
if 'top5_impact_history' not in st.session_state:
    st.session_state.top5_impact_history = []

# --- Define paths ---
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / 'config.ini'
CSV_PATH = PROJECT_ROOT / 'nifty50_trading_data.csv'
WEIGHT_ESTIMATE_AS_OF = "2026-08-04"
NIFTY50_WEIGHT_ESTIMATES = {
    "RELIANCE": 8.91,
    "BHARTIARTL": 6.22,
    "HDFCBANK": 5.80,
    "ICICIBANK": 5.28,
    "SBIN": 4.86,
    "TCS": 4.51,
    "BAJFINANCE": 3.65,
    "LT": 2.81,
    "HINDUNILVR": 2.49,
    "INFY": 2.41,
    "SUNPHARMA": 2.39,
    "MARUTI": 2.26,
    "TITAN": 2.23,
    "M&M": 2.16,
    "ADANIENT": 2.08,
    "KOTAKBANK": 1.99,
    "AXISBANK": 1.99,
    "ADANIPORTS": 1.98,
    "HCLTECH": 1.87,
    "ITC": 1.82,
    "ULTRACEMCO": 1.79,
    "BAJAJFINSV": 1.69,
    "NTPC": 1.69,
    "BAJAJ-AUTO": 1.62,
    "JSWSTEEL": 1.60,
    "ONGC": 1.55,
    "ETERNAL": 1.53,
    "BEL": 1.46,
    "ASIANPAINT": 1.34,
    "POWERGRID": 1.34,
    "COALINDIA": 1.30,
    "SHRIRAMFIN": 1.29,
    "TATASTEEL": 1.21,
    "HINDALCO": 1.16,
    "EICHERMOT": 1.11,
    "GRASIM": 1.08,
    "SBILIFE": 0.95,
    "WIPRO": 0.94,
    "JIOFIN": 0.89,
    "TRENT": 0.83,
    "TECHM": 0.82,
    "APOLLOHOSP": 0.65,
    "CIPLA": 0.60,
    "HDFCLIFE": 0.59,
    "TATACONSUM": 0.55,
    "DRREDDY": 0.49,
    # These symbols are absent from the August 2026 snapshot; use the
    # older approximate values already present in the project.
    "HEROMOTOCO": 0.75,
    "INDUSINDBK": 0.77,
    "NESTLEIND": 1.64,
    "TATAMOTORS": 1.61,
}

# --- Load Config ---
@st.cache_resource
def load_config():
    config = configparser.ConfigParser()
    
    if not os.path.exists(CONFIG_PATH):
        st.error(f"❌ **config.ini file not found at:** {CONFIG_PATH}")
        st.stop()
    
    try:
        config.read(CONFIG_PATH)
        st.success(f"✅ Config loaded from: {CONFIG_PATH}")
        
        if not config.has_section('5paise_login'):
            st.error("❌ **Missing [5paise_login] section in config.ini**")
            st.stop()
        
        section = "5paise_login"
        required_keys = ["APP_NAME", "APP_SOURCE", "USER_ID", "PASSWORD", 
                        "USER_KEY", "ENCRYPTION_KEY", "access_token", "CLIENT_CODE"]
        
        missing_keys = [key for key in required_keys if not config.has_option(section, key)]
        
        if missing_keys:
            st.error(f"❌ **Missing required keys:** {', '.join(missing_keys)}")
            st.stop()
        
        cred = {
            "APP_NAME": config.get(section, "APP_NAME"),
            "APP_SOURCE": config.get(section, "APP_SOURCE"),
            "USER_ID": config.get(section, "USER_ID"),
            "PASSWORD": config.get(section, "PASSWORD"),
            "USER_KEY": config.get(section, "USER_KEY"),
            "ENCRYPTION_KEY": config.get(section, "ENCRYPTION_KEY")
        }
        access_token = config.get(section, "access_token")
        client_code = config.get(section, "CLIENT_CODE")
        
        return cred, access_token, client_code
        
    except Exception as e:
        st.error(f"❌ **Config error:** {e}")
        st.stop()

# --- Authenticate ---
@st.cache_resource
def authenticate():
    cred, access_token, client_code = load_config()
    try:
        client = FivePaisaClient(cred=cred)
        client.set_access_token(access_token, client_code)
        return client
    except Exception as e:
        st.error(f"❌ **Authentication error:** {e}")
        st.stop()

# --- Load NIFTY 50 Data ---
@st.cache_data
def load_nifty50_data():
    if not os.path.exists(CSV_PATH):
        st.error(f"❌ **CSV file not found:** {CSV_PATH}")
        st.stop()
    
    try:
        df = pd.read_csv(CSV_PATH)
        st.success(f"✅ CSV loaded: {len(df)} stocks")
        
        required_columns = ['exchange_token', 'tradingsymbol', 'name', 'exchange']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            st.error(f"❌ **Missing columns:** {', '.join(missing_columns)}")
            st.stop()
        
        df = df.dropna()
        df['exchange_token'] = df['exchange_token'].astype(int)
        df['tradingsymbol'] = df['tradingsymbol'].astype(str).str.strip()
        df['name'] = df['name'].astype(str).str.strip()
        df['exchange'] = df['exchange'].astype(str).str.strip()
        
        instrument_details = {}
        scrip_codes = []
        req_list = []
        
        for _, row in df.iterrows():
            scrip_code = int(row['exchange_token'])
            scrip_codes.append(scrip_code)
            
            instrument_details[scrip_code] = {
                'symbol': row['tradingsymbol'],
                'name': row['name'],
                'exchange': row['exchange']
            }
            
            req_list.append({
                "Exch": "N",
                "ExchType": "C",
                "ScripCode": scrip_code
            })
        
        return instrument_details, scrip_codes, req_list
        
    except Exception as e:
        st.error(f"❌ **Error loading CSV:** {e}")
        st.stop()

# --- Start WebSocket with Better Error Handling ---
def start_websocket(client, req_list, event_queue):
    try:
        req_data = client.Request_Feed('mf', 's', req_list)
        client.connect(req_data)
        if client.ws is None:
            raise RuntimeError("5paisa did not initialize its WebSocket.")

        sdk_on_open = client.ws.on_open

        def handle_open(ws):
            if sdk_on_open is not None:
                sdk_on_open(ws)
            event_queue.put(("status", "WebSocket Connected"))

        def handle_message(_ws, message):
            event_queue.put(("message", message))

        def handle_error(_ws, error):
            event_queue.put(("status", f"WebSocket Error ({type(error).__name__})"))

        def handle_close(_ws, close_status_code, _close_message):
            event_queue.put(("status", f"WebSocket Closed: {close_status_code}"))

        client.ws.on_open = handle_open
        client.ws.on_error = handle_error
        client.ws.on_close = handle_close
        event_queue.put(("status", "Connecting..."))
        client.receive_data(handle_message)
    except Exception as error:
        event_queue.put(("status", f"Connection Error ({type(error).__name__})"))


def process_websocket_events():
    event_queue = st.session_state.websocket_events
    while True:
        try:
            event_type, payload = event_queue.get_nowait()
        except queue.Empty:
            break

        if event_type == "status":
            st.session_state.websocket_status = payload
            continue

        if event_type != "message":
            continue

        st.session_state.last_message_time = datetime.now()
        st.session_state.websocket_status = "Receiving Data"
        if len(st.session_state.raw_messages) >= 10:
            st.session_state.raw_messages.pop(0)
        st.session_state.raw_messages.append(payload[:200])

        try:
            ticks = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            st.session_state.websocket_status = "Received invalid WebSocket JSON"
            continue

        if isinstance(ticks, dict):
            ticks = [ticks]
        if not isinstance(ticks, list):
            st.session_state.websocket_status = "Received unexpected WebSocket data"
            continue

        for tick in ticks:
            if not isinstance(tick, dict):
                continue
            try:
                scrip_code = int(tick.get("Token"))
            except (TypeError, ValueError):
                continue
            if scrip_code in st.session_state.scrip_codes:
                st.session_state.current_data[scrip_code] = tick
                st.session_state.data_received_count += 1

# --- Format Number ---
def format_number(num):
    try:
        return f"{float(num):,.2f}"
    except:
        return "0.00"


def style_ltp_by_change(data):
    styles = pd.DataFrame("", index=data.index, columns=data.columns)
    for column in ("LTP", "% Change", "Index impact (pp)"):
        styles[column] = data["Change"].map(
            lambda change: "color: green" if change > 0 else "color: red" if change < 0 else ""
        )
    return styles


def render_top5_impact_chart(chart_df, symbols):
    width, height = 1000, 360
    left, right, top, bottom = 78, 976, 38, 286
    palette = ("#0f766e", "#2563eb", "#ea580c", "#9333ea", "#0891b2")
    values = [
        float(value)
        for symbol in symbols
        for value in chart_df[symbol].dropna()
    ]
    scale = max(max((abs(value) for value in values), default=0.0) * 1.15, 0.02)

    def x_position(index, count):
        return left if count <= 1 else left + index * (right - left) / (count - 1)

    def y_position(value):
        return top + (scale - value) * (bottom - top) / (2 * scale)

    samples = len(chart_df)
    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Live five-minute estimated index impact for the top five NIFTY stocks" '
        'style="display:block;width:100%;height:auto;font-family:Arial,sans-serif">'
    ]
    parts.append(
        f'<rect x="0" y="0" width="{width}" height="{height}" rx="14" '
        'fill="#ffffff"/>'
    )
    for tick in (-scale, -scale / 2, 0, scale / 2, scale):
        y = y_position(tick)
        stroke = "#94a3b8" if tick == 0 else "#edf1f6"
        stroke_width = "1.5" if tick == 0 else "1"
        parts.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" '
            f'stroke="{stroke}" stroke-width="{stroke_width}"/>'
        )
        parts.append(
            f'<text x="{left - 10}" y="{y + 4:.1f}" text-anchor="end" '
            'font-size="11" fill="#64748b">'
            f'{tick:+.3f}</text>'
        )
    parts.append(
        f'<text x="18" y="{(top + bottom) / 2:.1f}" transform="rotate(-90 18 '
        f'{(top + bottom) / 2:.1f})" text-anchor="middle" font-size="11" '
        'font-weight="600" fill="#475569">Estimated impact (pp)</text>'
    )

    for series_index, symbol in enumerate(symbols):
        series = chart_df[symbol].tolist()
        points = [
            f'{x_position(index, samples):.1f},{y_position(float(value)):.1f}'
            for index, value in enumerate(series)
            if pd.notna(value)
        ]
        if points:
            color = palette[series_index % len(palette)]
            parts.append(
                f'<polyline fill="none" stroke="{color}" stroke-width="2.7" '
                f'stroke-linejoin="round" stroke-linecap="round" opacity="0.92" '
                f'points="{" ".join(points)}"/>'
            )
            last_point = next(
                (
                    (index, float(value))
                    for index, value in reversed(list(enumerate(series)))
                    if pd.notna(value)
                ),
                None,
            )
            if last_point is not None:
                marker_index, last_value = last_point
                marker_x = x_position(marker_index, samples)
                marker_y = y_position(last_value)
                parts.append(
                    f'<circle cx="{marker_x:.1f}" cy="{marker_y:.1f}" r="4.5" '
                    f'fill="#ffffff" stroke="{color}" stroke-width="2.5"/>'
                )
            legend_x = left + series_index * 175
            parts.append(
                f'<line x1="{legend_x}" y1="330" x2="{legend_x + 18}" y2="330" '
                f'stroke="{color}" stroke-width="3" stroke-linecap="round"/>'
                f'<text x="{legend_x + 25}" y="334" font-size="11" '
                'font-weight="600" fill="#334155">'
                f'{escape(symbol)}</text>'
            )

    if samples:
        parts.append(
            f'<text x="{left}" y="307" font-size="10" fill="#94a3b8">'
            f'{chart_df.index[0].strftime("%H:%M:%S")}</text>'
            f'<text x="{right}" y="307" text-anchor="end" font-size="10" '
            f'fill="#94a3b8">{chart_df.index[-1].strftime("%H:%M:%S")}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


# --- Check Market Hours ---
def is_market_open():
    now = datetime.now()
    current_time = now.time()
    weekday = now.weekday()  # 0=Monday, 6=Sunday
    
    # Market is closed on weekends
    if weekday >= 5:  # Saturday (5) or Sunday (6)
        return False, "Market closed (Weekend)"
    
    # Market hours: 9:15 AM to 3:30 PM
    market_open = datetime.strptime("09:15", "%H:%M").time()
    market_close = datetime.strptime("15:30", "%H:%M").time()
    
    if market_open <= current_time <= market_close:
        return True, "Market Open"
    elif current_time < market_open:
        return False, "Market not yet open"
    else:
        return False, "Market closed for the day"

# --- Main App ---
def main():
    # Header
    st.title("📊 NIFTY 50 Live Market Feed")
    st.markdown("**Real-time market data dashboard**")
    st.markdown("---")
    
    # Market Status
    is_open, market_status = is_market_open()
    if is_open:
        st.success(f"🟢 {market_status}")
    else:
        st.warning(f"🟡 {market_status}")
    
    # Enhanced Debug Information
    with st.expander("🔍 Debug Information", expanded=True):
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("**File Status:**")
            st.write(f"- Config Exists: {os.path.exists(CONFIG_PATH)}")
            st.write(f"- CSV Exists: {os.path.exists(CSV_PATH)}")
            st.write(f"- Current Time: {datetime.now().strftime('%H:%M:%S')}")
            st.write(f"- Market Status: {market_status}")
        
        with col2:
            st.write("**WebSocket Status:**")
            st.write(f"- Status: {st.session_state.websocket_status}")
            st.write(f"- Started: {st.session_state.websocket_started}")
            st.write(f"- Last Message: {st.session_state.last_message_time}")
            st.write(f"- Messages Received: {st.session_state.data_received_count}")
        
        if st.session_state.raw_messages:
            st.write("**Recent Raw Messages:**")
            for i, msg in enumerate(st.session_state.raw_messages[-3:], 1):
                st.text(f"{i}: {msg}")
    
    # Initialize client and data
    if st.session_state.client is None:
        with st.spinner("🔐 Authenticating..."):
            st.session_state.client = authenticate()
        
        with st.spinner("📊 Loading stock data..."):
            st.session_state.instrument_details, st.session_state.scrip_codes, st.session_state.req_list = load_nifty50_data()
        
        st.success("✅ Authentication successful")
        st.info(f"✅ Loaded {len(st.session_state.scrip_codes)} stocks")
    
    # Start WebSocket
    if not st.session_state.websocket_started:
        with st.spinner("🔌 Starting WebSocket..."):
            websocket_thread = threading.Thread(
                target=start_websocket,
                args=(
                    st.session_state.client,
                    st.session_state.req_list,
                    st.session_state.websocket_events,
                ),
                daemon=True,
            )
            websocket_thread.start()
            st.session_state.websocket_started = True
            st.session_state.websocket_status = "Connecting..."

    process_websocket_events()
    
    # Status Dashboard
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("🕒 Time", datetime.now().strftime('%H:%M:%S'))
    with col2:
        st.metric("📈 Stocks with Data", len(st.session_state.current_data))
    with col3:
        st.metric("📊 Total Stocks", len(st.session_state.scrip_codes))
    with col4:
        st.metric("📡 Messages", st.session_state.data_received_count)
    
    # Data Display Logic
    if len(st.session_state.current_data) == 0:
        st.info("📊 Waiting for live market data...")
        st.markdown(f"**WebSocket Status:** {st.session_state.websocket_status}")
        
        if not is_open:
            st.warning("⚠️ **Market is currently closed.** Live data may not be available.")
            st.info("💡 **During market hours (9:15 AM - 3:30 PM IST), data will appear automatically.**")
        
        time.sleep(2)
        st.rerun()
    
    else:
        # Display live data
        st.success(f"🎉 **Live data active!** Showing {len(st.session_state.current_data)} stocks")
        
        # Prepare display data
        table_data = []
        for scrip_code in st.session_state.scrip_codes:
            d = st.session_state.current_data.get(scrip_code, {})
            if not d:
                continue
                
            current_ltp = d.get("LastRate", 0)
            prev_close = d.get("PClose", 0)
            pct_change = ((current_ltp - prev_close) / prev_close * 100) if prev_close != 0 else 0
            
            details = st.session_state.instrument_details.get(scrip_code, {})
            symbol = details.get('symbol', f'SCRIP_{scrip_code}')[:12]
            weight_pct = NIFTY50_WEIGHT_ESTIMATES.get(symbol)
            index_impact = weight_pct * pct_change / 100 if weight_pct is not None else None
            
            table_data.append({
                "Symbol": symbol,
                "Company": details.get('name', 'Unknown')[:25],
                "Weight (est. %)": weight_pct,
                "LTP": current_ltp,
                "Prev Close": prev_close,
                "High": d.get("High", 0),
                "Low": d.get("Low", 0),
                "% Change": pct_change,
                "Index impact (pp)": index_impact,
                "Volume": f"{int(d.get('Volume', 0)):,}",
                "Change": pct_change,
            })
        
        if table_data:
            table_data.sort(
                key=lambda row: (
                    row["Weight (est. %)"] is None,
                    -(row["Weight (est. %)"] or 0),
                    row["Symbol"],
                )
            )
            df = pd.DataFrame(table_data)
            top5_data = [
                row for row in table_data
                if row["Weight (est. %)"] is not None
            ][:5]
            now = datetime.now()
            impact_sample = {
                "Time": now,
                **{
                    row["Symbol"]: row["Index impact (pp)"]
                    for row in top5_data
                    if row["Index impact (pp)"] is not None
                },
            }
            history = st.session_state.top5_impact_history
            history.append(impact_sample)
            cutoff = now - timedelta(minutes=5)
            st.session_state.top5_impact_history = [
                sample for sample in history
                if sample["Time"] >= cutoff
            ][-300:]
            chart_df = pd.DataFrame(
                st.session_state.top5_impact_history
            ).set_index("Time")
            top5_symbols = [
                row["Symbol"] for row in top5_data
                if row["Index impact (pp)"] is not None
            ]
            net_impact = sum(
                row["Index impact (pp)"] or 0 for row in top5_data
            )

            st.markdown("### 📊 Top 5 by Estimated Weight — Live Impact")
            st.caption(
                "Five-minute trend of each stock's estimated contribution to the "
                "NIFTY 50 move since the previous close. Above zero is positive; "
                "below zero is negative. Weight and contribution values are estimates."
            )
            if top5_symbols:
                st.markdown(
                    render_top5_impact_chart(chart_df, top5_symbols),
                    unsafe_allow_html=True,
                )

            if net_impact > 0:
                st.success(
                    f"Positive top-5 bias: {net_impact:+.3f} pp estimated impact"
                )
            elif net_impact < 0:
                st.error(
                    f"Negative top-5 bias: {net_impact:+.3f} pp estimated impact"
                )
            else:
                st.info("Top-5 bias is neutral: no net estimated contribution.")
            st.caption(
                "This is a directional market summary, not a buy/sell recommendation "
                "or an entry/exit signal. Confirm with your own strategy and risk controls."
            )
            
            # Main table
            st.markdown("### 📈 Live Market Data")
            st.caption(
                f"Sorted by estimated index weight (highest first). Main weight snapshot: "
                f"{WEIGHT_ESTIMATE_AS_OF} (third-party source); HEROMOTOCO, INDUSINDBK, "
                "NESTLEIND, and TATAMOTORS use older project estimates. Weights drift "
                "over time. The local constituent list was last updated in July 2025 "
                "and may not match current NIFTY 50 membership. Index impact is an "
                "estimate in percentage points (weight × daily % change)."
            )
            styled_df = (
                df.style.format({
                    "Weight (est. %)": "{:.2f}%",
                    "LTP": "₹{:,.2f}",
                    "Prev Close": "₹{:,.2f}",
                    "High": "₹{:,.2f}",
                    "Low": "₹{:,.2f}",
                    "% Change": "{:+.2f}%",
                    "Volume": "{}",
                    "Index impact (pp)": "{:+.3f}",
                }, na_rep="N/A")
                .apply(style_ltp_by_change, axis=None)
                .hide(axis="columns", subset=["Change"])
            )
            st.dataframe(styled_df, use_container_width=True, height=400)
            
            # Summary stats
            col1, col2, col3 = st.columns(3)
            with col1:
                gainers = len([x for x in table_data if x['Change'] > 0])
                st.metric("🟢 Gainers", gainers)
            with col2:
                losers = len([x for x in table_data if x['Change'] < 0])
                st.metric("🔴 Losers", losers)
            with col3:
                unchanged = len([x for x in table_data if x['Change'] == 0])
                st.metric("⚪ Unchanged", unchanged)
        
        time.sleep(1)
        st.rerun()

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        st.error(f"❌ **Error:** {e}")
        st.error("Please refresh the page")
