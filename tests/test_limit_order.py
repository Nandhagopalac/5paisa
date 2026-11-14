import importlib.util
from io import StringIO
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "Order" / "limit" / "Place_limitorder.py"
SPEC = importlib.util.spec_from_file_location("place_limitorder", MODULE_PATH)
place_limitorder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(place_limitorder)


class QuoteLtpTests(unittest.TestCase):
    def test_zero_ltp_is_unavailable(self):
        response = {"body": {"Data": [{"ScripCode": 45386, "LastRate": 0}]}}

        self.assertIsNone(place_limitorder.quote_ltp(response, 45386))

    def test_positive_ltp_is_preserved(self):
        response = {"body": {"Data": [{"ScripCode": 45386, "LastRate": "12.5"}]}}

        self.assertEqual(place_limitorder.quote_ltp(response, 45386), place_limitorder.Decimal("12.5"))

    def test_negative_ltp_is_rejected(self):
        response = {"body": {"Data": [{"ScripCode": 45386, "LastRate": -1}]}}

        with self.assertRaisesRegex(RuntimeError, "invalid LTP"):
            place_limitorder.quote_ltp(response, 45386)

    def test_ltp_only_reports_unavailable_quote(self):
        arguments = [
            "Place_limitorder.py",
            "--ltp-only",
            "--scripcode", "45386",
            "--symbol", "NIFTY 17 NOV 2026 CE 25000.00",
            "--expiry", "20261117",
            "--strike", "25000",
            "--option-type", "CE",
        ]
        output = StringIO()
        with patch.object(sys, "argv", arguments), \
                patch.object(place_limitorder, "load_settings", return_value={}), \
                patch.object(place_limitorder, "get_market_feed_client", return_value=object()), \
                patch.object(place_limitorder, "fetch_ltp", return_value=None), \
                patch("sys.stdout", output):
            self.assertEqual(place_limitorder.main(), 0)

        self.assertIn("LTP=UNAVAILABLE", output.getvalue())


class StopLossTests(unittest.TestCase):
    def test_stop_trigger_uses_side_and_tick_safe_rounding(self):
        buy_trigger = place_limitorder.stop_trigger_price(
            place_limitorder.Decimal("100.03"),
            "B",
            place_limitorder.Decimal("2"),
            place_limitorder.Decimal("0.05"),
        )
        sell_trigger = place_limitorder.stop_trigger_price(
            place_limitorder.Decimal("100.03"),
            "S",
            place_limitorder.Decimal("2"),
            place_limitorder.Decimal("0.05"),
        )

        self.assertEqual(buy_trigger, place_limitorder.Decimal("98.05"))
        self.assertEqual(sell_trigger, place_limitorder.Decimal("102"))

    def test_stop_percentage_must_be_less_than_100(self):
        with self.assertRaises(place_limitorder.argparse.ArgumentTypeError):
            place_limitorder.positive_percentage("100")

    def test_stop_market_body_is_opposite_side_and_at_market(self):
        body = place_limitorder.build_stop_market_body(
            45386,
            1,
            "B",
            "N",
            "D",
            True,
            place_limitorder.Decimal("98"),
            "sl123",
        )

        self.assertEqual(body["OrderType"], "Sell")
        self.assertEqual(body["Price"], "0")
        self.assertEqual(body["StopLossPrice"], "98")
        self.assertTrue(body["AtMarket"])
        self.assertTrue(body["IsStopLossOrder"])

    def test_monitor_places_stops_for_incremental_partial_fills(self):
        statuses = [
            {"TradedQty": 1, "OrderStatus": "Pending"},
            {"TradedQty": 3, "OrderStatus": "Fully Executed"},
        ]
        with patch.object(place_limitorder, "token_valid", return_value=True), \
                patch.object(place_limitorder, "get_order_status", side_effect=statuses), \
                patch.object(place_limitorder, "submit_order", return_value={"Status": 0}) as submit, \
                patch.object(place_limitorder.time, "sleep"), \
                patch("sys.stdout", StringIO()):
            place_limitorder.monitor_entry(
                {"USER_KEY": "key"},
                "token",
                "limit123",
                45386,
                3,
                "B",
                "N",
                "D",
                True,
                place_limitorder.Decimal("100"),
                place_limitorder.Decimal("2"),
                place_limitorder.Decimal("0.05"),
            )

        self.assertEqual([call.args[0]["Qty"] for call in submit.call_args_list], [1, 2])


if __name__ == "__main__":
    unittest.main()
