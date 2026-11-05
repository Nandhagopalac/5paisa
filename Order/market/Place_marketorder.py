"""Place a regular 5paisa market order through the Xstream REST API.

Run from the project root (dry run by default):
    & .\\.venv_5paisa\\Scripts\\python.exe .\\Order\\Place_marketorder.py --scripcode 47133 --qty 65 --side B
    .\\Order\\market\\market.ps1 -Quantity 1 -Side B

Add --confirm to submit. Market orders can execute immediately at a price
different from the last traded price. Credentials are read from config.ini
next to the project root, or from the file named by FP_CONFIG.
"""
import argparse
import base64
import binascii
import configparser
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

URL = "https://Openapi.5paisa.com/VendorsAPI/Service1.svc/V1/PlaceOrderRequest"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG = Path(os.environ.get("FP_CONFIG", PROJECT_ROOT / "config.ini"))


def positive_int(value):
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


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


def main():
    parser = argparse.ArgumentParser(
        description="Place a regular 5paisa market order (dry run unless --confirm is used)."
    )
    script = parser.add_mutually_exclusive_group(required=True)
    script.add_argument("--scripcode", type=positive_int, help="numeric scrip code, e.g. 1660 (ITC)")
    script.add_argument("--scripdata", type=nonempty_symbol, help="symbol such as ITC_EQ")
    parser.add_argument("--qty", type=positive_int, required=True)
    parser.add_argument("--side", choices=("B", "S"), required=True, help="B=buy, S=sell")
    parser.add_argument("--exch", default="N", help="N=NSE, B=BSE, M=MCX")
    parser.add_argument("--exchtype", default="C", help="C=cash, D=derivatives, U=currency")
    parser.add_argument("--intraday", action="store_true", help="default is delivery")
    parser.add_argument("--algoid", default="0", help="Algo ID if you are a registered algo user")
    parser.add_argument(
        "--minimal",
        action="store_true",
        help="omit RemoteOrderID and AlgoID from the request body",
    )
    parser.add_argument("--confirm", action="store_true", help="really send the order")
    args = parser.parse_args()

    body = {
        "Exchange": args.exch,
        "ExchangeType": args.exchtype,
        "ScripCode": str(args.scripcode) if args.scripcode else "0",
        "Price": "0",
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
    if not args.minimal:
        body["RemoteOrderID"] = f"market{int(time.time())}"
        body["AlgoID"] = args.algoid

    print("Regular market order to place:\n", json.dumps(body, indent=2))
    print("Market orders may execute immediately at a price different from the last traded price.")
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
    app_key = settings["USER_KEY"].strip()
    token = get_access_token(settings)

    response = requests.post(
        URL,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"bearer {token}",
        },
        json={"head": {"key": app_key}, "body": body},
        timeout=20,
    )
    print("\nHTTP", response.status_code)
    response.raise_for_status()
    try:
        result = response.json()
    except requests.exceptions.JSONDecodeError as error:
        print(response.text)
        raise RuntimeError("5paisa returned a non-JSON response.") from error
    print(json.dumps(result, indent=2))
    if not isinstance(result, dict):
        raise RuntimeError("5paisa returned an unexpected response format.")

    head = result.get("head") or {}
    order_result = result.get("body") or {}
    if not isinstance(head, dict) or not isinstance(order_result, dict):
        raise RuntimeError("5paisa returned an unexpected response format.")
    if head.get("status") == "0" and order_result.get("Status") == 0:
        print(
            "\nMarket order accepted. "
            f"BrokerOrderID={order_result.get('BrokerOrderID')} "
            f"RemoteOrderID={order_result.get('RemoteOrderID')}"
        )
        return 0

    message = order_result.get("Message") or head.get("statusDescription")
    print(f"\nNOT placed: {message}")
    if head.get("status") == "2" or "Invalid Head" in str(message):
        print("Hint: USER_KEY (app key) in the request head may be wrong.")
    elif message == "Authentication Fails":
        print("Hint: access token is expired/invalid; log in again.")
    elif message == "Invalid Session":
        print("Hint: log in again with the correct account.")
    elif message == "Invalid Input Parameters.":
        print("Hint: check the scrip code, quantity, and request fields.")
    elif "algo limit order" in str(message).lower():
        print(
            "Hint: 5paisa's RMS rejected this market order and says an algo limit "
            "order is required. This script cannot safely convert a market order "
            "into a limit order; check with 5paisa API support whether your account "
            "and derivatives segment support market orders or require an approved "
            "algo order."
        )
    elif order_result.get("Status") == 1:
        print("Hint: 5paisa RMS rejected the order; check the message above with 5paisa.")
    return 1


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
