import configparser
from pathlib import Path

from py5paisa import FivePaisaClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_config(config_path="config.ini"):
    config = configparser.ConfigParser()
    config_path = Path(config_path)
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path

    if not config.read(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    if "5paise_login" not in config:
        raise configparser.NoSectionError("5paise_login")

    cred = {
        "APP_NAME": config["5paise_login"]["APP_NAME"],
        "APP_SOURCE": config["5paise_login"]["APP_SOURCE"],
        "USER_ID": config["5paise_login"]["USER_ID"],
        "PASSWORD": config["5paise_login"]["PASSWORD"],
        "USER_KEY": config["5paise_login"]["USER_KEY"],
        "ENCRYPTION_KEY": config["5paise_login"]["ENCRYPTION_KEY"]
    }
    access_token = config["5paise_login"].get("access_token", fallback="").strip()
    client_code = config["5paise_login"].get("CLIENT_CODE", fallback="").strip()

    return cred, access_token, client_code # <--- RETURN client_code


def create_client_with_access_token(cred, access_token, client_code):
    if not access_token:
        print("[ERROR] Invalid or empty access token.")
        return None
    
    if not client_code:
        print("[ERROR] Missing ClientCode in config.ini. Please ensure 'CLIENT_CODE' is set.")
        return None

    client = FivePaisaClient(cred=cred)
    client.set_access_token(access_token, client_code)

    print("[INFO] Client initialized with stored access token.")
    return client


def main():
    cred, access_token, client_code = read_config()

    client = create_client_with_access_token(cred, access_token, client_code)
    if client is None:
        print("[ERROR] Could not create client due to missing access token or client code.")
        return

    print("[INFO] Fetching holdings...")
    holdings = client.holdings()
    print("Holdings:", holdings)

    print("[INFO] Fetching margin...")
    margin = client.margin()
    print("Margin:", margin)

    print("[INFO] Fetching positions...")
    positions = client.positions()
    print("Positions:", positions)
    print("[INFO] market Status...")
    print(client.get_market_status())

    print("[INFO] Fetching order book...")
    order_book = client.order_book()
    print("Order Book:", order_book)

    print("[INFO] Fetching trade book...")
    trade_book = client.get_tradebook()
    print("Trade Book:", trade_book)


if __name__ == "__main__":
    main()