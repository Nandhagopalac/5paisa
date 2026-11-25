import unittest
from datetime import date

import pandas as pd

from Option_chain import synthetic_future_oi as oi


class OIClient:
    def fetch_market_feed_scrip(self, requests):
        data = []
        for request in requests:
            code = request["ScripCode"]
            if code == 999920000:
                data.append({"Token": code, "LastRate": 25230})
                continue
            strike, side = divmod(code, 10)
            current_oi = strike * 10 + side
            data.append({
                "Token": code,
                "OpenInterest": current_oi,
                "ChangeInOI": 3 if side == 1 else 7,
            })
        return {"Data": data}


def make_contracts():
    expiry = date(2026, 12, 1)
    rows = []
    for strike in range(24800, 25900, 50):
        rows.extend([
            (expiry, float(strike), "CE", strike * 10 + 1),
            (expiry, float(strike), "PE", strike * 10 + 2),
        ])
    return pd.DataFrame(rows, columns=["Expiry", "Strike", "Type", "ScripCode"])


class SyntheticFutureOITests(unittest.TestCase):
    def test_change_in_oi_falls_back_to_current_minus_previous_oi(self):
        self.assertEqual(oi._oi_values({"OpenInterest": 120, "Prev_OI": 90}), (120, 30))

    def test_snapshot_covers_five_strikes_each_side_and_atm(self):
        snapshot = oi.take_oi_snapshot(
            OIClient(), make_contracts(), date(2026, 12, 1)
        )

        self.assertEqual(snapshot["atm"], 25250)
        self.assertEqual(
            [row["strike"] for row in snapshot["rows"]],
            list(range(25000, 25501, 50)),
        )
        self.assertEqual(sum(row["is_atm"] for row in snapshot["rows"]), 1)
        self.assertTrue(all(row["ce_oi"] is not None for row in snapshot["rows"]))

    def test_totals_compare_cumulative_put_and_call_oi_changes(self):
        snapshot = oi.take_oi_snapshot(
            OIClient(), make_contracts(), date(2026, 12, 1)
        )

        totals = oi.oi_totals(snapshot["rows"])

        self.assertEqual(totals["ce_change"], 33)
        self.assertEqual(totals["pe_change"], 77)
        self.assertGreater(totals["pe_oi"], totals["ce_oi"])

    def test_totals_are_withheld_when_any_strike_is_missing(self):
        rows = [{"ce_oi": 100, "ce_change": 2, "pe_change": 3, "pe_oi": 200}]
        rows.append({"ce_oi": None, "ce_change": None, "pe_change": 1, "pe_oi": 200})

        totals = oi.oi_totals(rows)

        self.assertIsNone(totals["ce_oi"])
        self.assertIsNone(totals["ce_change"])
        self.assertEqual(totals["pe_oi"], 400)


if __name__ == "__main__":
    unittest.main()
