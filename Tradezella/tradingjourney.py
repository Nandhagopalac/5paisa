"""Streamlit app and local storage for the A+ trading journal."""

import calendar
import hashlib
import json
import os
import uuid
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
from pathlib import Path

from PIL import Image
import streamlit as st

APP_DIRECTORY = Path(__file__).resolve().parent
DATA_DIR = APP_DIRECTORY / "data"
JOURNALS_DIR = DATA_DIR / "journals"
SCREENSHOTS_DIR = DATA_DIR / "screenshots"
SETTINGS_PATH = DATA_DIR / "settings.json"
MAX_SCREENSHOT_BYTES = 10 * 1024 * 1024
DEFAULT_RULES = [
    "1:1:1 rule (write your own definition)",
    "Trade only my planned setups",
    "Record my trade rationale",
    "Respect my personal risk limits",
    "Stop when my written plan says to stop",
]
ALLOWED_IMAGE_FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}


COMPACT_CSS = """
<style>
.block-container {padding-top: 3.2rem; padding-bottom: 1rem; max-width: 1400px;}
h1 {font-size: 1.6rem !important; padding: 0 0 .2rem 0 !important;}
h2, h3 {font-size: 1.15rem !important; padding: .2rem 0 .2rem 0 !important;}
div[data-testid="stVerticalBlock"] {gap: .45rem;}
hr {margin: .6rem 0 !important;}
div[data-testid="stHorizontalBlock"] {gap: .5rem;}
/* trade rows */
div[class*="st-key-trow-"] p, div[class*="st-key-thead"] p {margin: 0; font-size: .86rem; line-height: 1.2;}
div[class*="st-key-trow-"] {border-bottom: 1px solid #eceef2; padding: .15rem 0;}
div[class*="st-key-trow-"] [data-testid="stHorizontalBlock"] {align-items: center;}
div[class*="st-key-trow-"] button, div[class*="st-key-trow-"] [data-testid="stPopover"] button {
    min-height: 1.9rem; padding: .1rem .5rem; font-size: .8rem; white-space: nowrap;}
div[class*="st-key-thead"] {margin-top: .5rem;}
div[class*="st-key-thead"] p {color: #6b7280; font-weight: 600; font-size: .78rem; text-transform: uppercase;}
</style>
"""


def _date_text(value):
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(str(value)).isoformat()


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary_path.open("w", encoding="utf-8") as file:
            json.dump(value, file, ensure_ascii=False, indent=2)
            file.write("\n")
        os.replace(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _journal_path(trade_date, data_dir=DATA_DIR):
    return Path(data_dir) / "journals" / f"{_date_text(trade_date)}.json"


def _empty_journal(trade_date):
    return {
        "trade_date": _date_text(trade_date),
        "plan": "",
        "market_notes": "",
        "review": "",
        "mood": "",
        "pnl": None,
        "rules_checked": [],
        "trades": [],
        "screenshots": [],
    }


def initialize_storage(data_dir=DATA_DIR):
    data_dir = Path(data_dir)
    (data_dir / "journals").mkdir(parents=True, exist_ok=True)
    (data_dir / "screenshots").mkdir(parents=True, exist_ok=True)
    settings_path = data_dir / "settings.json"
    if not settings_path.exists():
        _write_json(settings_path, {"rules": DEFAULT_RULES})


def get_rules(data_dir=DATA_DIR):
    initialize_storage(data_dir)
    settings = json.loads((Path(data_dir) / "settings.json").read_text(encoding="utf-8"))
    rules = settings.get("rules")
    if not isinstance(rules, list) or not all(isinstance(rule, str) for rule in rules):
        raise ValueError("The local settings file contains invalid daily rules.")
    return rules


def save_rules(rules, data_dir=DATA_DIR):
    cleaned_rules = [rule.strip() for rule in rules if rule.strip()]
    if not cleaned_rules:
        raise ValueError("Add at least one daily rule.")
    initialize_storage(data_dir)
    _write_json(Path(data_dir) / "settings.json", {"rules": cleaned_rules})


def get_journal(trade_date, data_dir=DATA_DIR):
    path = _journal_path(trade_date, data_dir)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_journal(
    trade_date,
    plan="",
    market_notes="",
    review="",
    mood="",
    pnl=None,
    rules_checked=(),
    data_dir=DATA_DIR,
):
    initialize_storage(data_dir)
    journal = get_journal(trade_date, data_dir) or _empty_journal(trade_date)
    journal.update(
        plan=plan,
        market_notes=market_notes,
        review=review,
        mood=mood,
        pnl=pnl,
        rules_checked=list(rules_checked),
        updated_at=datetime.now().isoformat(timespec="seconds"),
    )
    _write_json(_journal_path(trade_date, data_dir), journal)


def save_trade(
    trade_date,
    instrument,
    option_type,
    lots,
    buy_price,
    sell_price,
    notes="",
    data_dir=DATA_DIR,
):
    trade = {
        "id": uuid.uuid4().hex,
        **_trade_details(instrument, option_type, lots, buy_price, sell_price, notes),
    }
    _append_trade(trade_date, trade, data_dir)
    return trade["id"]


def update_trade(
    trade_date,
    trade_id,
    instrument,
    option_type,
    lots,
    buy_price,
    sell_price,
    notes="",
    data_dir=DATA_DIR,
):
    journal = get_journal(trade_date, data_dir)
    if journal is None:
        raise ValueError("The selected journal entry no longer exists.")
    for index, trade in enumerate(journal.get("trades", [])):
        if trade.get("id") == trade_id:
            journal["trades"][index] = {
                **trade,
                "id": trade_id,
                **_trade_details(instrument, option_type, lots, buy_price, sell_price, notes),
            }
            journal["updated_at"] = datetime.now().isoformat(timespec="seconds")
            _write_json(_journal_path(trade_date, data_dir), journal)
            return
    raise ValueError("The selected trade could not be found.")


def _trade_details(instrument, option_type, lots, buy_price, sell_price, notes):
    instrument = instrument.strip()
    if not instrument:
        raise ValueError("Enter an instrument.")
    if option_type not in {"CE", "PE"}:
        raise ValueError("Option type must be CE or PE.")
    if lots is None or int(lots) != lots or lots < 1:
        raise ValueError("Lots must be a positive whole number.")
    if buy_price is None or sell_price is None:
        raise ValueError("Enter both buy and sell prices to calculate P&L.")
    if buy_price < 0 or sell_price < 0:
        raise ValueError("Buy and sell prices cannot be negative.")

    lots = int(lots)
    lot_size = default_lot_size(instrument)
    quantity = lots * lot_size
    pnl = calculate_trade_pnl(quantity, buy_price, sell_price)

    return {
        "instrument": instrument,
        "option_type": option_type,
        "lots": lots,
        "lot_size": lot_size,
        "quantity": quantity,
        "buy_price": float(buy_price),
        "sell_price": float(sell_price),
        "pnl": pnl,
        "notes": notes.strip(),
    }


def default_lot_size(instrument):
    normalized = "".join(character for character in instrument.upper() if character.isalnum())
    if "BANKNIFTY" in normalized:
        return 30
    if "NIFTY" in normalized:
        return 65
    return 1


def _append_trade(trade_date, trade, data_dir):
    initialize_storage(data_dir)
    journal = get_journal(trade_date, data_dir) or _empty_journal(trade_date)
    journal.setdefault("trades", []).append(trade)
    journal["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write_json(_journal_path(trade_date, data_dir), journal)


def calculate_trade_pnl(quantity, buy_price, sell_price):
    if quantity is None or buy_price is None or sell_price is None:
        return None
    amount = (Decimal(str(sell_price)) - Decimal(str(buy_price))) * quantity
    return float(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def get_trades(trade_date, data_dir=DATA_DIR):
    journal = get_journal(trade_date, data_dir)
    return journal.get("trades", []) if journal else []


def _store_image(trade_date, content, data_dir):
    """Validate an image upload and write it to disk. Returns (path, relative_path)."""
    if not content:
        raise ValueError("The selected screenshot is empty.")
    if len(content) > MAX_SCREENSHOT_BYTES:
        raise ValueError("Each screenshot must be 10 MB or smaller.")

    try:
        image = Image.open(BytesIO(content))
        image_format = image.format
        image.verify()
    except Exception as error:
        raise ValueError("The selected file is not a valid image.") from error
    if image_format not in ALLOWED_IMAGE_FORMATS:
        raise ValueError("Use a PNG, JPEG, or WEBP screenshot.")

    initialize_storage(data_dir)
    relative_path = Path("screenshots") / _date_text(trade_date) / (
        f"{uuid.uuid4().hex}{ALLOWED_IMAGE_FORMATS[image_format]}"
    )
    saved_path = Path(data_dir) / relative_path
    saved_path.parent.mkdir(parents=True, exist_ok=True)
    saved_path.write_bytes(content)
    return saved_path, relative_path


def save_screenshot(trade_date, original_name, content, data_dir=DATA_DIR):
    saved_path, relative_path = _store_image(trade_date, content, data_dir)
    try:
        journal = get_journal(trade_date, data_dir) or _empty_journal(trade_date)
        journal.setdefault("screenshots", []).append(
            {
                "id": uuid.uuid4().hex,
                "relative_path": relative_path.as_posix(),
                "original_name": Path(original_name).name,
                "uploaded_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
        journal["updated_at"] = datetime.now().isoformat(timespec="seconds")
        _write_json(_journal_path(trade_date, data_dir), journal)
    except Exception:
        saved_path.unlink(missing_ok=True)
        raise


def _find_trade(journal, trade_id):
    for trade in (journal or {}).get("trades", []):
        if trade.get("id") == trade_id:
            return trade
    raise ValueError("The selected trade could not be found.")


def save_trade_journal(
    trade_date,
    trade_id,
    mood_before="",
    mood_after="",
    thinking="",
    improve="",
    rules_followed=(),
    data_dir=DATA_DIR,
):
    """Save the journal written after one trade (feelings, thoughts, rules followed)."""
    journal = get_journal(trade_date, data_dir)
    trade = _find_trade(journal, trade_id)
    trade["journal"] = {
        "mood_before": mood_before,
        "mood_after": mood_after,
        "thinking": thinking.strip(),
        "improve": improve.strip(),
        "rules_followed": list(rules_followed),
    }
    journal["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write_json(_journal_path(trade_date, data_dir), journal)


def save_trade_screenshot(trade_date, trade_id, original_name, content, data_dir=DATA_DIR):
    journal = get_journal(trade_date, data_dir)
    _find_trade(journal, trade_id)
    saved_path, relative_path = _store_image(trade_date, content, data_dir)
    try:
        journal = get_journal(trade_date, data_dir)
        trade = _find_trade(journal, trade_id)
        trade.setdefault("screenshots", []).append(
            {
                "id": uuid.uuid4().hex,
                "relative_path": relative_path.as_posix(),
                "original_name": Path(original_name).name,
                "uploaded_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
        journal["updated_at"] = datetime.now().isoformat(timespec="seconds")
        _write_json(_journal_path(trade_date, data_dir), journal)
    except Exception:
        saved_path.unlink(missing_ok=True)
        raise


def get_trade_screenshots(trade, data_dir=DATA_DIR):
    return [
        {**item, "path": Path(data_dir) / item["relative_path"]}
        for item in trade.get("screenshots", [])
    ]


def get_rules_summary(year, month, data_dir=DATA_DIR):
    """Per day: trades taken, trades with every rule followed, trades journalled."""
    rules = get_rules(data_dir)
    month_start = date(year, month, 1)
    month_end = date(year, month, calendar.monthrange(year, month)[1])
    rows = []
    for path in sorted((Path(data_dir) / "journals").glob("*.json")):
        trade_date = date.fromisoformat(path.stem)
        if not month_start <= trade_date <= month_end:
            continue
        trades = json.loads(path.read_text(encoding="utf-8")).get("trades", [])
        if not trades:
            continue
        followed_all = sum(
            1 for trade in trades
            if trade.get("journal") and all(
                rule in trade["journal"].get("rules_followed", []) for rule in rules
            )
        )
        rows.append(
            {
                "Date": trade_date.isoformat(),
                "Trades": len(trades),
                "Journalled": sum(1 for trade in trades if trade.get("journal")),
                "Followed all rules": followed_all,
                "Broke a rule": sum(1 for trade in trades if trade.get("journal")) - followed_all,
                "P&L": sum(trade.get("pnl") or 0 for trade in trades),
            }
        )
    return rows


def get_screenshots(trade_date, data_dir=DATA_DIR):
    journal = get_journal(trade_date, data_dir)
    if not journal:
        return []
    return [
        {**item, "path": Path(data_dir) / item["relative_path"]}
        for item in journal.get("screenshots", [])
    ]


def get_month_activity(year, month, data_dir=DATA_DIR):
    month_start = date(year, month, 1)
    month_end = date(year, month, calendar.monthrange(year, month)[1])
    initialize_storage(data_dir)
    activity = {}
    for path in (Path(data_dir) / "journals").glob("*.json"):
        trade_date = date.fromisoformat(path.stem)
        if not month_start <= trade_date <= month_end:
            continue
        journal = json.loads(path.read_text(encoding="utf-8"))
        trades = journal.get("trades", [])
        pnl = journal.get("pnl")
        if pnl is None and all(trade.get("pnl") is not None for trade in trades):
            pnl = sum(trade["pnl"] for trade in trades) if trades else 0.0
        activity[trade_date.isoformat()] = {
            "pnl": pnl,
            "trade_count": len(trades),
        }
    return activity


def select_calendar_day(trade_date):
    st.session_state["selected_trade_date"] = date.fromisoformat(trade_date)
    st.session_state["editing_trade"] = None


def shift_calendar_month(offset):
    month = st.session_state["calendar_month"]
    month_index = month.year * 12 + month.month - 1 + offset
    year, month_number = divmod(month_index, 12)
    new_month = date(year, month_number + 1, 1)
    st.session_state["calendar_month"] = new_month
    st.session_state["selected_trade_date"] = new_month
    st.session_state["editing_trade"] = None


def _trade_input_key(name, trade_date, trade_id=None):
    form_id = trade_id or "new"
    return f"trade_{form_id}_{name}_{trade_date}"


def _trade_lot_values(trade):
    instrument = trade.get("instrument", trade.get("symbol", ""))
    lot_size = trade.get("lot_size") or default_lot_size(instrument)
    lots = trade.get("lots")
    if lots is None and trade.get("quantity") is not None:
        lots = trade["quantity"] / lot_size
    if lots is not None and float(lots).is_integer():
        lots = int(lots)
    return lots, lot_size


def submit_trade_entry(trade_date, trade_id=None):
    day = date.fromisoformat(trade_date)
    instrument = st.session_state.get(
        _trade_input_key("instrument", trade_date, trade_id), ""
    ).strip()
    lots = st.session_state.get(_trade_input_key("lots", trade_date, trade_id))
    buy_price = st.session_state.get(
        _trade_input_key("buy_price", trade_date, trade_id)
    )
    sell_price = st.session_state.get(
        _trade_input_key("sell_price", trade_date, trade_id)
    )
    if not instrument:
        st.session_state["trade_feedback"] = {
            "date": trade_date,
            "error": "Enter an instrument before saving the trade.",
        }
        return
    if lots is None:
        st.session_state["trade_feedback"] = {
            "date": trade_date,
            "error": "Enter the number of lots.",
        }
        return
    if buy_price is None or sell_price is None:
        st.session_state["trade_feedback"] = {
            "date": trade_date,
            "error": "Enter both buy and sell prices to calculate P&L.",
        }
        return

    option_type = st.session_state[
        _trade_input_key("option_type", trade_date, trade_id)
    ]
    notes = st.session_state.get(
        _trade_input_key("notes", trade_date, trade_id), ""
    )
    try:
        if trade_id:
            update_trade(
                day,
                trade_id,
                instrument,
                option_type,
                lots,
                buy_price,
                sell_price,
                notes,
            )
        else:
            save_trade(
                day,
                instrument,
                option_type,
                lots,
                buy_price,
                sell_price,
                notes,
            )
    except ValueError as error:
        st.session_state["trade_feedback"] = {
            "date": trade_date,
            "error": str(error),
        }
        return

    st.session_state["trade_feedback"] = {
        "date": trade_date,
        "success": "Trade updated." if trade_id else "Trade added.",
    }
    st.session_state["editing_trade"] = None
    for name, value in (
        ("instrument", ""),
        ("lots", 1),
        ("buy_price", None),
        ("sell_price", None),
        ("notes", ""),
    ):
        st.session_state[_trade_input_key(name, trade_date, trade_id)] = value


def show_trade_entries(selected_date):
    st.divider()
    trade_date = selected_date.isoformat()
    trades = get_trades(selected_date)
    st.subheader(f"Trades · {selected_date:%d %b %Y} · {len(trades)}")
    feedback = st.session_state.get("trade_feedback")
    if feedback and feedback["date"] == selected_date.isoformat():
        st.session_state.pop("trade_feedback")
        if "error" in feedback:
            st.error(feedback["error"])
        else:
            st.success(feedback["success"])

    editing = st.session_state.get("editing_trade")
    editing_trade = None
    if editing and editing["date"] == trade_date:
        editing_trade = next(
            (trade for trade in trades if trade.get("id") == editing["id"]),
            None,
        )
        if editing_trade is None:
            st.session_state["editing_trade"] = None

    if trades:
        widths = [1.6, .7, .6, .8, .9, .8, .8, 1.2, 3.2, .8, 1.3]
        headers = ["Instrument", "CE/PE", "Lots", "Lot size", "Qty",
                   "Buy", "Sell", "P&L", "Notes", "", ""]
        with st.container(key="thead"):
            for column, header in zip(st.columns(widths), headers):
                column.markdown(header)
        for trade in trades:
            lots, lot_size = _trade_lot_values(trade)
            pnl = trade.get("pnl")
            pnl_color = "#15803d" if (pnl or 0) > 0 else ("#dc2626" if (pnl or 0) < 0 else "inherit")
            values = [
                f"**{trade.get('instrument', trade.get('symbol', ''))}**",
                trade.get("option_type", ""),
                lots,
                lot_size,
                trade.get("quantity"),
                trade.get("buy_price", trade.get("entry_price")),
                trade.get("sell_price", trade.get("exit_price")),
                "—" if pnl is None else (
                    f"<span style='color:{pnl_color};font-weight:700'>{pnl:,.0f}</span>"),
                trade.get("notes", ""),
            ]
            is_this_row = bool(editing_trade and editing_trade.get("id") == trade["id"])
            with st.container(key=f"trow-{trade_date}-{trade['id']}"):
                cells = st.columns(widths)
                for cell, value in zip(cells, values):
                    text = "" if value is None else (f"{value:g}" if isinstance(value, float) else str(value))
                    cell.markdown(text, unsafe_allow_html=True)
                shot_count = len(trade.get("screenshots", []))
                with cells[-1].popover(
                    f"📷 {shot_count}" if shot_count else "📷 Add",
                    use_container_width=True,
                ):
                    row_uploads = st.file_uploader(
                        "Upload a screenshot for this trade",
                        type=["png", "jpg", "jpeg", "webp"],
                        accept_multiple_files=True,
                        key=f"row_up_{trade_date}_{trade['id']}",
                    )
                    if st.button("Save", key=f"row_sv_{trade_date}_{trade['id']}",
                                 disabled=not row_uploads, type="primary"):
                        for upload in row_uploads:
                            try:
                                save_trade_screenshot(selected_date, trade["id"],
                                                      upload.name, upload.getvalue())
                            except ValueError as error:
                                st.error(f"{upload.name}: {error}")
                        st.rerun()
                    for shot in get_trade_screenshots(trade):
                        if shot["path"].is_file():
                            st.image(str(shot["path"]), caption=shot["original_name"],
                                     use_container_width=True)
                if cells[-2].button(
                    "Editing" if is_this_row else "Edit",
                    key=f"edit_row_{trade_date}_{trade['id']}",
                    disabled=is_this_row,
                    use_container_width=True,
                ):
                    st.session_state["editing_trade"] = {
                        "date": trade_date,
                        "id": trade["id"],
                    }
                    st.rerun()
    else:
        st.caption("No trades recorded for this date yet.")

    is_editing = editing_trade is not None
    trade_id = editing_trade["id"] if is_editing else None
    form_id = trade_id or "new"
    form_key = lambda name: _trade_input_key(name, trade_date, trade_id)
    editing_instrument = (
        editing_trade.get("instrument", editing_trade.get("symbol", ""))
        if is_editing
        else ""
    )
    lots_default = _trade_lot_values(editing_trade)[0] if is_editing else 1
    if lots_default is not None:
        lots_default = max(1, round(lots_default))
    editing_option = editing_trade.get("option_type", "CE") if is_editing else "CE"
    editing_buy = (
        editing_trade.get("buy_price", editing_trade.get("entry_price"))
        if is_editing else None
    )
    editing_sell = (
        editing_trade.get("sell_price", editing_trade.get("exit_price"))
        if is_editing else None
    )
    editing_notes = editing_trade.get("notes", "") if is_editing else ""

    with st.expander(
        "Edit trade" if is_editing else "Add a trade",
        expanded=is_editing or not trades,
    ):
        with st.form(f"trade_form_{trade_date}_{form_id}", clear_on_submit=not is_editing):
            instrument_column, option_column, lots_column = st.columns([2, 1, 1])
            instrument_column.text_input(
                "Instrument",
                placeholder="e.g. NIFTY 24500",
                value=editing_instrument,
                key=form_key("instrument"),
            )
            option_column.selectbox(
                "Option type",
                ["CE", "PE"],
                index=1 if editing_option == "PE" else 0,
                key=form_key("option_type"),
            )
            lots_column.number_input(
                "Lots",
                min_value=1,
                value=lots_default,
                step=1,
                help=(
                    "NIFTY: 65 units per lot. BANKNIFTY: 30 units per lot. "
                    "Other instruments default to 1."
                ),
                key=form_key("lots"),
            )
            buy_column, sell_column = st.columns(2)
            buy_column.number_input(
                "Buy price",
                min_value=0.0,
                value=editing_buy,
                step=0.05,
                key=form_key("buy_price"),
            )
            sell_column.number_input(
                "Sell price",
                min_value=0.0,
                value=editing_sell,
                step=0.05,
                key=form_key("sell_price"),
            )
            st.caption(
                "Gross P&L = (sell price − buy price) × lots × lot size. "
                "Lot size defaults to 65 for NIFTY and 30 for BANKNIFTY."
            )
            st.text_area(
                "Trade notes",
                value=editing_notes,
                key=form_key("notes"),
            )
            st.form_submit_button(
                "Save changes" if is_editing else "Add trade",
                on_click=submit_trade_entry,
                args=(trade_date, trade_id),
            )
        if is_editing and st.button("Cancel edit", key=f"cancel_edit_{trade_date}"):
            st.session_state["editing_trade"] = None
            st.rerun()


MOODS = ["Not recorded", "Calm", "Confident", "Focused", "Excited", "Anxious",
         "Fearful", "Greedy", "FOMO", "Frustrated", "Revenge urge", "Tired"]


def show_trade_journals(selected_date):
    """One journal per trade, written right after the trade."""
    trades = get_trades(selected_date)
    if not trades:
        return
    rules = get_rules()
    trade_date = selected_date.isoformat()
    st.subheader("Journal for each trade")
    st.caption("Write this right after each trade: how you felt, what you thought, "
               "which rules you followed, and a screenshot.")
    for number, trade in enumerate(trades, start=1):
        saved = trade.get("journal") or {}
        followed = set(saved.get("rules_followed", []))
        label = (f"Trade {number} · {trade.get('instrument', '')} "
                 f"{trade.get('option_type', '')} · P&L {trade.get('pnl', 0):,.2f}")
        if saved:
            label += f" · {len(followed & set(rules))}/{len(rules)} rules followed"
        else:
            label += " · not journalled yet"
        with st.expander(label, expanded=not saved):
            key = f"{trade_date}_{trade['id']}"
            with st.form(f"trade_journal_{key}"):
                left, right = st.columns(2)
                mood_before = left.selectbox(
                    "Feeling at entry", MOODS,
                    index=MOODS.index(saved["mood_before"]) if saved.get("mood_before") in MOODS else 0,
                    key=f"mb_{key}",
                )
                mood_after = right.selectbox(
                    "Feeling after the trade", MOODS,
                    index=MOODS.index(saved["mood_after"]) if saved.get("mood_after") in MOODS else 0,
                    key=f"ma_{key}",
                )
                thinking = st.text_area("What I was thinking", value=saved.get("thinking", ""),
                                        key=f"th_{key}")
                improve = st.text_area("What I would do differently",
                                       value=saved.get("improve", ""), key=f"im_{key}")
                st.markdown("**Rules I followed on this trade**")
                ticks = {}
                for index, rule in enumerate(rules):
                    suffix = hashlib.sha1(rule.encode("utf-8")).hexdigest()[:8]
                    ticks[rule] = st.checkbox(rule, value=rule in followed,
                                              key=f"rl_{key}_{index}_{suffix}")
                if st.form_submit_button("Save trade journal", type="primary"):
                    save_trade_journal(
                        selected_date, trade["id"],
                        mood_before="" if mood_before == "Not recorded" else mood_before,
                        mood_after="" if mood_after == "Not recorded" else mood_after,
                        thinking=thinking, improve=improve,
                        rules_followed=[r for r, on in ticks.items() if on],
                    )
                    st.rerun()

            uploads = st.file_uploader(
                "Paste or upload a screenshot for this trade",
                type=["png", "jpg", "jpeg", "webp"],
                accept_multiple_files=True,
                key=f"up_{key}",
            )
            if st.button("Save screenshot", key=f"sv_{key}", disabled=not uploads):
                for upload in uploads:
                    try:
                        save_trade_screenshot(selected_date, trade["id"],
                                              upload.name, upload.getvalue())
                    except ValueError as error:
                        st.error(f"{upload.name}: {error}")
                st.rerun()
            for shot in get_trade_screenshots(trade):
                if shot["path"].is_file():
                    st.image(str(shot["path"]), caption=shot["original_name"],
                             use_container_width=True)
                else:
                    st.warning(f"Screenshot file is missing: {shot['original_name']}")


def show_daily_journal(selected_date):
    journal = get_journal(selected_date) or {}
    rules = get_rules()
    checked_rules = set(journal.get("rules_checked", []))

    with st.form(f"journal_form_{selected_date.isoformat()}"):
        st.subheader("Before and after the session")
        planned_setup = st.text_area(
            "Plan for the day",
            value=journal.get("plan", ""),
            placeholder="What are you watching? What would keep you out of a trade?",
            key=f"plan_{selected_date}",
        )
        market_notes = st.text_area(
            "Market notes and daily work",
            value=journal.get("market_notes", ""),
            placeholder="Capture observations, decisions, and anything you want to remember.",
            key=f"market_notes_{selected_date}",
        )
        review = st.text_area(
            "End-of-day review",
            value=journal.get("review", ""),
            placeholder="What went well? What will you change next time?",
            key=f"review_{selected_date}",
        )
        left, right = st.columns(2)
        with left:
            mood = st.selectbox(
                "How did you feel?",
                ["Not recorded", "Calm", "Focused", "Hesitant", "Frustrated", "Other"],
                index=(
                    ["Not recorded", "Calm", "Focused", "Hesitant", "Frustrated", "Other"].index(
                        journal.get("mood", "Not recorded")
                    )
                    if journal.get("mood", "Not recorded")
                    in ["Not recorded", "Calm", "Focused", "Hesitant", "Frustrated", "Other"]
                    else 0
                ),
                key=f"mood_{selected_date}",
            )
        with right:
            daily_pnl = st.number_input(
                "Daily P&L (optional)",
                value=journal.get("pnl"),
                step=1.0,
                format="%.2f",
                help="Use your own preferred currency. Leave blank if you do not want to record it.",
                key=f"daily_pnl_{selected_date}",
            )

        st.markdown("#### Daily rules")
        rule_values = {}
        for index, rule in enumerate(rules):
            key_suffix = hashlib.sha1(rule.encode("utf-8")).hexdigest()[:10]
            rule_values[rule] = st.checkbox(
                rule,
                value=rule in checked_rules,
                key=f"rule_{selected_date}_{index}_{key_suffix}",
            )

        save_clicked = st.form_submit_button("Save daily journal", type="primary")
        if save_clicked:
            save_journal(
                selected_date,
                plan=planned_setup,
                market_notes=market_notes,
                review=review,
                mood="" if mood == "Not recorded" else mood,
                pnl=daily_pnl,
                rules_checked=[
                    rule for rule, is_checked in rule_values.items() if is_checked
                ],
            )
            st.session_state["journal_saved_date"] = selected_date.isoformat()
            st.rerun()

    if st.session_state.pop("journal_saved_date", None) == selected_date.isoformat():
        st.success("Daily notes saved.")

    st.divider()
    st.subheader("Screenshots")
    uploads = st.file_uploader(
        "Attach chart or trade screenshots",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        key=f"screenshots_{selected_date.isoformat()}",
    )
    if st.button("Save screenshots", disabled=not uploads):
        for upload in uploads:
            try:
                save_screenshot(selected_date, upload.name, upload.getvalue())
            except ValueError as error:
                st.error(f"{upload.name}: {error}")
            else:
                st.success(f"Saved {upload.name}")
        st.rerun()

    screenshots = get_screenshots(selected_date)
    if screenshots:
        columns = st.columns(min(3, len(screenshots)))
        for index, screenshot in enumerate(screenshots):
            with columns[index % len(columns)]:
                if screenshot["path"].is_file():
                    st.image(
                        str(screenshot["path"]),
                        caption=screenshot["original_name"],
                        use_container_width=True,
                    )
                else:
                    st.warning(
                        f"Screenshot file is missing: {screenshot['original_name']}"
                    )


def show_trade_calendar():
    month = st.session_state["calendar_month"]
    previous, month_label, following = st.columns([1, 6, 1])
    previous.button(
        "‹",
        help="Previous month",
        on_click=shift_calendar_month,
        args=(-1,),
        use_container_width=True,
    )
    month_label.markdown(f"<div style='text-align:center;font-size:1.15rem;font-weight:700;padding-top:.3rem'>Trade calendar · {month:%B %Y}</div>", unsafe_allow_html=True)
    following.button(
        "›",
        help="Next month",
        on_click=shift_calendar_month,
        args=(1,),
        use_container_width=True,
    )
    selected_date = st.session_state["selected_trade_date"]
    activity = get_month_activity(month.year, month.month)

    st.markdown(
        """
        <style>
        div[class*="st-key-calendar-"] button {
            height: 54px;
            min-height: 54px;
            width: 100%;
            white-space: pre-line;
            line-height: 1.25;
            font-size: .78rem;
            padding: .15rem .25rem;
            margin: 0;
        }
        div[class*="st-key-calendar-profit"] button {
            background: #4caf50 !important;
            border-color: #4caf50 !important;
            color: #fff !important;
        }
        div[class*="st-key-calendar-loss"] button {
            background: #e3444b !important;
            border-color: #e3444b !important;
            color: #fff !important;
        }
        div[class*="st-key-calendar-profit"] button:hover,
        div[class*="st-key-calendar-loss"] button:hover {
            filter: brightness(0.92);
        }
        div[class*="st-key-calendar-flat"] button {
            background: #fff !important;
            border-color: #d5d9df !important;
            color: #202124 !important;
        }
        div[class*="st-key-calendar-"][class*="-selected-"] button {
            outline: 3px solid #7656c9;
            outline-offset: 1px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    for column, weekday in zip(
        st.columns(7), ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    ):
        column.markdown(f"**{weekday}**")

    month_calendar = calendar.Calendar(firstweekday=calendar.MONDAY)
    for week in month_calendar.monthdayscalendar(month.year, month.month):
        for column, day_number in zip(st.columns(7), week):
            if day_number == 0:
                continue
            day = date(month.year, month.month, day_number)
            trade_date = day.isoformat()
            day_activity = activity.get(trade_date)
            trade_count = day_activity["trade_count"] if day_activity else 0
            pnl = day_activity["pnl"] if day_activity else 0
            tone = "profit" if pnl is not None and pnl > 0 else (
                "loss" if pnl is not None and pnl < 0 else "flat"
            )
            pnl_text = f"{pnl:,.0f}" if pnl is not None else "—"
            plural = "" if trade_count == 1 else "s"
            selected = "-selected" if day == selected_date else ""
            with column.container(key=f"calendar-{tone}{selected}-{trade_date}"):
                st.button(
                    (f"{day_number}\n{pnl_text}\n{trade_count} trade{plural}"
                     if trade_count else f"{day_number}\n\n"),
                    key=f"calendar-day-{trade_date}",
                    on_click=select_calendar_day,
                    args=(trade_date,),
                    use_container_width=True,
                )

    show_trade_entries(selected_date)
    show_trade_journals(selected_date)


def show_rules():
    st.title("Rules calendar")
    st.caption("Your rules, your day-level plan and review, and how well you followed "
               "the rules each day.")

    st.subheader("How I followed my rules this month")
    month = st.session_state["calendar_month"]
    summary = get_rules_summary(month.year, month.month)
    st.caption(f"{month:%B %Y}. A trade counts as 'followed all rules' only when every "
               "rule is ticked in its trade journal.")
    if summary:
        st.dataframe(summary, hide_index=True, use_container_width=True)
    else:
        st.caption("No trades this month yet.")

    st.divider()
    st.subheader("Day plan and review")
    selected = st.date_input("Day", value=st.session_state["selected_trade_date"],
                             key="rules_day_picker")
    st.session_state["selected_trade_date"] = selected
    show_daily_journal(selected)

    st.divider()
    st.subheader("My rules")
    st.info(
        "These rules appear as checkboxes in every trade journal. "
        "The 1:1:1 rule is included as a reminder; add your own definition here."
    )
    rules = get_rules()
    with st.form("rules_form"):
        text = st.text_area(
            "One rule per line",
            value="\n".join(rules),
            height=240,
            help="Remove a line to remove that rule from future checklists.",
        )
        save_clicked = st.form_submit_button("Save rules", type="primary")
        if save_clicked:
            try:
                save_rules(text.splitlines())
            except ValueError as error:
                st.error(str(error))
            else:
                st.success("Daily rules saved.")
                st.rerun()


def main():
    st.set_page_config(
        page_title="A+ Trading Journal",
        page_icon="📔",
        layout="wide",
    )
    initialize_storage()
    st.markdown(COMPACT_CSS, unsafe_allow_html=True)
    st.session_state.setdefault("calendar_month", date.today().replace(day=1))
    st.session_state.setdefault("selected_trade_date", date.today())

    with st.sidebar:
        st.title("A+ Journal")
        st.caption("Your trading process, day by day.")
        page = st.radio(
            "Pages",
            ["Trade calendar", "Rules calendar"],
            label_visibility="collapsed",
            key="app_page",
        )
        st.divider()
        st.caption(f"Local journal files\n`{DATA_DIR.relative_to(APP_DIRECTORY)}`")

    if page == "Trade calendar":
        show_trade_calendar()
    else:
        show_rules()


if __name__ == "__main__":
    main()
