"""Cancel all pending 5paisa after-market orders from the order book.

Run from the project root (or any working directory):
    & .\\.venv_5paisa\\Scripts\\python.exe .\\Order\\amo\\Cancel_AMOorder.py
Every cancellable pending AMO is submitted for cancellation without prompting.
"""
import base64
import binascii
import configparser
import json
import os
import re
import sys
import time
from pathlib import Path

from py5paisa import FivePaisaClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
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


def main():
    client = authenticated_client()
    orders = cancellable_amo_orders(client.order_book())
    if not orders:
        print("No pending AMO orders with an exchange order ID were found. Nothing cancelled.")
        return 0

    print(f"Cancelling all {len(orders)} pending AMO order(s):")
    failures = 0
    cancelled_ids = set()
    for order in orders:
        order_id = str(value(order, "ExchOrderID", "ExchangeOrderID")).strip()
        if order_id in cancelled_ids:
            continue
        cancelled_ids.add(order_id)
        print(f"\nCancelling: {describe(order)}")
        response = client.cancel_order(order_id)
        if not isinstance(response, dict):
            print(f"FAILED: no valid cancellation response for exchange order {order_id}.")
            failures += 1
            continue

        print(json.dumps(response, indent=2, default=str))
        status = response.get("Status")
        if status is None or str(status) not in {"0", "200"}:
            message = response.get("Message") or f"Unexpected cancellation status: {status!r}."
            print(f"FAILED: exchange order {order_id}: {message}")
            failures += 1
            continue
        print(f"Cancellation request accepted for exchange order {order_id}.")

    if failures:
        print(f"\nCancellation finished with {failures} failure(s).")
        return 1
    print(f"\nCancellation requests accepted for all {len(cancelled_ids)} pending AMO order(s).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (FileNotFoundError, KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
