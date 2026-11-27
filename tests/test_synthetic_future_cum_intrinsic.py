import unittest
import pandas as pd
from datetime import date
from Option_chain import synthetic_future_cum_intrinsic as ci


class CumTests(unittest.TestCase):
    def test_sum_and_live(self):
        h = pd.DataFrame({"Time": pd.to_datetime(["2026-11-27 11:30", "2026-11-27 11:35", "2026-11-26 11:35"]),
                          "mode": ["ATM"] * 3, "ce_intrinsic": [0, 10.0, 99], "pe_intrinsic": [34.2, 0, 99]})
        r = ci.today_readings(h, date(2026, 11, 27))
        self.assertEqual(len(r), 2)
        t = ci.cumulative(r, live=(0, 22.25))
        self.assertAlmostEqual(t["ce"], 10.0)
        self.assertAlmostEqual(t["pe"], 56.45)
        self.assertEqual(t["count"], 3)

    def test_empty(self):
        self.assertEqual(ci.cumulative(ci.today_readings(pd.DataFrame(), date.today()))["count"], 0)


if __name__ == "__main__":
    unittest.main()
