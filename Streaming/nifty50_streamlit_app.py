# & '.\.venv_5paisa\Scripts\python.exe' -m streamlit run '.\Streaming\nifty50_streamlit_app.py'
import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).resolve().parents[1]))  # repo root, so Option_chain imports work anywhere
import streamlit as st
import configparser
import logging
from py5paisa import FivePaisaClient
import json
import queue
from datetime import datetime, timedelta
import time
import threading
import pandas as pd
import os
from html import escape
from pathlib import Path
from Option_chain.derivatives_history import record_sample
try:
    from Option_chain.derivatives_history_view import render_history
except Exception as _history_import_error:  # keep the live dashboard working
    _HISTORY_IMPORT_ERROR = _history_import_error

    def render_history():
        st.error(f"History charts could not load: {_HISTORY_IMPORT_ERROR}")
        st.code("pip install -r requirements.txt")
try:
    from Option_chain.synthetic_future_view import render_synthetic_tab
except Exception as _synthetic_import_error:  # keep the live dashboard working
    _SYNTHETIC_IMPORT_ERROR = _synthetic_import_error

    def render_synthetic_tab(_client):
        st.error(f"Synthetic future tab could not load: {_SYNTHETIC_IMPORT_ERROR}")
try:
    from Option_chain.synthetic_future_panel import render_panel_tab
except Exception as _panel_import_error:  # keep the live dashboard working
    _PANEL_IMPORT_ERROR = _panel_import_error

    def render_panel_tab(_client):
        st.error(f"Synthetic future table could not load: {_PANEL_IMPORT_ERROR}")
try:
    from Option_chain.synthetic_future_view import render_synthetic_summary
except Exception as _summary_import_error:  # keep the live dashboard working
    _SUMMARY_IMPORT_ERROR = _summary_import_error

    def render_synthetic_summary():
        st.error(f"Synthetic summary could not load: {_SUMMARY_IMPORT_ERROR}")
try:
    from Option_chain.synthetic_future_signal_history import (
        render_second_by_second, render_signal_history_tab,
    )
except Exception as _signal_import_error:  # keep the live dashboard working
    _SIGNAL_IMPORT_ERROR = _signal_import_error

    def render_second_by_second():
        st.error(f"Signal table could not load: {_SIGNAL_IMPORT_ERROR}")

    def render_signal_history_tab():
        st.error(f"Signal history tab could not load: {_SIGNAL_IMPORT_ERROR}")
from Option_chain.nse_equity_derivatives_volume import (
    fetch_market_data,
    format_indian,
)

# ---------------- Look & feel knobs (change these to resize) ----------------
ROW_FONT_PX = 11       # font size of the stock tables (10 = smaller, 12 = bigger)
TABLE_COLUMNS = 2      # how many side-by-side tables the 50 stocks are split into
REFRESH_SECONDS = 1    # how often the data area refreshes (in place, no page reload)
DERIVATIVES_REFRESH_SECONDS = 15

# --- Page Configuration ---
st.set_page_config(
    page_title="NIFTY 50 Live",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

CSS = """
<style>
[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"],
[data-testid="stStatusWidget"], footer, #MainMenu { display: none !important; }
.stApp, [data-testid="stAppViewContainer"] { background: #eef2f8; }
.block-container, [data-testid="stMainBlockContainer"] {
    max-width: 100% !important;
    padding: 0.4rem 0.7rem 0.2rem 0.7rem !important;
}
[data-testid="stVerticalBlock"] { gap: 0.3rem; }

.topbar {
    display: flex; flex-wrap: wrap; align-items: center; gap: 5px;
    background: #14213d; border-radius: 10px; padding: 5px 10px; margin-bottom: 6px;
}
.topbar .title { font-weight: 700; font-size: 0.95rem; color: #ffffff; margin-right: 6px; }
.chip {
    display: inline-block; padding: 1px 8px; border-radius: 999px;
    background: #22324f; color: #cbd5e1; font-size: 0.72rem; white-space: nowrap;
}
.chip b { color: #ffffff; }
.chip.green { background: #064e3b; color: #a7f3d0; }
.chip.green b { color: #d1fae5; }
.chip.red { background: #7f1d1d; color: #fecaca; }
.chip.red b { color: #fee2e2; }
.chip.amber { background: #78350f; color: #fde68a; }
.chip.amber b { color: #fef3c7; }

.wrap { display: grid; grid-template-columns: 3.4fr 1.2fr; gap: 8px; align-items: start; }
.tables { display: grid; grid-template-columns: repeat(__COLS__, 1fr); gap: 6px; }

[data-testid="stMarkdownContainer"] table.tbl {
    width: 100%; border-collapse: collapse; margin: 0 !important;
    font-size: __FS__px; background: #ffffff; border: 1px solid #dde5f0;
    border-radius: 8px; overflow: hidden;
}
[data-testid="stMarkdownContainer"] table.tbl th {
    background: #f4f7fb; color: #64748b; font-weight: 600; font-size: 10px;
    text-align: right; padding: 2px 5px !important; border: none !important;
}
[data-testid="stMarkdownContainer"] table.tbl td {
    text-align: right; padding: 1px 5px !important; line-height: 1.3;
    border: none !important; border-top: 1px solid #f1f5f9 !important;
    font-variant-numeric: tabular-nums; color: #1e293b;
}
[data-testid="stMarkdownContainer"] table.tbl th:first-child,
[data-testid="stMarkdownContainer"] table.tbl td:first-child { text-align: left; font-weight: 600; }
td.up { color: #059669 !important; }
td.dn { color: #dc2626 !important; }
td.pct.up { background: #ecfdf5; font-weight: 600; }
td.pct.dn { background: #fef2f2; font-weight: 600; }
td.dim { color: #94a3b8 !important; }

.side { display: flex; flex-direction: column; gap: 6px; }
@media (max-width: 760px) { .wrap { grid-template-columns: 1fr; } .tables { grid-template-columns: 1fr; } }
.card { background: #ffffff; border: 1px solid #dde5f0; border-radius: 8px; padding: 6px 8px; }
.card h4 { margin: 0 0 3px 0; font-size: 0.72rem; color: #475569; font-weight: 700; letter-spacing: 0.02em; }
.t5 { display: flex; align-items: center; font-size: 0.72rem; padding: 1px 0; color: #1e293b; }
.t5 .dot { width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
.t5 .nm { font-weight: 600; width: 82px; }
.t5 .v { margin-left: auto; font-variant-numeric: tabular-nums; }
.breadth { display: flex; height: 9px; border-radius: 5px; overflow: hidden; background: #e2e8f0; }
.breadth .g { background: #10b981; }
.breadth .r { background: #ef4444; }
.breadth .u { background: #94a3b8; }
.legend2 { display: flex; justify-content: space-between; font-size: 0.68rem; color: #64748b; margin-top: 2px; }
</style>
""".replace("__FS__", str(ROW_FONT_PX)).replace("__COLS__", str(TABLE_COLUMNS))
st.markdown(CSS, unsafe_allow_html=True)

# --- Setup Logging ---
logging.basicConfig(level=logging.ERROR)

# --- Initialize Session State ---
_defaults = {
    'current_data': {},
    'data_received_count': 0,
    'websocket_started': False,
    'client': None,
    'instrument_details': {},
    'scrip_codes': [],
    'req_list': [],
    'websocket_status': "Not Started",
    'last_message_time': None,
    'raw_messages': [],
    'top5_impact_history': [],
    'snapshot_loaded': False,
    'data_source': "Loading...",
    'last_rest_poll': 0.0,
    'last_cache_save': 0.0,
    'last_ws_restart': 0.0,
    'nse_derivatives_data': None,
    'nse_derivatives_last_poll': 0.0,
    'nse_derivatives_error': None,
}
for _key, _val in _defaults.items():
    if _key not in st.session_state:
        st.session_state[_key] = _val
if 'websocket_events' not in st.session_state:
    st.session_state.websocket_events = queue.Queue()

# --- Define paths ---
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / 'config.ini'
for _candidate in (Path('/etc/secrets/config.ini'), CONFIG_PATH):  # Render secret file first
    _probe = configparser.ConfigParser()
    if _candidate.exists() and _probe.read(_candidate) and _probe.has_section('5paise_login'):
        CONFIG_PATH = _candidate
        break
CSV_PATH = PROJECT_ROOT / 'nifty50_trading_data.csv'
SNAPSHOT_PATH = PROJECT_ROOT / 'nifty50_last_snapshot.json'  # local backup of last data
WEIGHT_ESTIMATE_AS_OF = "2026-08-04"
NIFTY50_WEIGHT_ESTIMATES = {
    "RELIANCE": 8.91, "BHARTIARTL": 6.22, "HDFCBANK": 5.80, "ICICIBANK": 5.28,
    "SBIN": 4.86, "TCS": 4.51, "BAJFINANCE": 3.65, "LT": 2.81, "HINDUNILVR": 2.49,
    "INFY": 2.41, "SUNPHARMA": 2.39, "MARUTI": 2.26, "TITAN": 2.23, "M&M": 2.16,
    "ADANIENT": 2.08, "KOTAKBANK": 1.99, "AXISBANK": 1.99, "ADANIPORTS": 1.98,
    "HCLTECH": 1.87, "ITC": 1.82, "ULTRACEMCO": 1.79, "BAJAJFINSV": 1.69,
    "NTPC": 1.69, "BAJAJ-AUTO": 1.62, "JSWSTEEL": 1.60, "ONGC": 1.55,
    "ETERNAL": 1.53, "BEL": 1.46, "ASIANPAINT": 1.34, "POWERGRID": 1.34,
    "COALINDIA": 1.30, "SHRIRAMFIN": 1.29, "TATASTEEL": 1.21, "HINDALCO": 1.16,
    "EICHERMOT": 1.11, "GRASIM": 1.08, "SBILIFE": 0.95, "WIPRO": 0.94,
    "JIOFIN": 0.89, "TRENT": 0.83, "TECHM": 0.82, "APOLLOHOSP": 0.65,
    "CIPLA": 0.60, "HDFCLIFE": 0.59, "TATACONSUM": 0.55, "DRREDDY": 0.49,
    # Absent from the August 2026 snapshot; older approximate project values.
    "HEROMOTOCO": 0.75, "INDUSINDBK": 0.77, "NESTLEIND": 1.64, "TATAMOTORS": 1.61,
}

NOTES_TEXT = (
    f"Sorted by estimated index weight (highest first). Main weight snapshot: "
    f"{WEIGHT_ESTIMATE_AS_OF} (third-party source); HEROMOTOCO, INDUSINDBK, NESTLEIND "
    "and TATAMOTORS use older project estimates. Weights drift over time and the local "
    "constituent list may not match current NIFTY 50 membership. Imp = estimated index "
    "impact in percentage points (weight x daily % change). This is a directional market "
    "summary, not a buy/sell recommendation."
)

# --- Load Config ---
@st.cache_resource
def load_config():
    config = configparser.ConfigParser()

    if not os.path.exists(CONFIG_PATH):
        st.error(f"❌ config.ini file not found at: {CONFIG_PATH}")
        st.stop()

    try:
        config.read(CONFIG_PATH)

        if not config.has_section('5paise_login'):
            st.error(f"❌ Missing [5paise_login] section in {CONFIG_PATH}. Sections found: {config.sections() or 'none (file empty?)'}")
            st.stop()

        section = "5paise_login"
        required_keys = ["APP_NAME", "APP_SOURCE", "USER_ID", "PASSWORD",
                         "USER_KEY", "ENCRYPTION_KEY", "access_token", "CLIENT_CODE"]
        missing_keys = [key for key in required_keys if not config.has_option(section, key)]
        if missing_keys:
            st.error(f"❌ Missing required keys: {', '.join(missing_keys)}")
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
        st.error(f"❌ Config error: {e}")
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
        st.error(f"❌ Authentication error: {e}")
        st.stop()

# --- Load NIFTY 50 Data ---
@st.cache_data
def load_nifty50_data():
    if not os.path.exists(CSV_PATH):
        st.error(f"❌ CSV file not found: {CSV_PATH}")
        st.stop()

    try:
        df = pd.read_csv(CSV_PATH)
        required_columns = ['exchange_token', 'tradingsymbol', 'name', 'exchange']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            st.error(f"❌ Missing columns: {', '.join(missing_columns)}")
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
            req_list.append({"Exch": "N", "ExchType": "C", "ScripCode": scrip_code})

        return instrument_details, scrip_codes, req_list

    except Exception as e:
        st.error(f"❌ Error loading CSV: {e}")
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


def ensure_websocket():
    if not st.session_state.websocket_started:
        thread = threading.Thread(
            target=start_websocket,
            args=(
                st.session_state.client,
                st.session_state.req_list,
                st.session_state.websocket_events,
            ),
            daemon=True,
        )
        thread.start()
        st.session_state.websocket_started = True
        st.session_state.websocket_status = "Connecting..."


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


# --- Last-close snapshot helpers ---
def fetch_snapshot_rest(client, scrip_codes):
    """Last known quote for every stock over REST (works when the market is closed)."""
    result = {}
    try:
        for i in range(0, len(scrip_codes), 50):
            chunk = scrip_codes[i:i + 50]
            req = [{"Exch": "N", "ExchType": "C", "ScripCode": c} for c in chunk]
            resp = client.fetch_market_feed_scrip(req)
            rows = resp.get("Data") if isinstance(resp, dict) else None
            for tick in rows or []:
                try:
                    token = int(tick.get("Token"))
                except (TypeError, ValueError):
                    continue
                result[token] = tick
    except Exception as error:
        logging.error("Snapshot fetch failed: %s", error)
    return result


def save_cache(data):
    try:
        payload = {
            "saved_at": datetime.now().isoformat(),
            "data": {str(k): v for k, v in data.items()},
        }
        with open(SNAPSHOT_PATH, "w") as f:
            json.dump(payload, f, default=str)
    except Exception as error:
        logging.error("Cache save failed: %s", error)


def load_cache():
    try:
        if os.path.exists(SNAPSHOT_PATH):
            with open(SNAPSHOT_PATH) as f:
                payload = json.load(f)
            data = {int(k): v for k, v in payload.get("data", {}).items()}
            return data, payload.get("saved_at")
    except Exception as error:
        logging.error("Cache load failed: %s", error)
    return {}, None


def is_market_open():
    now = datetime.now()
    if now.weekday() >= 5:
        return False, "Closed (weekend)"
    current_time = now.time()
    market_open = datetime.strptime("09:15", "%H:%M").time()
    market_close = datetime.strptime("15:30", "%H:%M").time()
    if market_open <= current_time <= market_close:
        return True, "Open"
    elif current_time < market_open:
        return False, "Pre-open"
    return False, "Closed"


def refresh_data(is_open):
    """Show last-close data immediately, then switch to live ticks."""
    if not st.session_state.snapshot_loaded:
        snap = fetch_snapshot_rest(st.session_state.client, st.session_state.scrip_codes)
        source = "Last close"
        if not snap:
            snap, saved_at = load_cache()
            source = f"Last close (saved {saved_at[:16]})" if (snap and saved_at) else "Last close (saved)"
        for token, tick in snap.items():
            st.session_state.current_data.setdefault(token, tick)
        st.session_state.data_source = source if snap else "No data"
        st.session_state.snapshot_loaded = bool(snap)
        st.session_state.last_rest_poll = time.time()

    now_ts = time.time()
    last_msg = st.session_state.last_message_time
    ws_live = last_msg is not None and (datetime.now() - last_msg).total_seconds() < 20
    if ws_live:
        st.session_state.data_source = "Live"
        if now_ts - st.session_state.last_cache_save > 30:
            save_cache(st.session_state.current_data)
            st.session_state.last_cache_save = now_ts
    elif is_open:
        if now_ts - st.session_state.last_rest_poll > 15:
            snap = fetch_snapshot_rest(st.session_state.client, st.session_state.scrip_codes)
            if snap:
                st.session_state.current_data.update(snap)
                st.session_state.data_source = "Live (REST)"
                save_cache(st.session_state.current_data)
            st.session_state.last_rest_poll = now_ts
        ws_status = st.session_state.websocket_status
        if (ws_status.startswith(("WebSocket Closed", "WebSocket Error", "Connection Error"))
                and now_ts - st.session_state.last_ws_restart > 30):
            st.session_state.websocket_started = False
            st.session_state.last_ws_restart = now_ts


def build_rows():
    rows = []
    for scrip_code in st.session_state.scrip_codes:
        d = st.session_state.current_data.get(scrip_code, {})
        if not d:
            continue
        ltp = d.get("LastRate", 0) or 0
        prev_close = d.get("PClose", 0) or 0
        pct = ((ltp - prev_close) / prev_close * 100) if prev_close else 0.0
        details = st.session_state.instrument_details.get(scrip_code, {})
        symbol = details.get('symbol', f'SCRIP_{scrip_code}')[:12]
        weight = NIFTY50_WEIGHT_ESTIMATES.get(symbol)
        impact = weight * pct / 100 if weight is not None else None
        rows.append({"sym": symbol, "wt": weight, "ltp": ltp, "pct": pct, "imp": impact})
    rows.sort(key=lambda r: (r["wt"] is None, -(r["wt"] or 0), r["sym"]))
    return rows


# ---------------- HTML renderers ----------------
def chip(label, value, tone=""):
    return f'<span class="chip {tone}">{escape(str(label))} <b>{escape(str(value))}</b></span>'


def tone_class(value):
    return "up" if value > 0 else "dn" if value < 0 else ""


def render_tables_html(rows):
    per = -(-len(rows) // TABLE_COLUMNS)  # ceiling division
    out = ['<div class="tables">']
    for c in range(TABLE_COLUMNS):
        chunk = rows[c * per:(c + 1) * per]
        if not chunk:
            continue
        out.append('<table class="tbl"><thead><tr><th>Stock</th><th>Wt%</th><th>LTP</th>'
                   '<th>Chg%</th><th>Imp</th></tr></thead><tbody>')
        for r in chunk:
            cls = tone_class(r["pct"])
            wt = f'{r["wt"]:.2f}' if r["wt"] is not None else "-"
            imp = f'{r["imp"]:+.3f}' if r["imp"] is not None else "-"
            out.append(
                f'<tr><td>{escape(r["sym"])}</td>'
                f'<td class="dim">{wt}</td>'
                f'<td class="{cls}">{r["ltp"]:,.2f}</td>'
                f'<td class="pct {cls}">{r["pct"]:+.2f}%</td>'
                f'<td class="{cls}">{imp}</td></tr>'
            )
        out.append('</tbody></table>')
    out.append('</div>')
    return "".join(out)


PALETTE = ("#0f766e", "#2563eb", "#ea580c", "#9333ea", "#0891b2")


def render_chart_svg(chart_df, symbols):
    width, height = 420, 165
    left, right, top, bottom = 38, 412, 8, 134
    values = [float(v) for s in symbols for v in chart_df[s].dropna()]
    scale = max(max((abs(v) for v in values), default=0.0) * 1.15, 0.02)

    def xp(i, n):
        return left if n <= 1 else left + i * (right - left) / (n - 1)

    def yp(v):
        return top + (scale - v) * (bottom - top) / (2 * scale)

    n = len(chart_df)
    p = [f'<svg viewBox="0 0 {width} {height}" style="display:block;width:100%;height:auto;'
         f'font-family:Arial,sans-serif">']
    for tick in (-scale, 0, scale):
        y = yp(tick)
        stroke = "#94a3b8" if tick == 0 else "#edf1f6"
        p.append(f'<line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" stroke="{stroke}"/>')
        p.append(f'<text x="{left - 4}" y="{y + 3:.1f}" text-anchor="end" font-size="9" '
                 f'fill="#64748b">{tick:+.3f}</text>')
    for si, sym in enumerate(symbols):
        series = chart_df[sym].tolist()
        pts = [f'{xp(i, n):.1f},{yp(float(v)):.1f}' for i, v in enumerate(series) if pd.notna(v)]
        if pts:
            color = PALETTE[si % len(PALETTE)]
            p.append(f'<polyline fill="none" stroke="{color}" stroke-width="2" '
                     f'stroke-linejoin="round" stroke-linecap="round" points="{" ".join(pts)}"/>')
            last = next(((i, float(v)) for i, v in reversed(list(enumerate(series))) if pd.notna(v)), None)
            if last:
                p.append(f'<circle cx="{xp(last[0], n):.1f}" cy="{yp(last[1]):.1f}" r="3" '
                         f'fill="#fff" stroke="{color}" stroke-width="2"/>')
        lx = 6 + si * 82
        p.append(f'<rect x="{lx}" y="153" width="8" height="3" rx="1" fill="{PALETTE[si % len(PALETTE)]}"/>'
                 f'<text x="{lx + 11}" y="157" font-size="9" font-weight="600" fill="#334155">{escape(sym)}</text>')
    if n:
        p.append(f'<text x="{left}" y="146" font-size="8" fill="#94a3b8">{chart_df.index[0].strftime("%H:%M:%S")}</text>'
                 f'<text x="{right}" y="146" text-anchor="end" font-size="8" fill="#94a3b8">'
                 f'{chart_df.index[-1].strftime("%H:%M:%S")}</text>')
    p.append('</svg>')
    return "".join(p)


def update_history(rows):
    top5 = [r for r in rows if r["wt"] is not None][:5]
    now = datetime.now()
    sample = {"Time": now, **{r["sym"]: r["imp"] for r in top5 if r["imp"] is not None}}
    hist = st.session_state.top5_impact_history
    hist.append(sample)
    cutoff = now - timedelta(minutes=5)
    st.session_state.top5_impact_history = [s for s in hist if s["Time"] >= cutoff][-300:]
    chart_df = pd.DataFrame(st.session_state.top5_impact_history).set_index("Time")
    symbols = [r["sym"] for r in top5 if r["imp"] is not None]
    return top5, chart_df, symbols


def render_derivatives_volume():
    now = time.monotonic()
    if now - st.session_state.nse_derivatives_last_poll >= DERIVATIVES_REFRESH_SECONDS:
        st.session_state.nse_derivatives_last_poll = now
        try:
            st.session_state.nse_derivatives_data = fetch_market_data()
            st.session_state.nse_derivatives_error = None
            try:
                record_sample(*st.session_state.nse_derivatives_data)  # saves one reading per 10 min
            except OSError as error:
                st.session_state.nse_derivatives_error = f"Could not save history: {error}"
        except RuntimeError as error:
            st.session_state.nse_derivatives_error = str(error)

    data = st.session_state.nse_derivatives_data
    if data is None:
        if st.session_state.nse_derivatives_error:
            st.warning(
                f"Could not refresh NSE volume data: "
                f"{st.session_state.nse_derivatives_error}"
            )
        return

    totals, row_counts, timestamp, market_status = data
    call_volume = totals["Call"]
    put_volume = totals["Put"]
    difference = abs(call_volume - put_volume)
    if call_volume > put_volume:
        leading_side = "CE"
    elif put_volume > call_volume:
        leading_side = "PE"
    else:
        leading_side = "Equal"

    max_volume = max(call_volume, put_volume, 1)
    chart_rows = []
    for label, volume, color in (
        ("CE", call_volume, "#16a36a"),
        ("PE", put_volume, "#e34b4b"),
    ):
        bar_width = volume / max_volume * 100
        chart_rows.append(
            '<div style="display:grid;grid-template-columns:30px minmax(80px,1fr) '
            '115px;align-items:center;gap:8px;margin:5px 0;font-size:11px">'
            f'<b>{label}</b>'
            '<div style="height:12px;background:#e2e8f0;border-radius:6px;'
            'overflow:hidden">'
            f'<div style="width:{bar_width:.2f}%;height:100%;'
            f'background:{color};border-radius:6px"></div></div>'
            f'<span style="text-align:right;font-variant-numeric:tabular-nums">'
            f'{format_indian(volume)}</span></div>'
        )

    status_text = ""
    if isinstance(market_status, dict):
        status_text = market_status.get("marketStatusMessage", "")
    result_text = (
        f"{leading_side} leads by {format_indian(difference)} contracts"
        if difference
        else "CE and PE volumes are equal"
    )
    if st.session_state.nse_derivatives_error:
        st.warning(
            f"Could not refresh NSE volume data: "
            f"{st.session_state.nse_derivatives_error}"
        )
    chart = (
        '<div class="card"><h4>NSE EQUITY DERIVATIVES · TOP 20 CONTRACTS</h4>'
        + "".join(chart_rows)
        + f'<div style="font-size:11px;color:#475569;margin-top:7px">'
        f'{result_text} · {row_counts["Call"]} CE / {row_counts["Put"]} PE rows'
        f'</div><div style="font-size:10px;color:#64748b;margin-top:3px">'
        f'As of {escape(str(timestamp or "unknown"))} IST · '
        f'{escape(str(status_text))} · refreshes every '
        f'{DERIVATIVES_REFRESH_SECONDS} seconds</div></div>'
    )
    st.markdown(chart, unsafe_allow_html=True)


def live_view(part="all"):
    is_open, market_status = is_market_open()
    ensure_websocket()
    process_websocket_events()
    refresh_data(is_open)
    rows = build_rows()

    if not rows:
        st.info("No data yet: last-close snapshot could not be loaded. Retrying...")
        st.session_state.snapshot_loaded = False
        if part != "left":
            render_derivatives_volume()
        return

    gainers = sum(1 for r in rows if r["pct"] > 0)
    losers = sum(1 for r in rows if r["pct"] < 0)
    unch = len(rows) - gainers - losers
    top5, chart_df, symbols = update_history(rows)
    net = sum(r["imp"] or 0 for r in top5)

    live = st.session_state.data_source.startswith("Live")
    bias_tone = "green" if net > 0 else "red" if net < 0 else ""
    bar = (
        '<div class="topbar"><span class="title">📊 NIFTY 50</span>'
        + chip("Market", market_status, "green" if is_open else "amber")
        + chip("Data", st.session_state.data_source, "green" if live else "amber")
        + chip("Time", datetime.now().strftime('%H:%M:%S'))
        + chip("Stocks", f"{len(rows)}/{len(st.session_state.scrip_codes)}")
        + chip("▲", gainers, "green") + chip("▼", losers, "red") + chip("●", unch)
        + chip("Top-5 impact", f"{net:+.3f} pp", bias_tone)
        + f'<span class="chip" title="{escape(NOTES_TEXT, quote=True)}">ℹ Notes</span>'
        + '</div>'
    )

    # right-hand side panel
    t5_rows = []
    for i, r in enumerate(top5):
        cls = tone_class(r["pct"])
        color = {"up": "#059669", "dn": "#dc2626"}.get(cls, "#64748b")
        imp = f'{r["imp"]:+.3f}' if r["imp"] is not None else "-"
        t5_rows.append(
            f'<div class="t5"><span class="dot" style="background:{PALETTE[i % len(PALETTE)]}"></span>'
            f'<span class="nm">{escape(r["sym"])}</span>'
            f'<span class="v" style="color:{color}">{r["pct"]:+.2f}%&nbsp;&nbsp;{imp}</span></div>'
        )
    total = max(len(rows), 1)
    breadth = (
        f'<div class="breadth"><div class="g" style="width:{gainers / total * 100:.1f}%"></div>'
        f'<div class="u" style="width:{unch / total * 100:.1f}%"></div>'
        f'<div class="r" style="width:{losers / total * 100:.1f}%"></div></div>'
        f'<div class="legend2"><span>▲ {gainers}</span><span>● {unch}</span><span>▼ {losers}</span></div>'
    )
    chart = render_chart_svg(chart_df, symbols) if symbols else ""
    side = (
        '<div class="side">'
        f'<div class="card"><h4>TOP 5 BY WEIGHT - IMPACT (5 MIN, pp)</h4>{chart}</div>'
        f'<div class="card"><h4>TOP 5 NOW (Chg%  Imp)</h4>{"".join(t5_rows)}</div>'
        f'<div class="card"><h4>MARKET BREADTH</h4>{breadth}</div>'
        '</div>'
    )

    if part == "left":
        # NIFTY 50 block only: bar, the two stock tables on the left and the three summary cards
        # stacked on the right. The NSE card and the synthetic future table follow (see main()).
        st.markdown(bar + '<div class="wrap">' + render_tables_html(rows) + side + '</div>',
                    unsafe_allow_html=True)
        return
    html = bar + '<div class="wrap">' + render_tables_html(rows) + side + '</div>'
    st.markdown(html, unsafe_allow_html=True)
    st.divider()
    render_derivatives_volume()


def live_footer():
    """Full-width NSE equity derivatives card under the NIFTY 50 / synthetic future row."""
    st.divider()
    render_derivatives_volume()


def main():
    # One-time setup (runs once per browser session)
    if st.session_state.client is None:
        with st.spinner("Authenticating and loading stock list..."):
            st.session_state.client = authenticate()
            (
                st.session_state.instrument_details,
                st.session_state.scrip_codes,
                st.session_state.req_list,
            ) = load_nifty50_data()

    live_tab, signal_tab = st.tabs(["📊 Live", "🕘 History details"])

    with signal_tab:
        # Synthetic future & strike monitor (expiry / fixed-strike controls, live card, history)
        render_synthetic_tab(st.session_state.client)
        st.divider()
        render_signal_history_tab()
        st.divider()
        # NSE top-20 history (it has its own expander, so it is not wrapped in one)
        if hasattr(st, "fragment"):
            st.fragment(run_every=60)(render_history)()
        else:
            render_history()

    with live_tab:
        if hasattr(st, "fragment"):
            # NIFTY 50 (2 tables + cards), then the NSE card; the synthetic future table goes last.
            st.fragment(run_every=REFRESH_SECONDS)(live_view)("left")
            live_area = st.container()
            with live_area:
                st.fragment(run_every=REFRESH_SECONDS)(live_footer)()
        else:
            live_area = st.container()
        signal_area = st.container()   # synthetic card, BUY strip and second-by-second table

        with signal_area:
            render_synthetic_summary()  # synthetic card + BUY strip, then the second-by-second table
            render_second_by_second()

        if hasattr(st, "fragment"):
            render_panel_tab(st.session_state.client)  # Synthetic future table, after "Second by second"
        else:
            # Older Streamlit: redraw inside one placeholder
            with live_area:
                placeholder = st.empty()
                while True:
                    with placeholder.container():
                        live_view()
                    time.sleep(REFRESH_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        st.error(f"❌ Error: {e}")
        st.error("Please refresh the page")