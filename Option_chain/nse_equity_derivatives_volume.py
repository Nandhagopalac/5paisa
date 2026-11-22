import argparse
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont


PAGE_URL = "https://www.nseindia.in/market-data/equity-derivatives-watch"
API_URL = "https://www.nseindia.in/api/liveEquity-derivatives?index=top20_contracts"
DEFAULT_OUTPUT = Path(__file__).resolve().with_name("equity_derivatives_ce_pe.png")


def get_font(size, bold=False):
    fonts_dir = Path(r"C:\Windows\Fonts")
    filename = "segoeuib.ttf" if bold else "segoeui.ttf"
    font_path = fonts_dir / filename
    if font_path.is_file():
        return ImageFont.truetype(str(font_path), size=size)
    return ImageFont.load_default(size=size)


def format_indian(value):
    value = str(int(value))
    if len(value) <= 3:
        return value
    last_three = value[-3:]
    remaining = value[:-3]
    groups = []
    while remaining:
        groups.append(remaining[-2:])
        remaining = remaining[:-2]
    return ",".join(reversed(groups)) + "," + last_three


def fetch_market_data():
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
            ),
            "Referer": PAGE_URL,
        }
    )
    try:
        page_response = session.get(PAGE_URL, timeout=30)
        page_response.raise_for_status()
        response = session.get(API_URL, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Could not retrieve NSE market data: {exc}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("NSE returned invalid JSON for market data.") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise RuntimeError("NSE response did not contain a market-data list.")

    totals = {"Call": 0, "Put": 0}
    row_counts = {"Call": 0, "Put": 0}
    for row in payload["data"]:
        if not isinstance(row, dict):
            raise RuntimeError("NSE returned an invalid market-data row.")
        option_type = row.get("optionType")
        if option_type not in totals:
            continue
        try:
            # The page's Volume (Contracts) column is mapped to noOfTrades.
            contracts = int(row["noOfTrades"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(
                f"NSE returned invalid contract volume for {option_type}."
            ) from exc
        if contracts < 0:
            raise RuntimeError("NSE returned a negative contract volume.")
        totals[option_type] += contracts
        row_counts[option_type] += 1

    return totals, row_counts, payload.get("timestamp"), payload.get("marketStatus")


def create_chart(totals, row_counts, timestamp, market_status, output_path):
    width, height = 1000, 620
    image = Image.new("RGB", (width, height), "#F8FAFC")
    draw = ImageDraw.Draw(image)
    title_font = get_font(32, bold=True)
    subtitle_font = get_font(17)
    value_font = get_font(24, bold=True)
    label_font = get_font(22, bold=True)
    small_font = get_font(15)

    draw.text((55, 38), "NSE Equity Derivatives", fill="#0F172A", font=title_font)
    draw.text(
        (57, 91),
        f"Top 20 Contracts | Volume in contracts | As of {timestamp or 'unknown'} IST",
        fill="#475569",
        font=subtitle_font,
    )
    status_text = ""
    if isinstance(market_status, dict):
        status_text = market_status.get("marketStatusMessage", "")
    if status_text:
        draw.text((57, 120), status_text, fill="#64748B", font=small_font)

    categories = (
        ("Call (CE)", totals["Call"], row_counts["Call"], "#16A36A"),
        ("Put (PE)", totals["Put"], row_counts["Put"], "#E34B4B"),
    )
    max_value = max(totals.values(), default=0)
    chart_top, chart_bottom = 205, 475
    chart_height = chart_bottom - chart_top
    bar_width = 220
    centers = (330, 670)

    draw.line(
        (150, chart_bottom, 850, chart_bottom),
        fill="#CBD5E1",
        width=2,
    )
    for (label, value, count, color), center in zip(categories, centers):
        bar_height = round(chart_height * value / max_value) if max_value else 0
        left = center - bar_width // 2
        top = chart_bottom - bar_height
        draw.rounded_rectangle(
            (left, top, left + bar_width, chart_bottom),
            radius=12,
            fill=color,
        )
        value_text = format_indian(value)
        value_box = draw.textbbox((0, 0), value_text, font=value_font)
        value_width = value_box[2] - value_box[0]
        draw.text(
            (center - value_width // 2, max(chart_top - 42, top - 42)),
            value_text,
            fill="#0F172A",
            font=value_font,
        )
        label_box = draw.textbbox((0, 0), label, font=label_font)
        label_width = label_box[2] - label_box[0]
        draw.text(
            (center - label_width // 2, chart_bottom + 20),
            label,
            fill="#0F172A",
            font=label_font,
        )
        count_text = f"{count} contracts"
        count_box = draw.textbbox((0, 0), count_text, font=small_font)
        draw.text(
            (center - (count_box[2] - count_box[0]) // 2, chart_bottom + 55),
            count_text,
            fill="#64748B",
            font=small_font,
        )

    difference = abs(totals["Call"] - totals["Put"])
    leading = "CE" if totals["Call"] > totals["Put"] else "PE"
    result_text = (
        f"{leading} leads by {format_indian(difference)} contracts"
        if difference
        else "CE and PE volumes are equal"
    )
    result_box = draw.textbbox((0, 0), result_text, font=subtitle_font)
    draw.text(
        ((width - (result_box[2] - result_box[0])) // 2, 555),
        result_text,
        fill="#334155",
        font=subtitle_font,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG")


def main():
    parser = argparse.ArgumentParser(
        description="Compare CE and PE contract volume from NSE's derivatives watch."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Chart PNG path (default: {DEFAULT_OUTPUT}).",
    )
    args = parser.parse_args()

    totals, row_counts, timestamp, market_status = fetch_market_data()
    total_rows = sum(row_counts.values())
    if total_rows == 0:
        raise RuntimeError("NSE returned no Call or Put contracts to compare.")
    create_chart(totals, row_counts, timestamp, market_status, args.output)

    call_volume = totals["Call"]
    put_volume = totals["Put"]
    if call_volume > put_volume:
        result = f"CE is higher by {format_indian(call_volume - put_volume)} contracts."
    elif put_volume > call_volume:
        result = f"PE is higher by {format_indian(put_volume - call_volume)} contracts."
    else:
        result = "CE and PE contract volumes are equal."

    print(f"As of: {timestamp or 'unknown'} IST")
    if isinstance(market_status, dict):
        print(market_status.get("marketStatusMessage", ""))
    print(f"Contracts compared: {total_rows}")
    print(f"CE volume: {format_indian(call_volume)} contracts ({row_counts['Call']} rows)")
    print(f"PE volume: {format_indian(put_volume)} contracts ({row_counts['Put']} rows)")
    print(result)
    print(f"Chart saved: {args.output.resolve()}")


if __name__ == "__main__":
    main()
