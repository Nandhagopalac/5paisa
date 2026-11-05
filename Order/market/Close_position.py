"""Close a selected open 5paisa position with an opposite-side market order.

Run from the project root or any working directory:
    & .\\.venv_5paisa\\Scripts\\python.exe .\\Order\\market\\Close_position.py

Select an open position with the arrow keys and press Enter to submit its
opposite-side market order. No additional confirmation is requested.
"""
import base64
import binascii
import configparser
import json
import os
import re
import sys
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

import msvcrt
import requests
from py5paisa import FivePaisaClient

URL = "https://Openapi.5paisa.com/VendorsAPI/Service1.svc/V1/PlaceOrderRequest"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG = Path(os.environ.get("FP_CONFIG", PROJECT_ROOT / "config.ini"))


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
    if not token_valid(token):
        print("Access token missing or expired; OAuth login is needed.")
        request_token = input(
            "Open the 5paisa login URL described in Order\\amo\\Place_AMOorder.py "
            "and paste the request token: "
        ).strip()
        client.get_oauth_session(request_token)
        token = client.get_access_token()
        if not token or not token_valid(token):
            raise RuntimeError("Login did not return a valid access token.")
        save_token(token)
        print(f"New access token saved to {CONFIG}.")

    client_code = settings["CLIENT_CODE"].strip()
    client.set_access_token(token, client_code)
    return client, settings["USER_KEY"].strip(), token


def position_value(position, key, *, required=True):
    value = position.get(key)
    if value is None or value == "":
        if required:
            raise ValueError(f"Position is missing required field {key}.")
        return ""
    return value


def open_positions(raw_positions):
    if not isinstance(raw_positions, list):
        raise TypeError(
            f"Expected positions() to return a list, got {type(raw_positions).__name__}."
        )

    result = []
    for position in raw_positions:
        if not isinstance(position, dict):
            raise TypeError("Position book contains an entry that is not an object.")
        try:
            net_quantity = Decimal(str(position_value(position, "NetQty")))
        except (InvalidOperation, ValueError) as error:
            raise ValueError("Position book contains an invalid NetQty.") from error
        if not net_quantity.is_finite() or net_quantity != net_quantity.to_integral_value():
            raise ValueError("Position book contains a non-integer NetQty.")
        if net_quantity == 0:
            continue

        product = str(position_value(position, "OrderFor")).strip().upper()
        if product not in {"I", "D"}:
            raise ValueError(f"Unsupported position product type: {product!r}.")
        position_value(position, "ScripCode")
        position_value(position, "Exch")
        position_value(position, "ExchType")
        result.append((position, int(net_quantity)))
    return result


def describe(position, net_quantity):
    name = position_value(position, "ScripName", required=False) or "Unknown contract"
    exchange = position_value(position, "Exch")
    segment = position_value(position, "ExchType")
    product = "Intraday" if str(position["OrderFor"]).strip().upper() == "I" else "Delivery"
    side = "Long" if net_quantity > 0 else "Short"
    close_side = "Sell" if net_quantity > 0 else "Buy"
    return (
        f"{name} | {side} {abs(net_quantity)} -> {close_side} | "
        f"{product} | {exchange}/{segment} | ScripCode {position['ScripCode']}"
    )


def choose_position(positions):
    selected_index = 0
    while True:
        os.system("cls")
        print("Open positions — Up/Down to select and submit, Esc to exit\n")
        for index, (position, net_quantity) in enumerate(positions):
            marker = ">" if index == selected_index else " "
            print(f"{marker} {describe(position, net_quantity)}")

        key = msvcrt.getch()
        if key in (b"\x00", b"\xe0"):
            arrow = msvcrt.getch()
            if arrow == b"H":
                selected_index = (selected_index - 1) % len(positions)
            elif arrow == b"P":
                selected_index = (selected_index + 1) % len(positions)
        elif key == b"\r":
            return positions[selected_index]
        elif key == b"\x1b":
            return None


def close_order_body(position, net_quantity):
    close_side = "Sell" if net_quantity > 0 else "Buy"
    return {
        "Exchange": position["Exch"],
        "ExchangeType": position["ExchType"],
        "ScripCode": str(position["ScripCode"]),
        "Price": "0",
        "StopLossPrice": "0",
        "OrderType": close_side,
        "Qty": abs(net_quantity),
        "DisQty": "0",
        "IsIntraday": str(position["OrderFor"]).strip().upper() == "I",
        "isMTF": False,
        "iOrderValidity": "0",
        "AHPlaced": "N",
        "RemoteOrderID": f"close{int(time.time())}",
        "AlgoID": "0",
    }


def place_close_order(position, net_quantity, app_key, token):
    body = close_order_body(position, net_quantity)
    print("\nSubmitting close market order:\n", json.dumps(body, indent=2))
    print("A market order may execute immediately at a price different from the last traded price.")

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
            "\nClose order accepted by 5paisa. Verify the order book/position book "
            "to confirm it executed. "
            f"BrokerOrderID={order_result.get('BrokerOrderID')} "
            f"RemoteOrderID={order_result.get('RemoteOrderID')}"
        )
        return 0

    message = order_result.get("Message") or head.get("statusDescription")
    print(f"\nPosition not closed: {message}")
    if "algo limit order" in str(message).lower():
        print(
            "Hint: 5paisa RMS requires an algo limit order for this position. "
            "This market-order script cannot safely convert the close to a limit "
            "order; check the required close-order type with 5paisa API support."
        )
    return 1


def main():
    client, app_key, token = authenticated_client()
    positions = open_positions(client.positions())
    if not positions:
        print("No open positions were found. Nothing was sent.")
        return 0

    selected_position = choose_position(positions)
    if selected_position is None:
        print("Cancelled selection; no order was sent.")
        return 0

    position, net_quantity = selected_position
    print(f"\nSelected position: {describe(position, net_quantity)}")
    return place_close_order(position, net_quantity, app_key, token)


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
        TypeError,
        ValueError,
    ) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
