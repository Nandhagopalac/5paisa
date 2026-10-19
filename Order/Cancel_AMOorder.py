"""Select and cancel a pending 5paisa after-market order from the order book.

Run from the project root:
    & .\\.venv_5paisa\\Scripts\\python.exe .\\Order\\Cancel_AMOorder.py
Use Up/Down and Enter to cancel; Esc exits without cancelling.
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

import msvcrt
from py5paisa import FivePaisaClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG = Path(os.environ.get("FP_CONFIG", PROJECT_ROOT / "config.ini"))
TERMINAL_STATUS_WORDS = (
    "cancel",
    "reject",
    "fully executed",
    "complete",
    "expire",
)


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


def authenticated_client():
    config = configparser.ConfigParser(interpolation=None)
    if not config.read(CONFIG):
        raise FileNotFoundError(f"Cannot find configuration file: {CONFIG}")
    if not config.has_section("5paise_login"):
        raise configparser.NoSectionError("5paise_login")

    settings = config["5paise_login"]
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
    token = settings.get("access_token", "").strip()
    client_code = settings["CLIENT_CODE"].strip()

    if not token_valid(token):
        print("Access token missing or expired; login is required.")
        request_token = input(
            "Open the 5paisa login URL from Place_AMOorder.py, then paste the request token: "
        ).strip()
        client.get_oauth_session(request_token)
        token = client.get_access_token()
        if not token or not token_valid(token):
            raise RuntimeError("Login did not return a valid access token.")
        save_token(token)
        print(f"New access token saved to {CONFIG}.")

    client.set_access_token(token, client_code)
    return client


def value(order, *keys, default=""):
    for key in keys:
        result = order.get(key)
        if result is not None and result != "":
            return result
    return default


def cancellable_amo_orders(order_book):
    if not isinstance(order_book, list):
        raise TypeError(
            f"Expected order_book() to return a list, got {type(order_book).__name__}."
        )

    eligible = []
    for order in order_book:
        if not isinstance(order, dict):
            raise TypeError("Order book contains an entry that is not an object.")

        after_hours = str(value(order, "AfterHours", "AHPlaced", default="")).strip().upper()
        if after_hours not in {"Y", "YES", "TRUE", "1"}:
            continue

        order_id = str(value(order, "ExchOrderID", "ExchangeOrderID", default="")).strip()
        if not order_id or order_id == "0":
            continue

        status = str(value(order, "OrderStatus", "Status", default="")).strip().lower()
        if any(word in status for word in TERMINAL_STATUS_WORDS):
            continue

        try:
            pending_qty = int(float(value(order, "PendingQty", default=0)))
        except (TypeError, ValueError):
            raise ValueError(f"Invalid PendingQty for exchange order {order_id}.")
        if pending_qty <= 0:
            continue

        eligible.append(order)
    return eligible


def describe(order):
    order_id = value(order, "ExchOrderID", "ExchangeOrderID", default="?")
    symbol = value(order, "ScripName", "Name", default="Unknown contract")
    side = value(order, "BuySell", "OrderType", default="?")
    quantity = value(order, "Qty", "Quantity", default="?")
    pending = value(order, "PendingQty", default="?")
    price = value(order, "Rate", "Price", default="?")
    status = value(order, "OrderStatus", "Status", default="Unknown status")
    return (
        f"{symbol} | {side} | Qty {quantity} (pending {pending}) | "
        f"Price {price} | {status} | Exchange order {order_id}"
    )


def choose_order(orders):
    selected_index = 0
    while True:
        os.system("cls")
        print("Pending AMO orders — Up/Down to select, Enter to cancel, Esc to exit\n")
        for index, order in enumerate(orders):
            marker = ">" if index == selected_index else " "
            print(f"{marker} {describe(order)}")

        key = msvcrt.getch()
        if key in (b"\x00", b"\xe0"):
            arrow = msvcrt.getch()
            if arrow == b"H":
                selected_index = (selected_index - 1) % len(orders)
            elif arrow == b"P":
                selected_index = (selected_index + 1) % len(orders)
        elif key == b"\r":
            return orders[selected_index]
        elif key == b"\x1b":
            return None


def main():
    parser = argparse.ArgumentParser(
        description="Choose a pending 5paisa AMO from the order book and cancel it."
    )
    parser.parse_args()

    client = authenticated_client()
    orders = cancellable_amo_orders(client.order_book())
    if not orders:
        print("No pending AMO orders with an exchange order ID were found.")
        return 0

    selected_order = choose_order(orders)
    if selected_order is None:
        print("Cancelled selection; no order was sent to the broker.")
        return 0

    order_id = str(value(selected_order, "ExchOrderID", "ExchangeOrderID")).strip()
    print(f"\nCancelling AMO: {describe(selected_order)}")
    response = client.cancel_order(order_id)
    if not isinstance(response, dict):
        raise RuntimeError("5paisa returned no cancellation response.")

    print(json.dumps(response, indent=2, default=str))
    status = response.get("Status")
    if status is not None and str(status) not in {"0", "200"}:
        raise RuntimeError(
            str(response.get("Message") or f"5paisa did not accept cancellation (Status={status}).")
        )
    print("Cancellation request accepted by 5paisa.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (FileNotFoundError, KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
