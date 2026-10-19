import webbrowser
import configparser
from datetime import datetime
from pathlib import Path
from py5paisa import FivePaisaClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_config(config_path="config.ini"):
    config = configparser.ConfigParser()
    config.optionxform = str
    config_path = Path(config_path)
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path

    loaded_files = config.read(config_path)
    if not loaded_files:
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

    redirect_url = config["5paise_login"].get("REDIRECT_URL")
    if not redirect_url:
        raise ValueError(
            "Missing REDIRECT_URL in the [5paise_login] section of config.ini."
        )
    stored_access_token = config["5paise_login"].get("access_token", fallback=None)

    return cred, redirect_url, stored_access_token


def save_access_token(access_token):
    config_path = PROJECT_ROOT / "config.ini"
    config = configparser.ConfigParser()
    config.optionxform = str
    if not config.read(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    if not config.has_section("5paise_login"):
        raise configparser.NoSectionError("5paise_login")

    config.set("5paise_login", "access_token", access_token)
    with config_path.open("w", encoding="utf-8") as config_file:
        config.write(config_file)


def get_5paisa_access_token():
    cred, redirect_url, _ = read_config()

    vendor_key = cred["USER_KEY"]
    login_url = (
        f"https://dev-openapi.5paisa.com/WebVendorLogin/VLogin/Index"
        f"?VendorKey={vendor_key}&ResponseURL={redirect_url}"
    )

    print("\n[INFO] Opening 5paisa login page in your browser...")
    webbrowser.open_new_tab(login_url)
    print(f"[ACTION REQUIRED] Complete the login and copy the full RequestToken from the browser URL.")
    print(f"Example: {redirect_url}?RequestToken=YOUR_TOKEN_HERE\n")

    copied_request_token = input("Paste the full RequestToken here: ").strip()

    if not copied_request_token:
        print("[ERROR] No RequestToken entered. Exiting.")
        return

    try:
        client = FivePaisaClient(cred=cred)

        # Authenticate using RequestToken
        print(f"{datetime.now().strftime('%H:%M:%S')} | Requesting OAuth session...")
        client.get_oauth_session(copied_request_token)
        print(f"{datetime.now().strftime('%H:%M:%S')} | Logged in!!")

        # Get Access Token
        print(f"{datetime.now().strftime('%H:%M:%S')} | Fetching Access Token...")
        access_token = client.get_access_token()
        if not access_token:
            raise RuntimeError("5paisa did not return an access token.")
        save_access_token(access_token)
        print("[SUCCESS] Access token saved to the local config.ini.")
        return access_token

    except Exception as error:
        print(f"[ERROR] Authentication failed ({type(error).__name__}).")
        raise

if __name__ == "__main__":
    get_5paisa_access_token()