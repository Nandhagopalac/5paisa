from datetime import date, time
import math
from pathlib import Path

import pandas as pd


REQUIRED_COLUMNS = {
    "Exch",
    "ExchType",
    "ScripCode",
    "Expiry",
    "ScripType",
    "StrikeRate",
    "SymbolRoot",
}
OPTION_TYPES = ("CE", "PE")


class QuoteDataError(ValueError):
    pass


def load_scrip_master(path):
    scrips = pd.read_csv(Path(path))
    missing = REQUIRED_COLUMNS.difference(scrips.columns)
    if missing:
        raise ValueError(
            f"Scrip master is missing columns: {', '.join(sorted(missing))}"
        )
    return scrips


def nifty_contracts(scrips):
    contracts = scrips[
        scrips["SymbolRoot"].fillna("").astype(str).str.upper().eq("NIFTY")
        & scrips["Exch"].fillna("").astype(str).str.upper().eq("N")
        & scrips["ExchType"].fillna("").astype(str).str.upper().eq("D")
        & scrips["ScripType"].fillna("").astype(str).str.upper().isin(OPTION_TYPES)
    ].copy()
    contracts["ExpiryDate"] = pd.to_datetime(
        contracts["Expiry"], errors="coerce"
    ).dt.date
    contracts["StrikeRate"] = pd.to_numeric(
        contracts["StrikeRate"], errors="coerce"
    )
    contracts["ScripCode"] = pd.to_numeric(
        contracts["ScripCode"], errors="coerce"
    )
    return contracts.dropna(subset=["ExpiryDate", "StrikeRate", "ScripCode"])


def available_expiries(contracts, today=None):
    today = today or date.today()
    return sorted(
        expiry
        for expiry in contracts["ExpiryDate"].unique()
        if expiry >= today
    )


def nse_market_status(now):
    if now.weekday() >= 5:
        return False, "Market closed (weekend)"

    local_time = now.timetz().replace(tzinfo=None)
    if time(9, 15) <= local_time <= time(15, 30):
        return True, "Scheduled market session open"
    return False, "Market closed (outside 09:15–15:30 IST)"


def select_atm_pair(contracts, expiry, spot_price):
    expiry_contracts = contracts[contracts["ExpiryDate"].eq(expiry)]
    strikes = sorted(expiry_contracts["StrikeRate"].unique())
    if not strikes:
        raise LookupError(f"No NIFTY option contracts found for {expiry}.")

    strike = min(strikes, key=lambda value: (abs(value - spot_price), value))
    selected = {}
    for option_type in OPTION_TYPES:
        matches = expiry_contracts[
            expiry_contracts["StrikeRate"].eq(strike)
            & expiry_contracts["ScripType"].astype(str).str.upper().eq(option_type)
        ]
        if len(matches) != 1:
            raise LookupError(
                f"Expected one NIFTY {option_type} contract at {strike:g} "
                f"for {expiry}; found {len(matches)}."
            )
        selected[option_type] = matches.iloc[0].to_dict()
    return strike, selected


def index_quote_request(scrip_code):
    return {"Exch": "N", "ExchType": "C", "ScripCode": int(scrip_code)}


def option_quote_request(contract):
    expiry = pd.to_datetime(contract["Expiry"]).strftime("%Y%m%d")
    return {
        "Exch": str(contract["Exch"]),
        "ExchType": str(contract["ExchType"]),
        "Symbol": str(contract["SymbolRoot"]),
        "Expiry": expiry,
        "StrikePrice": float(contract["StrikeRate"]),
        "OptionType": str(contract["ScripType"]).upper(),
    }


def quote_ltp(response, scrip_code):
    if not isinstance(response, (dict, list)):
        raise QuoteDataError("5paisa returned an unexpected market-feed response.")

    quotes = []
    ltp_keys = ("LastRate", "LTP", "LastTradedPrice", "LastTradedRate")
    token_keys = ("ScripCode", "Token", "token", "ExchScripCode", "InstrumentToken")

    def visit(value):
        if isinstance(value, dict):
            rate = next(
                (value[key] for key in ltp_keys if value.get(key) is not None),
                None,
            )
            if rate is not None:
                token = next(
                    (value[key] for key in token_keys if value.get(key) is not None),
                    None,
                )
                quotes.append((token, rate))
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(response)
    matches = [
        rate
        for token, rate in quotes
        if token is not None and str(token).strip() == str(scrip_code)
    ]
    if len(matches) == 1:
        selected_rate = matches[0]
    elif len(matches) > 1:
        raise QuoteDataError(f"5paisa returned duplicate quotes for scrip {scrip_code}.")
    elif len(quotes) == 1:
        selected_rate = quotes[0][1]
    else:
        raise QuoteDataError(f"Could not identify a quote for scrip {scrip_code}.")

    try:
        ltp = float(selected_rate)
    except (TypeError, ValueError) as error:
        raise QuoteDataError(
            f"5paisa returned an invalid quote for scrip {scrip_code}."
        ) from error
    if not math.isfinite(ltp) or ltp <= 0:
        raise QuoteDataError(
            f"5paisa returned an unavailable quote for scrip {scrip_code}."
        )
    return ltp


def fetch_quotes(client, requests_by_code):
    response = client.fetch_market_feed(list(requests_by_code.values()))
    return {
        code: quote_ltp(response, code)
        for code in requests_by_code
    }
