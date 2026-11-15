from datetime import date, datetime
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "Streaming"
    / "nifty"
    / "options_monitor.py"
)
SPEC = importlib.util.spec_from_file_location("nifty_options_monitor", MODULE_PATH)
options_monitor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(options_monitor)


class NiftyOptionsMonitorTests(unittest.TestCase):
    def setUp(self):
        import pandas as pd

        self.contracts = options_monitor.nifty_contracts(
            pd.DataFrame(
                [
                    {
                        "Exch": "N",
                        "ExchType": "D",
                        "ScripCode": 101,
                        "Expiry": "2026-11-17",
                        "ScripType": "CE",
                        "StrikeRate": 25000,
                        "SymbolRoot": "NIFTY",
                    },
                    {
                        "Exch": "N",
                        "ExchType": "D",
                        "ScripCode": 102,
                        "Expiry": "2026-11-17",
                        "ScripType": "PE",
                        "StrikeRate": 25000,
                        "SymbolRoot": "NIFTY",
                    },
                    {
                        "Exch": "N",
                        "ExchType": "D",
                        "ScripCode": 103,
                        "Expiry": "2026-11-17",
                        "ScripType": "CE",
                        "StrikeRate": 25050,
                        "SymbolRoot": "NIFTY",
                    },
                    {
                        "Exch": "N",
                        "ExchType": "D",
                        "ScripCode": 104,
                        "Expiry": "2026-11-17",
                        "ScripType": "PE",
                        "StrikeRate": 25050,
                        "SymbolRoot": "NIFTY",
                    },
                ]
            )
        )

    def test_selects_nearest_strike_and_matching_call_put(self):
        strike, pair = options_monitor.select_atm_pair(
            self.contracts, date(2026, 11, 17), 25037
        )

        self.assertEqual(strike, 25050)
        self.assertEqual(pair["CE"]["ScripCode"], 103)
        self.assertEqual(pair["PE"]["ScripCode"], 104)

    def test_expiries_excludes_expired_contracts(self):
        expiries = options_monitor.available_expiries(
            self.contracts, today=date(2026, 11, 17)
        )

        self.assertEqual(expiries, [date(2026, 11, 17)])

    def test_market_status_pauses_quotes_on_weekends_and_outside_hours(self):
        self.assertEqual(
            options_monitor.nse_market_status(datetime(2026, 11, 15, 10, 0)),
            (False, "Market closed (weekend)"),
        )
        self.assertEqual(
            options_monitor.nse_market_status(datetime(2026, 11, 16, 8, 0)),
            (False, "Market closed (outside 09:15–15:30 IST)"),
        )
        self.assertEqual(
            options_monitor.nse_market_status(datetime(2026, 11, 16, 10, 0)),
            (True, "Scheduled market session open"),
        )

    def test_quote_ltp_matches_requested_scrip(self):
        response = {
            "body": {
                "Data": [
                    {"ScripCode": 101, "LastRate": 12.5},
                    {"ScripCode": 102, "LastRate": 18.25},
                ]
            }
        }

        self.assertEqual(options_monitor.quote_ltp(response, 102), 18.25)

    def test_quote_ltp_rejects_unavailable_value(self):
        with self.assertRaisesRegex(
            options_monitor.QuoteDataError, "unavailable quote"
        ):
            options_monitor.quote_ltp(
                {"body": {"Data": [{"ScripCode": 101, "LastRate": 0}]}},
                101,
            )

    def test_option_quote_request_uses_scrip_master_contract_fields(self):
        contract = self.contracts.iloc[0].to_dict()

        request = options_monitor.option_quote_request(contract)

        self.assertEqual(
            request,
            {
                "Exch": "N",
                "ExchType": "D",
                "Symbol": "NIFTY",
                "Expiry": "20261117",
                "StrikePrice": 25000.0,
                "OptionType": "CE",
            },
        )

    def test_fetch_quotes_sends_one_batch_and_maps_response(self):
        client = Mock()
        client.fetch_market_feed.return_value = {
            "body": {
                "Data": [
                    {"ScripCode": 101, "LastRate": 12.5},
                    {"ScripCode": 102, "LastRate": 18.25},
                ]
            }
        }
        requests = {
            101: {"Exch": "N", "ExchType": "D"},
            102: {"Exch": "N", "ExchType": "D"},
        }

        quotes = options_monitor.fetch_quotes(client, requests)

        client.fetch_market_feed.assert_called_once_with(list(requests.values()))
        self.assertEqual(quotes, {101: 12.5, 102: 18.25})


if __name__ == "__main__":
    unittest.main()
