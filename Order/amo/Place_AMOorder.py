r"""
Quick PowerShell shortcut:
    .\Order\amo\amo.ps1
Choose a contract from the latest HTML report with the arrow keys, press Enter,
then type Y after reviewing the order to submit it. Defaults can be overridden:
    .\Order\amo\amo.ps1 -Quantity 1 -Price 445 -Side B

Direct Python invocation:
    & .\.venv_5paisa\Scripts\python.exe .\Order\amo\Place_AMOorder.py --scripcode 47133 --qty 65 --price 7.5 --side B --exchtype D --confirm
Place an After-Market Order (AMO) on 5paisa via the Xstream REST API.

Docs: https://xstream.5paisa.com/dev-docs/order-management-system/place-order
  POST https://Openapi.5paisa.com/VendorsAPI/Service1.svc/V1/PlaceOrderRequest
  Authorization: bearer <access token>,  body: {"head": {"key": <app key>}, "body": {...}}

Credentials are read from config.ini (section [5paise_login]) in the project
root, or from the file named in the FP_CONFIG environment variable.
Needed keys: APP_NAME, APP_SOURCE, USER_ID, PASSWORD, USER_KEY, ENCRYPTION_KEY.
Optional: access_token (re-used while still valid; refreshed + saved when expired).

Access tokens last only ~1 hour. When the stored token has expired the script
asks you to log in once:
    1. Open in your browser and log in to 5paisa:
       https://dev-openapi.5paisa.com/WebVendorLogin/VLogin/Index?VendorKey=<USER_KEY>&ResponseURL=https://www.5paisa.com/technology/developer-apis
    2. Copy the request token from the URL you land on.
    3. Paste it here within ~30 seconds.

Direct Python usage (DRY RUN by default, nothing is sent):
    & .\.venv_5paisa\Scripts\python.exe .\Order\amo\Place_AMOorder.py --scripcode 1660 --qty 1 --price 445 --side B
    & .\.venv_5paisa\Scripts\python.exe .\Order\amo\Place_AMOorder.py --scripdata ITC_EQ --qty 1 --price 445 --side B
Place it for real by adding --confirm.

If 5paisa rejects the order, try  --minimal  : it sends exactly the body shown in
the docs' sample request (no RemoteOrderID / AlgoID), only AHPlaced is "Y".
"""
import argparse
import base64
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


def token_valid(tok):
    """True if the JWT is present and not within 60s of expiring."""
    try:
        payload = tok.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        exp = json.loads(base64.urlsafe_b64decode(payload))["exp"]
        return exp > time.time() + 60
    except Exception:
        return False


def save_token(tok):
    """Replace only the access_token line in config.ini, leaving the rest as is."""
    text = CONFIG.read_text(encoding="utf-8")
    new, n = re.subn(r"(?m)^access_token\s*=.*$", lambda m: f"access_token = {tok}", text)
    if n == 0:
        new = re.sub(r"(?m)^(\[5paise_login\]\s*)$", lambda m: m.group(1) + f"\naccess_token = {tok}", text, count=1)
    CONFIG.write_text(new, encoding="utf-8")


p = argparse.ArgumentParser()
p.add_argument("--scripcode", type=int, help="numeric scrip code, e.g. 1660 (ITC)")
p.add_argument("--scripdata", help="symbol such as ITC_EQ (used instead of --scripcode)")
p.add_argument("--qty", type=int, required=True)
p.add_argument("--price", type=float, required=True, help="limit price; 0 = market")
p.add_argument("--side", choices=["B", "S"], required=True, help="B=buy, S=sell")
p.add_argument("--exch", default="N", help="N=NSE, B=BSE, M=MCX")
p.add_argument("--exchtype", default="C", help="C=cash, D=derivatives, U=currency")
p.add_argument("--intraday", action="store_true", help="default is delivery")
p.add_argument("--algoid", default="0", help="Algo ID if you are a registered algo user")
p.add_argument("--minimal", action="store_true",
               help="send exactly the docs' sample body (no RemoteOrderID/AlgoID)")
p.add_argument("--confirm", action="store_true", help="really send the order")
a = p.parse_args()
if not a.scripcode and not a.scripdata:
    p.error("give --scripcode or --scripdata")

# Built from the docs' sample request body.
body = {
    "Exchange": a.exch,
    "ExchangeType": a.exchtype,
    "ScripCode": str(a.scripcode) if a.scripcode else "0",
    "Price": f"{a.price:g}",  # "445", not "445.0", like the docs' sample
    "StopLossPrice": "0",
    "OrderType": "Buy" if a.side == "B" else "Sell",
    "Qty": a.qty,
    "DisQty": "0",
    "IsIntraday": a.intraday,
    "isMTF": False,
    "iOrderValidity": "0",
    "AHPlaced": "Y",  # Y = after-market order (the docs' sample has "N")
}
if a.scripdata:
    body["ScripData"] = a.scripdata
if not a.minimal:
    body["RemoteOrderID"] = f"amo{int(time.time())}"  # docs list it as mandatory
    body["AlgoID"] = a.algoid  # docs: non-algo users pass 0 or null

print("Order to place:\n", json.dumps(body, indent=2))
if not a.confirm:
    print("\nDRY RUN - nothing sent. Add --confirm to place it.")
    sys.exit(0)

cfg = configparser.ConfigParser(interpolation=None)  # passwords may contain '%'
if not cfg.read(CONFIG):
    sys.exit(f"Cannot find {CONFIG}. Set FP_CONFIG to its path if needed.")
s = cfg["5paise_login"]
app_key = s["USER_KEY"].strip()
token = s.get("access_token", "").strip()

if token_valid(token):
    print("Using saved access token (still valid).")
else:
    from py5paisa import FivePaisaClient

    print("Access token missing or expired -> OAuth login needed (see top of this file).")
    cred = {k: s[k].strip() for k in
            ("APP_NAME", "APP_SOURCE", "USER_ID", "PASSWORD", "USER_KEY", "ENCRYPTION_KEY")}
    client = FivePaisaClient(cred=cred)
    client.get_oauth_session(input("Paste request token: ").strip())
    token = client.get_access_token()
    if not token_valid(token):
        sys.exit("Login did not return a valid access token. Re-do the login and paste the token faster.")
    save_token(token)
    print(f"New access token saved to {CONFIG}.")

resp = requests.post(
    URL,
    headers={"Content-Type": "application/json", "Authorization": f"bearer {token}"},
    json={"head": {"key": app_key}, "body": body},
    timeout=20,
)
print("\nHTTP", resp.status_code)
try:
    out = resp.json()
    print(json.dumps(out, indent=2))
except ValueError:
    print(resp.text)
    sys.exit(1)

head = out.get("head") or {}
b = out.get("body") or {}
if head.get("status") == "0" and b.get("Status") == 0:
    print(f"\nAMO accepted. BrokerOrderID={b.get('BrokerOrderID')} RemoteOrderID={b.get('RemoteOrderID')}")
    sys.exit(0)

msg = b.get("Message") or head.get("statusDescription")
print(f"\nNOT placed: {msg}")
hints = {
    "Authentication Fails": "access token is expired/invalid -> delete access_token from config.ini and log in again.",
    "Invalid Session": "token does not belong to this user/client code -> log in again with the right account.",
    "Invalid Input Parameters.": "a field is wrong/missing -> check scrip code, qty, price; try --minimal.",
}
if head.get("status") == "2" or "Invalid Head" in str(msg):
    print("Hint: USER_KEY (app key) in the request head is wrong.")
elif msg in hints:
    print("Hint:", hints[msg])
elif b.get("Status") == 1 or b.get("RMSResponseCode") == 0 and b.get("Status") == 0:
    print("Hint: 5paisa's risk system (RMS) rejected it - check funds/margin, price band, and AMO timing.")
sys.exit(1)