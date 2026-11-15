
# & '.\.venv_5paisa\Scripts\python.exe' '.\Option_chain\sensibull_screenshot.py' --tradingsymbol NIFTY --expiry 2026-11-17
import argparse
from datetime import date, datetime, timedelta, timezone
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
from urllib.parse import urlencode

from PIL import Image, ImageDraw, ImageFont


OPTION_CHAIN_URL = "https://web.sensibull.com/option-chain"
SCREENSHOT_DIR = Path(r"C:\Users\agalya\OneDrive\Pictures\OpenBoard")
INDIA_TIME = timezone(timedelta(hours=5, minutes=30), name="IST")


def bold_font(size):
    fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for filename in ("segoeuib.ttf", "arialbd.ttf"):
        font_path = fonts_dir / filename
        if font_path.is_file():
            return ImageFont.truetype(str(font_path), size=size)
    return ImageFont.load_default(size=size)


def add_timestamp(source_path, output_path, captured_at):
    with Image.open(source_path) as source:
        screenshot = source.convert("RGB")

    header_height = 82
    stamped_image = Image.new(
        "RGB",
        (screenshot.width, screenshot.height + header_height),
        "#F8FAFC",
    )
    stamped_image.paste(screenshot, (0, header_height))
    draw = ImageDraw.Draw(stamped_image)
    draw.rectangle((0, 0, 7, header_height), fill="#2563EB")
    draw.line(
        (0, header_height - 1, screenshot.width, header_height - 1),
        fill="#DCE5EF",
        width=2,
    )

    label = "CAPTURED"
    date_text = captured_at.strftime("%d %b %Y").upper()
    time_text = captured_at.strftime("%H:%M:%S")
    timezone_text = "IST"
    label_font = bold_font(16)
    date_font = bold_font(21)
    time_font = bold_font(35)
    timezone_font = bold_font(16)

    label_box = draw.textbbox((0, 0), label, font=label_font)
    date_box = draw.textbbox((0, 0), date_text, font=date_font)
    time_box = draw.textbbox((0, 0), time_text, font=time_font)
    timezone_box = draw.textbbox((0, 0), timezone_text, font=timezone_font)

    label_x = 28
    label_width = label_box[2] - label_box[0]
    label_height = label_box[3] - label_box[1]
    label_y = (header_height - label_height) // 2 - label_box[1]
    label_left = label_x - 12
    label_right = label_x + label_width + 12
    draw.rounded_rectangle(
        (label_left, 19, label_right, 63),
        radius=12,
        fill="#DBEAFE",
    )
    draw.text((label_x, label_y), label, fill="#1D4ED8", font=label_font)

    date_x = label_right + 28
    date_height = date_box[3] - date_box[1]
    date_y = (header_height - date_height) // 2 - date_box[1]
    draw.text((date_x, date_y), date_text, fill="#475569", font=date_font)

    date_right = date_x + date_box[2] - date_box[0]
    divider_x = date_right + 26
    draw.line((divider_x, 23, divider_x, 59), fill="#CBD5E1", width=2)

    time_x = divider_x + 25
    time_height = time_box[3] - time_box[1]
    time_y = (header_height - time_height) // 2 - time_box[1]
    draw.text((time_x, time_y), time_text, fill="#0F172A", font=time_font)

    time_right = time_x + time_box[2] - time_box[0]
    timezone_width = timezone_box[2] - timezone_box[0]
    timezone_height = timezone_box[3] - timezone_box[1]
    timezone_x = time_right + 16
    timezone_y = (header_height - timezone_height) // 2 - timezone_box[1]
    draw.rounded_rectangle(
        (
            timezone_x - 10,
            27,
            timezone_x + timezone_width + 10,
            55,
        ),
        radius=10,
        fill="#EFF6FF",
        outline="#BFDBFE",
        width=1,
    )
    draw.text(
        (timezone_x, timezone_y),
        timezone_text,
        fill="#1D4ED8",
        font=timezone_font,
    )
    stamped_image.save(output_path, format="PNG")


def parse_expiry(value):
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Expiry must use YYYY-MM-DD format.") from exc


def find_edge():
    candidates = [
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
        / "Microsoft"
        / "Edge"
        / "Application"
        / "msedge.exe",
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        / "Microsoft"
        / "Edge"
        / "Application"
        / "msedge.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "Microsoft Edge was not found. Install Edge on this Windows device."
    )


def main():
    parser = argparse.ArgumentParser(
        description="Capture a Sensibull option-chain screenshot using installed Edge."
    )
    parser.add_argument(
        "--tradingsymbol",
        default="NIFTY",
        help="Symbol to open (default: NIFTY).",
    )
    parser.add_argument(
        "--expiry",
        type=parse_expiry,
        default="2026-11-17",
        help="Expiry date in YYYY-MM-DD format (default: 2026-11-17).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=SCREENSHOT_DIR,
        help=f"Folder for PNG files (default: {SCREENSHOT_DIR}).",
    )
    args = parser.parse_args()

    query = urlencode(
        {
            "view": "ltp",
            "tradingsymbol": args.tradingsymbol,
            "expiry": args.expiry,
        }
    )
    url = f"{OPTION_CHAIN_URL}?{query}"
    safe_symbol = re.sub(r"[^A-Za-z0-9._-]", "_", args.tradingsymbol)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    edge = find_edge()
    with TemporaryDirectory(prefix="sensibull-edge-") as profile_dir:
        temp_dir = Path(profile_dir)
        edge_profile = temp_dir / "profile"
        raw_screenshot = temp_dir / "page.png"
        result = subprocess.run(
            [
                str(edge),
                "--headless",
                "--disable-gpu",
                "--no-first-run",
                f"--user-data-dir={edge_profile}",
                "--window-size=1600,1000",
                "--virtual-time-budget=12000",
                f"--screenshot={raw_screenshot}",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

        if result.returncode:
            raise RuntimeError(
                f"Microsoft Edge failed to capture the page: {result.stderr}"
            )
        if not raw_screenshot.is_file() or raw_screenshot.stat().st_size == 0:
            raise RuntimeError("Edge did not create the screenshot.")

        captured_at = datetime.now(INDIA_TIME)
        screenshot_path = args.output_dir / (
            f"sensibull-{safe_symbol}-{args.expiry}-"
            f"{captured_at:%Y%m%d-%H%M%S}-IST.png"
        )
        add_timestamp(raw_screenshot, screenshot_path, captured_at)

    print(f"Screenshot saved: {screenshot_path}")


if __name__ == "__main__":
    main()
