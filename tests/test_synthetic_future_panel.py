import unittest
from datetime import date

import pandas as pd

from Option_chain import synthetic_future_panel as panel
from tests.test_synthetic_future import FakeClient, make_contracts


class PanelClient(FakeClient):
    FUTURE_CODE = 58875

    def fetch_market_feed_scrip(self, requests):
        data = super().fetch_market_feed_scrip(requests)["Data"]
        for tick in data:
            if tick["Token"] == self.FUTURE_CODE:
                tick["LastRate"] = 25200.0
            tick["PClose"] = tick["LastRate"] * 2   # previous close twice the price -> -50 %
        return {"Data": data}


FUTURES = pd.DataFrame({"Expiry": [date(2026, 12, 29), date(2027, 1, 25)], "ScripCode": [58875, 54749]})


class PanelTests(unittest.TestCase):
    def snapshot(self, spot=25367.5):
        return panel.take_panel(PanelClient(spot), make_contracts(), FUTURES, date(2026, 12, 1))

    def test_near_future_skips_expired(self):
        self.assertEqual(panel.near_future(FUTURES, date(2026, 12, 1)), (date(2026, 12, 29), 58875))
        self.assertEqual(panel.near_future(FUTURES, date(2026, 12, 30)), (date(2027, 1, 25), 54749))
        self.assertIsNone(panel.near_future(FUTURES, date(2027, 2, 1)))

    def test_summary_and_chain(self):
        d = self.snapshot()
        self.assertEqual(d["atm"], 25350)
        self.assertEqual([r["strike"] for r in d["chain"]], [25500, 25450, 25400, 25350, 25300, 25250, 25200])
        # CE 25350 = 17.5 + 40 -> PE 25350 = 0 + 40 ... synthetic = strike + CE - PE
        self.assertAlmostEqual(d["synthetic"], 25350 + d["ce"] - d["pe"])
        self.assertEqual(d["future"], 25200.0)
        self.assertAlmostEqual(d["basis"], d["future"] - d["synthetic"])
        self.assertAlmostEqual(d["chain"][0]["ce"]["chg"], -50.0)

    def test_html_contains_the_table_rows(self):
        text = panel.panel_html(self.snapshot())
        for needle in ("Synthetic Future", "Strike + (CE-PE)", "Last option trade", "CE Chg %", "25350", "Exp 01-12-26"):
            self.assertIn(needle, text)

    def test_trade_time_parses_epoch(self):
        self.assertEqual(panel.trade_time({"TickDt": "/Date(1764065340000)/"}), "25-Nov 15:39")
        self.assertEqual(panel.trade_time({}), "")


if __name__ == "__main__":
    unittest.main()
