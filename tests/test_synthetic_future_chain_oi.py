import unittest
from datetime import date

from Option_chain import synthetic_future_cum_oi as oi


class FakeClient:
    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    def get_expiry(self, exch, symbol):
        return {"Expiry": [{"ExpiryDate": "/Date(1796126400000+0530)/"}]}

    def get_option_chain(self, exch, symbol, ts):
        self.calls += 1
        return {"Options": self.rows}


class ChainOiTests(unittest.TestCase):
    def setUp(self):
        oi._CHAIN_CACHE.clear()
        oi._EXPIRY_TS.clear()

    def test_fills_missing_oi_from_chain(self):
        rows = [{"StrikeRate": 26000, "CPType": "CE", "OpenInterest": 500},
                {"StrikeRate": 26000, "CPType": "PE", "OpenInterest": 700}]
        client = FakeClient(rows)
        chain = [{"strike": 26000, "ce": {"oi": None}, "pe": {"oi": None}}]
        diag = oi.fill_missing_oi(client, chain, date(2026, 12, 1))
        self.assertEqual(diag, "")
        self.assertEqual((chain[0]["ce"]["oi"], chain[0]["pe"]["oi"]), (500, 700))

    def test_reports_fields_when_chain_has_no_oi(self):
        client = FakeClient([{"StrikeRate": 26000, "CPType": "CE", "LastRate": 1}])
        chain = [{"strike": 26000, "ce": {"oi": None}, "pe": {"oi": None}}]
        diag = oi.fill_missing_oi(client, chain, date(2026, 12, 1))
        self.assertIn("fields", diag)
        self.assertIsNone(chain[0]["ce"]["oi"])


if __name__ == "__main__":
    unittest.main()
