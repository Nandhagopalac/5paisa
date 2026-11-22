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
RULE_GROUPS = (
    ("market", "Market conditions"),
    ("entry", "Entry rules"),
    ("exit", "Exit rules"),
)
LEGACY_DEFAULT_RULES = [
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
div[class*="st-key-trow-"] {border-bottom: 1px solid #eceef2; border-left: 4px solid transparent; padding: .15rem .4rem;}
div[class*="st-key-trow-"] [data-testid="stHorizontalBlock"] {align-items: center;}
div[class*="st-key-trow-"] button, div[class*="st-key-trow-"] [data-testid="stPopover"] button {
    min-height: 1.9rem; padding: .1rem .5rem; font-size: .8rem; white-space: nowrap;}
div[class*="st-key-trow-sel-"] {background: #ede9fe; border-left-color: #7656c9; border-radius: 6px;}
div[class*="st-key-trow-sel-"] button[kind="secondary"] {border-color: #7656c9; color: #5b3fb3; font-weight: 700;}
div[class*="st-key-journal-panel"] {border: 2px solid #7656c9; border-radius: 10px; padding: .6rem .9rem; background: #faf8ff;}
div[class*="st-key-edit-trade-panel"] {border: 2px solid #ea580c; border-radius: 10px; background: #fff7ed;}
div[class*="st-key-edit-trade-panel"] summary p {font-weight: 800; color: #c2410c; letter-spacing: .04em;}
div[class*="st-key-add-trade-panel"] summary p {font-weight: 700; color: #15803d;}
div[class*="st-key-delete-confirm"] {border: 2px solid #dc2626; background: #fef2f2; border-radius: 8px; padding: .5rem .8rem;}
div[class*="st-key-rrow-"] {border-bottom: 1px solid #eceef2; padding: .1rem .2rem;}
div[class*="st-key-rrow-"] [data-testid="stHorizontalBlock"] {align-items: stretch;}
div[class*="st-key-rrow-"] p {margin: 0; font-size: .86rem;}
div[class*="st-key-rrow-"] input {min-height: 2rem; padding: .2rem .6rem; font-weight: 600;}
div[class*="st-key-rrow-"] button {min-height: 1.9rem; padding: .1rem .4rem;}
div[class*="st-key-thead-rules"] {padding: 0 .2rem .35rem .2rem; min-height: 1.5rem;}
div[class*="st-key-rrow-"] [data-testid="stColumn"] {justify-content: center;}
div[class*="st-key-rules-panel"] {border: 2px solid #7656c9; border-radius: 10px; padding: .6rem .9rem; background: #faf8ff;}
div[class*="st-key-thead"] {margin-top: .5rem; padding: 0 .4rem 0 calc(4px + .4rem);}
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


def _new_id():
    return uuid.uuid4().hex[:8]


def _new_rule(text):
    return {"id": _new_id(), "text": text.strip()}


def _default_strategy():
    return {
        "id": _new_id(),
        "name": "Trendline break reversal",
        "archived": False,
        "rules": {
            "market": [_new_rule("Trending market")],
            "entry": [
                _new_rule("A+ setup: trendline has 3+ touchpoints"),
                _new_rule("Price has broken the trendline"),
                _new_rule("Price pulled back and retested"),
                _new_rule("Candle has closed"),
                _new_rule("Top 5 Nifty stocks agree (green / red)"),
            ],
            "exit": [_new_rule("S/R hit or safety line crossed")],
        },
    }


def _load_settings(data_dir):
    path = Path(data_dir) / "settings.json"
    settings = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    strategies = settings.get("strategies")
    if not isinstance(strategies, list) or not strategies:
        strategy = _default_strategy()
        old_rules = settings.get("rules")
        if isinstance(old_rules, list):
            strategy["rules"]["entry"] += [
                _new_rule(rule) for rule in old_rules
                if isinstance(rule, str) and rule.strip() and rule not in LEGACY_DEFAULT_RULES
            ]
        settings = {"strategies": [strategy]}
        _write_json(path, settings)
    return settings


def initialize_storage(data_dir=DATA_DIR):
    data_dir = Path(data_dir)
    (data_dir / "journals").mkdir(parents=True, exist_ok=True)
    (data_dir / "screenshots").mkdir(parents=True, exist_ok=True)
    _load_settings(data_dir)


def get_strategies(data_dir=DATA_DIR, include_archived=False):
    initialize_storage(data_dir)
    strategies = _load_settings(data_dir)["strategies"]
    return [s for s in strategies if include_archived or not s.get("archived")]


def _save_strategies(strategies, data_dir):
    _write_json(Path(data_dir) / "settings.json", {"strategies": strategies})


def _edit_strategy(strategy_id, data_dir, change):
    initialize_storage(data_dir)
    strategies = _load_settings(data_dir)["strategies"]
    strategy = next((s for s in strategies if s["id"] == strategy_id), None)
    if strategy is None:
        raise ValueError("That strategy no longer exists.")
    result = change(strategy, strategies)
    _save_strategies(strategies, data_dir)
    return result


def create_strategy(name, data_dir=DATA_DIR):
    name = name.strip()
    if not name:
        raise ValueError("Give the strategy a name.")
    initialize_storage(data_dir)
    strategies = _load_settings(data_dir)["strategies"]
    if any(s["name"].lower() == name.lower() for s in strategies):
        raise ValueError("A strategy with that name already exists.")
    strategy = {"id": _new_id(), "name": name, "archived": False,
                "rules": {key: [] for key, _ in RULE_GROUPS}}
    strategies.append(strategy)
    _save_strategies(strategies, data_dir)
    return strategy["id"]


def set_strategy_archived(strategy_id, archived, data_dir=DATA_DIR):
    def change(strategy, strategies):
        others = [s for s in strategies if s["id"] != strategy_id and not s.get("archived")]
        if archived and not others:
            raise ValueError("Keep at least one active strategy.")
        strategy["archived"] = bool(archived)
    _edit_strategy(strategy_id, data_dir, change)


def add_rule(strategy_id, group, text, data_dir=DATA_DIR):
    if group not in dict(RULE_GROUPS):
        raise ValueError("Unknown rule group.")
    if not text.strip():
        raise ValueError("Type the rule first.")

    def change(strategy, _):
        rule = _new_rule(text)
        strategy["rules"].setdefault(group, []).append(rule)
        return rule["id"]
    return _edit_strategy(strategy_id, data_dir, change)


def rename_rule(strategy_id, rule_id, text, data_dir=DATA_DIR):
    if not text.strip():
        raise ValueError("A rule cannot be empty. Use the bin to remove it.")

    def change(strategy, _):
        for rules in strategy["rules"].values():
            for rule in rules:
                if rule["id"] == rule_id:
                    rule["text"] = text.strip()
                    return
        raise ValueError("That rule no longer exists.")
    _edit_strategy(strategy_id, data_dir, change)


def delete_rule(strategy_id, rule_id, data_dir=DATA_DIR):
    def change(strategy, _):
        for group, rules in strategy["rules"].items():
            strategy["rules"][group] = [r for r in rules if r["id"] != rule_id]
    _edit_strategy(strategy_id, data_dir, change)


def rule_followed(entry, rule):
    ticked = (entry or {}).get("rules_followed", [])
    return rule["id"] in ticked or rule["text"] in ticked


def trade_strategy_id(trade, strategies):
    """The trade's strategy; older trades without one belong to the first strategy."""
    ids = {s["id"] for s in strategies}
    return trade.get("strategy_id") if trade.get("strategy_id") in ids else strategies[0]["id"]


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
    strategy_id=None,
    data_dir=DATA_DIR,
):
    trade = {
        "id": uuid.uuid4().hex,
        "strategy_id": strategy_id or get_strategies(data_dir)[0]["id"],
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
    strategy_id=None,
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
                **({"strategy_id": strategy_id} if strategy_id else {}),
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


INSTRUMENTS = ["NIFTY", "BANKNIFTY", "FINNIFTY"]


def default_lot_size(instrument):
    normalized = "".join(character for character in instrument.upper() if character.isalnum())
    if "BANKNIFTY" in normalized:
        return 30
    if "FINNIFTY" in normalized:
        return 60
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


def delete_trade(trade_date, trade_id, data_dir=DATA_DIR):
    """Remove a trade together with its journal and its screenshot files."""
    journal = get_journal(trade_date, data_dir)
    trade = _find_trade(journal, trade_id)
    journal["trades"] = [t for t in journal["trades"] if t.get("id") != trade_id]
    journal["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write_json(_journal_path(trade_date, data_dir), journal)
    removed = 0
    for item in trade.get("screenshots", []):
        file_path = Path(data_dir) / item["relative_path"]
        if file_path.is_file():
            file_path.unlink()
            removed += 1
    folder = Path(data_dir) / "screenshots" / _date_text(trade_date)
    if folder.is_dir() and not any(folder.iterdir()):
        folder.rmdir()
    return removed


def get_trade_screenshots(trade, data_dir=DATA_DIR):
    return [
        {**item, "path": Path(data_dir) / item["relative_path"]}
        for item in trade.get("screenshots", [])
    ]


def _iter_trades(data_dir, year=None, month=None):
    initialize_storage(data_dir)
    for path in sorted((Path(data_dir) / "journals").glob("*.json")):
        trade_date = date.fromisoformat(path.stem)
        if year and (trade_date.year, trade_date.month) != (year, month):
            continue
        for trade in json.loads(path.read_text(encoding="utf-8")).get("trades", []):
            yield trade_date, trade


def _performance(pnls):
    pnls = [p for p in pnls if p is not None]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_loss = -sum(losses)
    if gross_loss:
        profit_factor = sum(wins) / gross_loss
    else:
        profit_factor = float("inf") if wins else None
    return {
        "trades": len(pnls),
        "win_rate": len(wins) / len(pnls) * 100 if pnls else None,
        "net_pnl": sum(pnls),
        "profit_factor": profit_factor,
        "avg_win": sum(wins) / len(wins) if wins else None,
        "avg_loss": sum(losses) / len(losses) if losses else None,
    }


def get_strategy_overview(year=None, month=None, data_dir=DATA_DIR, include_archived=False):
    """One performance row per strategy (all time, or one month)."""
    everything = get_strategies(data_dir, include_archived=True)
    pnls = {s["id"]: [] for s in everything}
    journalled = {s["id"]: 0 for s in everything}
    for _, trade in _iter_trades(data_dir, year, month):
        sid = trade_strategy_id(trade, everything)
        pnls[sid].append(trade.get("pnl"))
        journalled[sid] += 1 if trade.get("journal") else 0
    return [
        {"id": s["id"], "name": s["name"], "archived": bool(s.get("archived")),
         "journalled": journalled[s["id"]], **_performance(pnls[s["id"]])}
        for s in everything if include_archived or not s.get("archived")
    ]


def get_rule_stats(strategy_id, year=None, month=None, data_dir=DATA_DIR):
    """For each rule of a strategy: follow rate, net P&L, profit factor, win rate."""
    everything = get_strategies(data_dir, include_archived=True)
    strategy = next(s for s in everything if s["id"] == strategy_id)
    journalled = [
        trade for _, trade in _iter_trades(data_dir, year, month)
        if trade_strategy_id(trade, everything) == strategy_id and trade.get("journal")
    ]
    groups = []
    for key, label in RULE_GROUPS:
        rules = []
        for rule in strategy["rules"].get(key, []):
            followed = [t for t in journalled if rule_followed(t["journal"], rule)]
            performance = _performance([t.get("pnl") for t in followed])
            rules.append({
                "id": rule["id"], "text": rule["text"],
                "journalled": len(journalled), "followed": len(followed),
                "follow_rate": len(followed) / len(journalled) * 100 if journalled else None,
                "net_pnl": performance["net_pnl"] if followed else None,
                "profit_factor": performance["profit_factor"],
                "win_rate": performance["win_rate"],
            })
        groups.append({"key": key, "label": label, "rules": rules})
    return groups


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
    st.session_state["selected_trade"] = None


def current_trade_id(trades, trade_date):
    """The trade chosen in the table; else the first one not yet journalled."""
    chosen = st.session_state.get("selected_trade")
    if chosen and chosen["date"] == trade_date and any(t.get("id") == chosen["id"] for t in trades):
        return chosen["id"]
    if not trades:
        return None
    pending = next((t for t in trades if not t.get("journal")), trades[0])
    return pending["id"]


def choose_trade(trade_date, trade_id):
    st.session_state["selected_trade"] = {"date": trade_date, "id": trade_id}


def shift_calendar_month(offset):
    month = st.session_state["calendar_month"]
    month_index = month.year * 12 + month.month - 1 + offset
    year, month_number = divmod(month_index, 12)
    new_month = date(year, month_number + 1, 1)
    st.session_state["calendar_month"] = new_month
    st.session_state["selected_trade_date"] = new_month
    st.session_state["editing_trade"] = None
    st.session_state["selected_trade"] = None


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
    strategy_id = st.session_state.get(_trade_input_key("strategy", trade_date, trade_id))
    notes = ""
    if trade_id:
        notes = next(
            (t.get("notes", "") for t in get_trades(day) if t.get("id") == trade_id), ""
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
                strategy_id,
            )
        else:
            new_id = save_trade(
                day,
                instrument,
                option_type,
                lots,
                buy_price,
                sell_price,
                notes,
                strategy_id,
            )
            choose_trade(trade_date, new_id)
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
        ("instrument", INSTRUMENTS[0]),
        ("lots", 1),
        ("buy_price", None),
        ("sell_price", None),
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
        widths = [.55, 1.6, .7, .6, .9, .8, .8, .8, 1.2, .8, 1.3, 1.25]
        headers = ["#", "Instrument", "CE/PE", "Lots", "Lot size", "Qty",
                   "Buy", "Sell", "P&L", "", "", ""]
        chosen_id = current_trade_id(trades, trade_date)
        with st.container(key="thead"):
            for column, header in zip(st.columns(widths), headers):
                column.markdown(header)
        for number, trade in enumerate(trades, start=1):
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
            ]
            is_this_row = bool(editing_trade and editing_trade.get("id") == trade["id"])
            is_chosen = trade["id"] == chosen_id
            with st.container(key=f"trow-{'sel-' if is_chosen else ''}{trade_date}-{trade['id']}"):
                cells = st.columns(widths)
                if cells[0].button(
                    f"● {number}" if is_chosen else f"○ {number}",
                    key=f"pick_row_{trade_date}_{trade['id']}",
                    help="Select this trade to see its journal below",
                    use_container_width=True,
                ):
                    choose_trade(trade_date, trade["id"])
                    st.rerun()
                for cell, value in zip(cells[1:], values):
                    text = "" if value is None else (f"{value:g}" if isinstance(value, float) else str(value))
                    cell.markdown(text, unsafe_allow_html=True)
                shot_count = len(trade.get("screenshots", []))
                with cells[-2].popover(
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
                        choose_trade(trade_date, trade["id"])
                        st.rerun()
                    for shot in get_trade_screenshots(trade):
                        if shot["path"].is_file():
                            st.image(str(shot["path"]), caption=shot["original_name"],
                                     use_container_width=True)
                if cells[-3].button(
                    "Editing" if is_this_row else "Edit",
                    key=f"edit_row_{trade_date}_{trade['id']}",
                    disabled=is_this_row,
                    use_container_width=True,
                ):
                    st.session_state["editing_trade"] = {
                        "date": trade_date,
                        "id": trade["id"],
                    }
                    choose_trade(trade_date, trade["id"])
                    st.rerun()
                if cells[-1].button(
                    "🗑 Delete",
                    key=f"delete_row_{trade_date}_{trade['id']}",
                    use_container_width=True,
                ):
                    st.session_state["confirm_delete"] = {"date": trade_date, "id": trade["id"]}
                    choose_trade(trade_date, trade["id"])
                    st.rerun()
        pending = st.session_state.get("confirm_delete")
        if pending and pending["date"] == trade_date:
            target = next((t for t in trades if t.get("id") == pending["id"]), None)
            if target is None:
                st.session_state["confirm_delete"] = None
            else:
                with st.container(key="delete-confirm"):
                    shots = len(target.get("screenshots", []))
                    st.markdown(
                        f"**Delete this trade?** {target.get('instrument', '')} "
                        f"{target.get('option_type', '')} · P&L "
                        f"{(target.get('pnl') or 0):,.0f}. Its journal and "
                        f"{shots} screenshot{'s' if shots != 1 else ''} will be removed "
                        "permanently."
                    )
                    yes, no, _ = st.columns([1, 1, 5])
                    if yes.button("Yes, delete", key="confirm_delete_yes", type="primary"):
                        delete_trade(selected_date, target["id"])
                        st.session_state["confirm_delete"] = None
                        st.session_state["editing_trade"] = None
                        st.session_state["selected_trade"] = None
                        st.session_state["trade_feedback"] = {
                            "date": trade_date, "success": "Trade and its screenshots deleted."}
                        st.rerun()
                    if no.button("Cancel", key="confirm_delete_no"):
                        st.session_state["confirm_delete"] = None
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
    if editing_instrument.upper() in INSTRUMENTS:
        editing_instrument = editing_instrument.upper()
    instrument_options = INSTRUMENTS + (
        [editing_instrument] if editing_instrument and editing_instrument not in INSTRUMENTS else []
    )
    lots_default = _trade_lot_values(editing_trade)[0] if is_editing else 1
    if lots_default is not None:
        lots_default = max(1, round(lots_default))
    editing_option = editing_trade.get("option_type", "CE") if is_editing else "CE"
    all_strategies = get_strategies(include_archived=True)
    strategy_names = {x["id"]: x["name"] for x in all_strategies}
    own_strategy = trade_strategy_id(editing_trade, all_strategies) if is_editing else None
    strategy_options = [x["id"] for x in all_strategies
                        if not x.get("archived") or x["id"] == own_strategy]
    strategy_index = strategy_options.index(own_strategy) if own_strategy in strategy_options else 0
    editing_buy = (
        editing_trade.get("buy_price", editing_trade.get("entry_price"))
        if is_editing else None
    )
    editing_sell = (
        editing_trade.get("sell_price", editing_trade.get("exit_price"))
        if is_editing else None
    )

    panel = st.container(key="edit-trade-panel" if is_editing else "add-trade-panel")
    with panel, st.expander(
        "✏️ EDIT TRADE" if is_editing else "➕ Add a trade",
        expanded=is_editing or not trades,
    ):
        with st.form(f"trade_form_{trade_date}_{form_id}", clear_on_submit=not is_editing):
            instrument_column, option_column, lots_column, strategy_column = st.columns([2, 1, 1, 2])
            strategy_column.selectbox(
                "Strategy",
                strategy_options,
                index=strategy_index,
                format_func=lambda sid: strategy_names[sid],
                key=form_key("strategy"),
            )
            instrument_column.selectbox(
                "Instrument",
                instrument_options,
                index=instrument_options.index(editing_instrument) if editing_instrument else 0,
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
                    "NIFTY: 65 units per lot. BANKNIFTY: 30. FINNIFTY: 60. "
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
                "Lot size: 65 for NIFTY, 30 for BANKNIFTY, 60 for FINNIFTY."
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
    """The journal for the trade selected in the table above."""
    trades = get_trades(selected_date)
    if not trades:
        return
    all_strategies = get_strategies(include_archived=True)
    trade_date = selected_date.isoformat()
    chosen_id = current_trade_id(trades, trade_date)
    number, trade = next((n, t) for n, t in enumerate(trades, start=1) if t["id"] == chosen_id)
    saved = trade.get("journal") or {}
    strategy = next(x for x in all_strategies if x["id"] == trade_strategy_id(trade, all_strategies))
    rule_list = [(label, rule) for key, label in RULE_GROUPS
                 for rule in strategy["rules"].get(key, [])]
    pnl = trade.get("pnl") or 0
    done = sum(1 for _, rule in rule_list if rule_followed(saved, rule))
    status = (f"{done}/{len(rule_list)} rules followed" if saved else "not journalled yet")
    with st.container(key="journal-panel"):
        st.markdown(
            f"**Journal · Trade {number} · {trade.get('instrument', '')} "
            f"{trade.get('option_type', '')} · P&L {pnl:,.0f}** &nbsp;·&nbsp; "
            f"{strategy['name']} &nbsp;·&nbsp; {status}"
        )
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
                                    height=90, key=f"th_{key}")
            improve = st.text_area("What I would do differently",
                                   value=saved.get("improve", ""), height=90, key=f"im_{key}")
            ticks = {}
            if rule_list:
                st.markdown("**Rules I followed on this trade**")
                for key_name, label in RULE_GROUPS:
                    group_rules = strategy["rules"].get(key_name, [])
                    if not group_rules:
                        continue
                    st.caption(label)
                    rule_columns = st.columns(2)
                    for index, rule in enumerate(group_rules):
                        ticks[rule["id"]] = rule_columns[index % 2].checkbox(
                            rule["text"], value=rule_followed(saved, rule),
                            key=f"rl_{key}_{rule['id']}")
            else:
                st.caption("This strategy has no rules yet. Add them on the Strategies page.")
            if st.form_submit_button("Save trade journal", type="primary"):
                save_trade_journal(
                    selected_date, trade["id"],
                    mood_before="" if mood_before == "Not recorded" else mood_before,
                    mood_after="" if mood_after == "Not recorded" else mood_after,
                    thinking=thinking, improve=improve,
                    rules_followed=[rule_id for rule_id, on in ticks.items() if on],
                )
                st.rerun()

        uploads = st.file_uploader(
            "Screenshots for this trade",
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
        shots = get_trade_screenshots(trade)
        if shots:
            shot_columns = st.columns(min(3, len(shots)))
            for index, shot in enumerate(shots):
                with shot_columns[index % len(shot_columns)]:
                    if shot["path"].is_file():
                        st.image(str(shot["path"]), caption=shot["original_name"],
                                 use_container_width=True)
                    else:
                        st.warning(f"Screenshot file is missing: {shot['original_name']}")


def show_daily_journal(selected_date):
    journal = get_journal(selected_date) or {}

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

        save_clicked = st.form_submit_button("Save daily journal", type="primary")
        if save_clicked:
            save_journal(
                selected_date,
                plan=planned_setup,
                market_notes=market_notes,
                review=review,
                mood="" if mood == "Not recorded" else mood,
                pnl=daily_pnl,
                rules_checked=journal.get("rules_checked", []),
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
    with st.expander("📝 Day plan & review"):
        show_daily_journal(selected_date)


def _money(value):
    return "—" if value is None else f"{value:,.0f}"


def _percent(value):
    return "—" if value is None else f"{value:.0f}%"


def _factor(value):
    if value is None:
        return "—"
    return "∞" if value == float("inf") else f"{value:.2f}"


def _coloured(value):
    if value is None:
        return "—"
    colour = "#15803d" if value > 0 else ("#dc2626" if value < 0 else "inherit")
    return f"<span style='color:{colour};font-weight:700'>{value:,.0f}</span>"


def _strategy_action(action, *args):
    try:
        action(*args)
    except ValueError as error:
        st.session_state["strategy_error"] = str(error)


def _rename_rule_from_input(strategy_id, rule_id):
    _strategy_action(rename_rule, strategy_id, rule_id,
                     st.session_state.get(f"rule_text_{rule_id}", ""))


def _add_rule_from_input(strategy_id, group):
    key = f"new_rule_{strategy_id}_{group}"
    _strategy_action(add_rule, strategy_id, group, st.session_state.get(key, ""))
    st.session_state[key] = ""


def _choose_strategy(strategy_id):
    st.session_state["selected_strategy"] = strategy_id


def show_strategies():
    today = date.today()
    title, period_box = st.columns([3, 2])
    title.markdown("### Strategies")
    period = period_box.radio("Period", ["All time", f"This month ({today:%b %Y})"],
                              horizontal=True, label_visibility="collapsed",
                              key="strategy_period")
    year, month = (None, None) if period == "All time" else (today.year, today.month)

    error = st.session_state.pop("strategy_error", None)
    if error:
        st.error(error)

    show_archived = st.session_state.get("show_archived_strategies", False)
    overview = get_strategy_overview(year, month, include_archived=show_archived)
    active = [row for row in overview if not row["archived"]]
    traded = [row for row in active if row["trades"]]

    cards = st.columns(4)
    def card(column, icon, label, row, detail):
        with column, st.container(border=True):
            st.caption(f"{icon} {label}")
            st.markdown(f"**{row['name']}**" if row else "**—**")
            st.caption(detail(row) if row else "No trades yet")
    card(cards[0], "📈", "Best performing", max(traded, key=lambda r: r["net_pnl"], default=None),
         lambda r: f"{r['trades']} trades · {_money(r['net_pnl'])}")
    card(cards[1], "📉", "Least performing", min(traded, key=lambda r: r["net_pnl"], default=None),
         lambda r: f"{r['trades']} trades · {_money(r['net_pnl'])}")
    card(cards[2], "⚡", "Most active", max(traded, key=lambda r: r["trades"], default=None),
         lambda r: f"{r['trades']} trades")
    card(cards[3], "🎯", "Best win rate",
         max(traded, key=lambda r: (r["win_rate"], r["trades"]), default=None),
         lambda r: f"{_percent(r['win_rate'])} · {r['trades']} trades")

    selected_id = st.session_state.get("selected_strategy")
    if selected_id not in {row["id"] for row in overview}:
        selected_id = (active or overview)[0]["id"]
        st.session_state["selected_strategy"] = selected_id

    widths = [.5, 2.4, .8, 1, 1.1, 1, 1, 1, 1]
    with st.container(key="thead-strategies"):
        for column, header in zip(st.columns(widths), ["", "Strategy", "Trades", "Win rate",
                "Net P&L", "Profit factor", "Avg winner", "Avg loser", ""]):
            column.markdown(header)
    for row in overview:
        chosen = row["id"] == selected_id
        with st.container(key=f"trow-{'sel-' if chosen else ''}strategy-{row['id']}"):
            cells = st.columns(widths)
            cells[0].button("●" if chosen else "○", key=f"pick_strategy_{row['id']}",
                            on_click=_choose_strategy, args=(row["id"],),
                            use_container_width=True, help="Show this strategy's rules")
            cells[1].markdown(f"**{row['name']}**" + (" _(archived)_" if row["archived"] else ""))
            cells[2].markdown(str(row["trades"]))
            cells[3].markdown(_percent(row["win_rate"]))
            cells[4].markdown(_coloured(row["net_pnl"] if row["trades"] else None), unsafe_allow_html=True)
            cells[5].markdown(_factor(row["profit_factor"]))
            cells[6].markdown(_money(row["avg_win"]))
            cells[7].markdown(_money(row["avg_loss"]))
            cells[8].button("Restore" if row["archived"] else "Archive",
                            key=f"archive_{row['id']}", use_container_width=True,
                            on_click=_strategy_action,
                            args=(set_strategy_archived, row["id"], not row["archived"]))

    footer = st.columns([3, 1])
    with footer[0], st.expander("➕ Create strategy"):
        with st.form("create_strategy", clear_on_submit=True):
            name = st.text_input("Strategy name", placeholder="e.g. Break & retest")
            if st.form_submit_button("Create", type="primary"):
                try:
                    st.session_state["selected_strategy"] = create_strategy(name)
                    st.rerun()
                except ValueError as problem:
                    st.error(str(problem))
    footer[1].toggle("Show archived", key="show_archived_strategies")

    chosen_row = next(row for row in overview if row["id"] == selected_id)
    st.divider()
    with st.container(key="rules-panel"):
        st.markdown(f"#### {chosen_row['name']} · Entry and Exit Rules")
        st.caption("Type in a box to rename a rule. Follow rate, P&L, profit factor and win rate "
                   "come from the trades you journalled with this strategy.")
        for group in get_rule_stats(selected_id, year, month):
            st.markdown(f"**{group['label']}**")
            rule_widths = [4, 1.1, 1.3, 1.1, 1, .6]
            if group["rules"]:
                with st.container(key=f"thead-rules-{group['key']}"):
                    for column, header in zip(st.columns(rule_widths),
                            ["Rule", "Follow rate", "Net P&L", "Profit factor", "Win rate", ""]):
                        column.markdown(header)
            else:
                st.caption("No rules yet. Add the first one below.")
            for rule in group["rules"]:
                with st.container(key=f"rrow-{rule['id']}"):
                    cells = st.columns(rule_widths)
                    cells[0].text_input("Rule", value=rule["text"], key=f"rule_text_{rule['id']}",
                                        label_visibility="collapsed",
                                        on_change=_rename_rule_from_input,
                                        args=(selected_id, rule["id"]))
                    cells[1].markdown(_percent(rule["follow_rate"]))
                    cells[2].markdown(_coloured(rule["net_pnl"]), unsafe_allow_html=True)
                    cells[3].markdown(_factor(rule["profit_factor"]))
                    cells[4].markdown(_percent(rule["win_rate"]))
                    cells[5].button("🗑", key=f"del_rule_{rule['id']}", help="Remove this rule",
                                    on_click=_strategy_action,
                                    args=(delete_rule, selected_id, rule["id"]))
            add_box, add_button = st.columns([4, 1.2])
            add_box.text_input("New rule", placeholder=f"+ Add a rule to {group['label'].lower()}",
                               key=f"new_rule_{selected_id}_{group['key']}",
                               label_visibility="collapsed")
            add_button.button("Add rule", key=f"add_rule_{selected_id}_{group['key']}",
                              on_click=_add_rule_from_input, args=(selected_id, group["key"]),
                              use_container_width=True)


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
            ["Trade calendar", "Strategies"],
            label_visibility="collapsed",
            key="app_page",
        )
        st.divider()
        st.caption(f"Local journal files\n`{DATA_DIR.relative_to(APP_DIRECTORY)}`")

    if page == "Trade calendar":
        show_trade_calendar()
    else:
        show_strategies()


if __name__ == "__main__":
    main()
