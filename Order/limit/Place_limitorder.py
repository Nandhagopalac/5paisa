"""Place a regular 5paisa limit order through the Xstream REST API.

Run from the project root (dry run by default):
    & .\\.venv_5paisa\\Scripts\\python.exe .\\Order\\limit\\Place_limitorder.py --scripcode 47133 --qty 65 --price 7.5 --side B
    .\\Order\\limit\\limit.ps1 -Quantity 1 -Side B -StopLossPercent 2

Add --confirm to submit. Credentials are read from config.ini next to the
project root, or from the file named by FP_CONFIG. If login is required, open
the 5paisa developer login URL using USER_KEY from config.ini, then paste the
request token here. When stop-loss protection is enabled, the script monitors
the entry order and submits stop-market exits after fills are reported.
"""
import argparse
import base64
import binascii
import csv
import configparser
import json
import os
import re
import sys
import time
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path

import requests

URL = "https://Openapi.5paisa.com/VendorsAPI/Service1.svc/V1/PlaceOrderRequest"
ORDER_STATUS_URL = "https://Openapi.5paisa.com/VendorsAPI/Service1.svc/V3/OrderStatus"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG = Path(os.environ.get("FP_CONFIG", PROJECT_ROOT / "config.ini"))
SCRIP_MASTER = PROJECT_ROOT / "scrip_master.csv"
ORDER_STATUS_POLL_SECONDS = 2


def positive_int(value):
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def positive_price(value):
    try:
        price = Decimal(value)
    except InvalidOperation as error:
        raise argparse.ArgumentTypeError("must be a positive decimal price") from error
    if not price.is_finite() or price <= 0:
        raise argparse.ArgumentTypeError("must be a positive decimal price")
    return price


def positive_percentage(value):
    try:
        percentage = Decimal(value)
    except InvalidOperation as error:
        raise argparse.ArgumentTypeError("must be a positive percentage below 100") from error
    if not percentage.is_finite() or percentage <= 0 or percentage >= 100:
        raise argparse.ArgumentTypeError("must be a positive percentage below 100")
    return percentage


def nonempty_symbol(value):
    symbol = value.strip()
    if not symbol:
        raise argparse.ArgumentTypeError("must be a non-empty symbol")
    return symbol


def token_valid(token):
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        expiry = json.loads(base64.urlsafe_b64decode(payload))["exp"]
        return expiry > time.time() + 60
    except (
        AttributeError,
        binascii.Error,
        IndexError,
        KeyError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
    ):
        return False


def save_token(token):
    text = CONFIG.read_text(encoding="utf-8")
    updated, count = re.subn(
        r"(?m)^access_token\s*=.*$",
        lambda _: f"access_token = {token}",
        text,
    )
    if count == 0:
        updated, count = re.subn(
            r"(?m)^(\[5paise_login\]\s*)$",
            lambda match: match.group(1) + f"\naccess_token = {token}",
            text,
            count=1,
        )
    if count == 0:
        raise ValueError(f"Could not save access token: [5paise_login] section not found in {CONFIG}.")
    CONFIG.write_text(updated, encoding="utf-8")


def get_access_token(settings):
    token = settings.get("access_token", "").strip()
    if token_valid(token):
        print("Using saved access token (still valid).")
        return token

    from py5paisa import FivePaisaClient

    print("Access token missing or expired; OAuth login is needed.")
    credentials = {
        key: settings[key].strip()
        for key in (
            "APP_NAME",
            "APP_SOURCE",
            "USER_ID",
            "PASSWORD",
            "USER_KEY",
            "ENCRYPTION_KEY",
        )
    }
    client = FivePaisaClient(cred=credentials)
    client.get_oauth_session(input("Paste request token: ").strip())
    token = client.get_access_token()
    if not token or not token_valid(token):
        raise RuntimeError("Login did not return a valid access token.")
    save_token(token)
    print(f"New access token saved to {CONFIG}.")
    return token


def quote_ltp(response, scripcode):
    if not isinstance(response, (dict, list)):
        raise RuntimeError("5paisa returned an unexpected market-feed response.")

    quotes = []
    ltp_keys = ("LastRate", "LTP", "LastTradedPrice", "LastTradedRate")
    token_keys = ("ScripCode", "Token", "token", "ExchScripCode", "InstrumentToken")

    def visit(value):
        if isinstance(value, dict):
            rate = next((value[key] for key in ltp_keys if value.get(key) is not None), None)
            if rate is not None:
                token = next((value[key] for key in token_keys if value.get(key) is not None), None)
                quotes.append((token, rate))
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(response)
    exact_matches = [
        rate for token, rate in quotes
        if token is not None and str(token).strip() == str(scripcode)
    ]
    if len(exact_matches) == 1:
        selected_rate = exact_matches[0]
    elif len(exact_matches) > 1:
        raise RuntimeError(
            f"5paisa returned multiple LTP values for scrip code {scripcode}; refusing to choose one."
        )
    elif len(quotes) == 1:
        selected_rate = quotes[0][1]
    else:
        body = response.get("body", response) if isinstance(response, dict) else response
        message = ""
        if isinstance(body, dict):
            message = str(body.get("Message") or body.get("Error") or "")
        details = f"Found {len(quotes)} quote records."
        if message:
            details += f" 5paisa message: {message}."
        raise RuntimeError(
            f"Could not identify one LTP for scrip code {scripcode}. {details}"
        )

    try:
        ltp = Decimal(str(selected_rate))
    except InvalidOperation as error:
        raise RuntimeError("5paisa returned an invalid LTP.") from error
    if not ltp.is_finite() or ltp < 0:
        raise RuntimeError("5paisa returned an invalid LTP.")
    return ltp if ltp > 0 else None


def fetch_ltp(client, scripcode, exchange, exchange_type, symbol, expiry, strike, option_type):
    response = client.fetch_market_feed(
        [
            {
                "Exch": exchange,
                "ExchType": exchange_type,
                "Symbol": symbol,
                "Expiry": expiry,
                "StrikePrice": strike,
                "OptionType": option_type,
            }
        ]
    )
    return quote_ltp(response, scripcode)


def load_settings():
    config = configparser.ConfigParser(interpolation=None)
    if not config.read(CONFIG):
        raise FileNotFoundError(
            f"Cannot find configuration file: {CONFIG}. Set FP_CONFIG to its path if needed."
        )
    if not config.has_section("5paise_login"):
        raise configparser.NoSectionError("5paise_login")
    return config["5paise_login"]


def get_market_feed_client(settings):
    from py5paisa import FivePaisaClient

    credentials = {
        key: settings[key].strip()
        for key in (
            "APP_NAME",
            "APP_SOURCE",
            "USER_ID",
            "PASSWORD",
            "USER_KEY",
            "ENCRYPTION_KEY",
        )
    }
    token = get_access_token(settings)
    client = FivePaisaClient(cred=credentials)
    client.set_access_token(token, settings["CLIENT_CODE"].strip())
    return client


def get_tick_size(scripcode, exchange, exchange_type):
    if not SCRIP_MASTER.is_file():
        raise FileNotFoundError(
            f"Scrip master not found: {SCRIP_MASTER}. Refresh it before using stop-loss protection."
        )

    with SCRIP_MASTER.open(newline="", encoding="utf-8-sig") as file:
        rows = csv.DictReader(file)
        matches = [
            row for row in rows
            if row.get("ScripCode", "").strip() == str(scripcode)
            and row.get("Exch", "").strip().upper() == exchange.upper()
            and row.get("ExchType", "").strip().upper() == exchange_type.upper()
        ]

    if len(matches) != 1:
        raise ValueError(
            f"Expected one scrip-master row for {exchange}/{exchange_type} "
            f"scrip code {scripcode}; found {len(matches)}."
        )
    try:
        tick_size = Decimal(matches[0]["TickSize"])
    except (InvalidOperation, KeyError) as error:
        raise ValueError(f"Missing or invalid TickSize for scrip code {scripcode}.") from error
    if not tick_size.is_finite() or tick_size <= 0:
        raise ValueError(f"Invalid TickSize for scrip code {scripcode}.")
    return tick_size


def stop_trigger_price(entry_price, side, percentage, tick_size):
    if side not in ("B", "S"):
        raise ValueError("Side must be B or S to calculate the stop trigger.")
    if entry_price <= 0 or percentage <= 0 or percentage >= 100:
        raise ValueError("Entry price and stop percentage are outside the valid range.")
    if tick_size <= 0:
        raise ValueError("Tick size must be positive.")
    multiplier = Decimal(1) - percentage / Decimal(100)
    rounding = ROUND_CEILING
    if side == "S":
        multiplier = Decimal(1) + percentage / Decimal(100)
        rounding = ROUND_FLOOR
    raw_trigger = entry_price * multiplier
    trigger = (raw_trigger / tick_size).to_integral_value(rounding=rounding) * tick_size
    if trigger <= 0:
        raise ValueError("The calculated stop-loss trigger must be positive.")
    return trigger


def build_stop_market_body(
    scripcode,
    quantity,
    side,
    exchange,
    exchange_type,
    intraday,
    trigger_price,
    remote_order_id,
):
    return {
        "Exchange": exchange,
        "ExchangeType": exchange_type,
        "ScripCode": str(scripcode),
        "Price": "0",
        "StopLossPrice": format(trigger_price, "f"),
        "OrderType": "Sell" if side == "B" else "Buy",
        "Qty": quantity,
        "DisQty": "0",
        "IsIntraday": intraday,
        "isMTF": False,
        "iOrderValidity": "0",
        "AHPlaced": "N",
        "AtMarket": True,
        "IsStopLossOrder": True,
        "RemoteOrderID": remote_order_id,
        "AlgoID": "0",
    }


def api_result(response, operation):
    response.raise_for_status()
    try:
        result = response.json()
    except requests.exceptions.JSONDecodeError as error:
        raise RuntimeError(f"5paisa returned a non-JSON {operation} response.") from error
    if not isinstance(result, dict):
        raise RuntimeError(f"5paisa returned an unexpected {operation} response.")
    head = result.get("head") or {}
    body = result.get("body")
    if not isinstance(head, dict):
        raise RuntimeError(f"5paisa returned an unexpected {operation} response.")
    return head, body


def submit_order(body, settings, token):
    response = requests.post(
        URL,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"bearer {token}",
        },
        json={"head": {"key": settings["USER_KEY"].strip()}, "body": body},
        timeout=20,
    )
    print("\nHTTP", response.status_code)
    head, order_result = api_result(response, "order")
    print(json.dumps({"head": head, "body": order_result}, indent=2))
    if head.get("status") != "0" or not isinstance(order_result, dict):
        message = head.get("statusDescription") or "invalid response body"
        raise RuntimeError(f"5paisa rejected the order: {message}")
    if order_result.get("Status") != 0:
        message = order_result.get("Message") or head.get("statusDescription") or "unknown error"
        raise RuntimeError(f"5paisa did not accept the order: {message}")
    return order_result


def get_order_status(settings, token, exchange, remote_order_id):
    response = requests.post(
        ORDER_STATUS_URL,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"bearer {token}",
        },
        json={
            "head": {"key": settings["USER_KEY"].strip()},
            "body": {
                "ClientCode": settings["CLIENT_CODE"].strip(),
                "OrdStatusReqList": [
                    {"Exch": exchange, "RemoteOrderID": remote_order_id}
                ],
            },
        },
        timeout=20,
    )
    head, body = api_result(response, "order-status")
    if head.get("status") != "0" or not isinstance(body, dict):
        raise RuntimeError("5paisa returned an unsuccessful order-status response.")
    records = body.get("OrdStatusResLst")
    if not isinstance(records, list):
        raise RuntimeError("5paisa returned no order-status list.")
    if not records and body.get("Status") == 1:
        return None

    matches = [
        record for record in records
        if isinstance(record, dict)
        and str(record.get("RemoteOrderID", "")).strip() == remote_order_id
    ]
    if not matches and len(records) == 1 and isinstance(records[0], dict):
        matches = records
    if len(matches) != 1:
        raise RuntimeError(
            f"Could not identify one status for RemoteOrderID {remote_order_id}."
        )
    return matches[0]


def order_progress(record, requested_quantity):
    status = str(record.get("OrderStatus") or "").strip()
    quantity = record.get("TradedQty")
    if quantity is None:
        total = record.get("OrderQty", record.get("Qty", requested_quantity))
        pending = record.get("PendingQty")
        if pending is None:
            raise RuntimeError("Order status is missing TradedQty and PendingQty.")
        quantity = Decimal(str(total)) - Decimal(str(pending))
    try:
        traded = Decimal(str(quantity))
    except InvalidOperation as error:
        raise RuntimeError("5paisa returned an invalid TradedQty.") from error
    if (
        not traded.is_finite()
        or traded < 0
        or traded != traded.to_integral_value()
        or traded > requested_quantity
    ):
        raise RuntimeError("5paisa returned an invalid traded quantity.")
    if not status:
        raise RuntimeError("5paisa order status is missing OrderStatus.")
    return int(traded), status


def monitor_entry(
    settings,
    token,
    remote_order_id,
    scripcode,
    requested_quantity,
    side,
    exchange,
    exchange_type,
    intraday,
    entry_price,
    stop_percentage,
    tick_size,
):
    protected_quantity = 0
    previous_progress = None
    terminal_statuses = (
        "fully executed",
        "cancelled",
        "canceled",
        "rejected",
        "expired",
    )
    print(
        "\nMonitoring the entry order. Keep this window and the PC awake; "
        "stop orders are submitted after fills are reported by 5paisa."
    )
    while True:
        try:
            if not token_valid(token):
                token = get_access_token(settings)
            record = get_order_status(settings, token, exchange, remote_order_id)
        except (requests.RequestException, RuntimeError) as error:
            raise RuntimeError(
                f"URGENT: monitoring entry RemoteOrderID {remote_order_id} failed. "
                "Any fill not yet reported may be unprotected; check the 5paisa "
                "order book and position book immediately."
            ) from error
        if record is None:
            time.sleep(ORDER_STATUS_POLL_SECONDS)
            continue

        try:
            traded_quantity, status = order_progress(record, requested_quantity)
        except (RuntimeError, TypeError, ValueError) as error:
            raise RuntimeError(
                f"URGENT: 5paisa returned unusable fill status for entry "
                f"RemoteOrderID {remote_order_id}; any unreported fill may be "
                "unprotected. Check the order book and position book immediately."
            ) from error
        progress = (traded_quantity, status)
        if progress != previous_progress:
            print(
                f"Entry status: {status} | filled "
                f"{traded_quantity}/{requested_quantity}"
            )
            previous_progress = progress

        if traded_quantity < protected_quantity:
            raise RuntimeError("5paisa reported a decreasing traded quantity.")
        if traded_quantity > protected_quantity:
            trigger_price = stop_trigger_price(
                entry_price, side, stop_percentage, tick_size
            )
            stop_remote_id = f"sl{int(time.time() * 1000)}{traded_quantity}"
            stop_body = build_stop_market_body(
                scripcode,
                traded_quantity - protected_quantity,
                side,
                exchange,
                exchange_type,
                intraday,
                trigger_price,
                stop_remote_id,
            )
            print(
                "Submitting stop-market exit for "
                f"{traded_quantity - protected_quantity} filled unit(s), "
                f"trigger {format(trigger_price, 'f')}."
            )
            try:
                stop_result = submit_order(stop_body, settings, token)
            except (requests.RequestException, RuntimeError) as error:
                raise RuntimeError(
                    f"URGENT: {traded_quantity - protected_quantity} filled unit(s) "
                    f"have no confirmed stop order. Check the 5paisa order book "
                    f"before taking action; stop RemoteOrderID was {stop_remote_id}."
                ) from error
            protected_quantity = traded_quantity
            print(
                "Stop-market order accepted. "
                f"BrokerOrderID={stop_result.get('BrokerOrderID')} "
                f"RemoteOrderID={stop_remote_id}"
            )

        if any(word in status.lower() for word in terminal_statuses):
            if status.lower() != "fully executed":
                print(
                    f"Entry order ended with status '{status}'. "
                    f"{protected_quantity} filled unit(s) have stop orders submitted."
                )
            else:
                print(
                    f"Entry fully filled. Stop orders submitted for "
                    f"{protected_quantity} unit(s)."
                )
            return
        time.sleep(ORDER_STATUS_POLL_SECONDS)


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Place a regular 5paisa limit order and optionally monitor fills "
            "for percentage-based stop-market protection."
        )
    )
    script = parser.add_mutually_exclusive_group(required=True)
    script.add_argument("--scripcode", type=positive_int, help="numeric scrip code, e.g. 1660 (ITC)")
    script.add_argument("--scripdata", type=nonempty_symbol, help="symbol such as ITC_EQ")
    parser.add_argument("--qty", type=positive_int)
    parser.add_argument("--price", type=positive_price, help="positive limit price")
    parser.add_argument(
        "--stop-loss-percent",
        type=positive_percentage,
        help="submit stop-market exits after entry fills, based on the entry limit price",
    )
    parser.add_argument("--side", choices=("B", "S"), help="B=buy, S=sell")
    parser.add_argument("--exch", default="N", help="N=NSE, B=BSE, M=MCX")
    parser.add_argument("--exchtype", default="C", help="C=cash, D=derivatives, U=currency")
    parser.add_argument("--symbol", help=argparse.SUPPRESS)
    parser.add_argument("--expiry", help=argparse.SUPPRESS)
    parser.add_argument("--strike", help=argparse.SUPPRESS)
    parser.add_argument("--option-type", choices=("CE", "PE"), help=argparse.SUPPRESS)
    parser.add_argument("--ltp-only", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--intraday", action="store_true", help="default is delivery")
    parser.add_argument("--algoid", default="0", help="Algo ID if you are a registered algo user")
    parser.add_argument(
        "--minimal",
        action="store_true",
        help="omit RemoteOrderID and AlgoID from the request body",
    )
    parser.add_argument("--confirm", action="store_true", help="really send the order")
    args = parser.parse_args()

    if args.stop_loss_percent is not None and args.scripcode is None:
        parser.error("--stop-loss-percent requires --scripcode so fills can be tracked.")

    if args.ltp_only:
        quote_fields = (args.symbol, args.expiry, args.strike, args.option_type)
        if args.scripcode is None or any(field is None for field in quote_fields):
            parser.error(
                "--ltp-only requires --scripcode, --symbol, --expiry, --strike, and --option-type"
            )
        client = get_market_feed_client(load_settings())
        ltp = fetch_ltp(
            client,
            args.scripcode,
            args.exch,
            args.exchtype,
            args.symbol,
            args.expiry,
            args.strike,
            args.option_type,
        )
        if ltp is None:
            print("LTP=UNAVAILABLE")
        else:
            print(f"LTP={format(ltp, 'f')}")
        return 0

    if args.qty is None or args.side is None or args.price is None:
        parser.error("--qty, --side, and --price are required to place a limit order")

    price = format(args.price.normalize(), "f")
    body = {
        "Exchange": args.exch,
        "ExchangeType": args.exchtype,
        "ScripCode": str(args.scripcode) if args.scripcode else "0",
        "Price": price,
        "StopLossPrice": "0",
        "OrderType": "Buy" if args.side == "B" else "Sell",
        "Qty": args.qty,
        "DisQty": "0",
        "IsIntraday": args.intraday,
        "isMTF": False,
        "iOrderValidity": "0",
        "AHPlaced": "N",
    }
    if args.scripdata:
        body["ScripData"] = args.scripdata
    if not args.minimal or args.stop_loss_percent is not None:
        body["RemoteOrderID"] = f"limit{int(time.time() * 1000)}"
    if not args.minimal:
        body["AlgoID"] = args.algoid

    print("Regular limit order to place:\n", json.dumps(body, indent=2))
    if args.stop_loss_percent is not None:
        tick_size = get_tick_size(
            args.scripcode, args.exch, args.exchtype
        )
        trigger_price = stop_trigger_price(
            args.price, args.side, args.stop_loss_percent, tick_size
        )
        stop_side = "Sell" if args.side == "B" else "Buy"
        print(
            f"\nStop-market protection: {args.stop_loss_percent}% from entry "
            f"limit price; {stop_side} trigger {format(trigger_price, 'f')} "
            f"(tick size {format(tick_size, 'f')})."
        )
        print(
            "The stop is submitted only after 5paisa reports a fill. "
            "Market exits can execute at a different price."
        )
    if not args.confirm:
        print("\nDRY RUN - nothing sent. Add --confirm to place it.")
        return 0

    config = configparser.ConfigParser(interpolation=None)
    if not config.read(CONFIG):
        raise FileNotFoundError(
            f"Cannot find configuration file: {CONFIG}. Set FP_CONFIG to its path if needed."
        )
    if not config.has_section("5paise_login"):
        raise configparser.NoSectionError("5paise_login")
    settings = config["5paise_login"]
    token = get_access_token(settings)
    order_result = submit_order(body, settings, token)
    remote_order_id = order_result.get("RemoteOrderID") or body.get("RemoteOrderID")
    if args.stop_loss_percent is None:
        print(
            "\nLimit order accepted. "
            f"BrokerOrderID={order_result.get('BrokerOrderID')} "
            f"RemoteOrderID={remote_order_id}"
        )
        return 0

    if not remote_order_id:
        raise RuntimeError(
            "Limit order was accepted but no RemoteOrderID was returned; "
            "cannot monitor fills for stop-loss protection."
        )
    print(
        "\nLimit order accepted. "
        f"BrokerOrderID={order_result.get('BrokerOrderID')} "
        f"RemoteOrderID={remote_order_id}"
    )
    monitor_entry(
        settings,
        token,
        str(remote_order_id),
        args.scripcode,
        args.qty,
        args.side,
        args.exch,
        args.exchtype,
        args.intraday,
        args.price,
        args.stop_loss_percent,
        tick_size,
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (
        configparser.Error,
        FileNotFoundError,
        KeyError,
        OSError,
        requests.RequestException,
        RuntimeError,
        ValueError,
    ) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
