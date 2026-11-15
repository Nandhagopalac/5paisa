import argparse
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright


OPTION_CHAIN_URL = "https://web.sensibull.com/option-chain?view=ltp"
LOGIN_PROMPT = "Login with your broker for real-time prices and trading."
PROFILE_DIR = Path.home() / ".sensibull-playwright-profile"
SCREENSHOT_DIR = Path.home() / "SensibullScreenshots"
INDIA_TIME = ZoneInfo("Asia/Kolkata")


def main():
    parser = argparse.ArgumentParser(
        description="Capture the Sensibull option-chain page using a persistent local browser session."
    )
    parser.add_argument(
        "--login",
        action="store_true",
        help="Open a visible browser so you can log in and save today's session.",
    )
    args = parser.parse_args()

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=not args.login,
            viewport={"width": 1600, "height": 1000},
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(
                OPTION_CHAIN_URL,
                wait_until="domcontentloaded",
                timeout=60_000,
            )

            if args.login:
                input(
                    "Log in to Sensibull in the opened browser, then press Enter "
                    "here to save the session and close the browser..."
                )
                return

            page.wait_for_timeout(10_000)
            if page.get_by_text(LOGIN_PROMPT, exact=False).count():
                raise RuntimeError(
                    "Sensibull is asking for a broker login. Run this script "
                    "with --login on the runner device, then try again."
                )

            captured_at = datetime.now(INDIA_TIME)
            SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            screenshot_path = SCREENSHOT_DIR / (
                f"sensibull-option-chain-{captured_at:%Y%m%d-%H%M%S}-IST.png"
            )
            page.screenshot(path=str(screenshot_path), full_page=True)
            print(f"Screenshot saved: {screenshot_path}")
        finally:
            context.close()


if __name__ == "__main__":
    main()
