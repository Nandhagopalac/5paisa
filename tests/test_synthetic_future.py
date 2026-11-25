import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from Option_chain import synthetic_future as sf


class FakeClient:
    """Quotes: spot 25230, CE/PE prices from a tiny model."""
    def __init__(self, spot=25230.0):
        self.spot = spot

    def fetch_market_feed_scrip(self, requests):
        data = []
        for r in requests:
            code = r["ScripCode"]
            if code == 999920000:
                price = self.spot
            else:
                strike, kind = divmod(code, 10)
                strike *= 1
                price = (max(self.spot - strike, 0) if kind == 1 else max(strike - self.spot, 0)) + 40
            data.append({"Token": code, "LastRate": price})
        return {"Data": data}


def make_contracts(expiry=date(2026, 12, 1)):
    rows = []
    for strike in range(25000, 25500, 50):
        rows.append((expiry, float(strike), "CE", strike * 10 + 1))
        rows.append((expiry, float(strike), "PE", strike * 10 + 2))
    return pd.DataFrame(rows, columns=["Expiry", "Strike", "Type", "ScripCode"])


class CalculationTests(unittest.TestCase):
    def test_atm_strike_rounds_to_nearest_50(self):
        self.assertEqual(sf.atm_strike(25224), 25200)
        self.assertEqual(sf.atm_strike(25226), 25250)

    def test_synthetic_future_both_directions(self):
        self.assertEqual(sf.synthetic_future(25200, 150, 120), 25230)  # CE leads: strike + diff
        self.assertEqual(sf.synthetic_future(25200, 100, 130), 25170)  # PE leads: strike - diff

    def test_intrinsic_and_extrinsic(self):
        v = sf.leg_values(25230, 25200, 70, 40)
        self.assertEqual(v["ce_intrinsic"], 30)
        self.assertEqual(v["ce_extrinsic"], 40)
        self.assertEqual(v["pe_intrinsic"], 0)
        self.assertEqual(v["pe_extrinsic"], 40)
        self.assertEqual(v["straddle"], 110)
        self.assertEqual(v["total_extrinsic"], 80)

    def test_expiries_and_codes(self):
        contracts = make_contracts()
        self.assertEqual(sf.upcoming_expiries(contracts, date(2026, 12, 1)), [date(2026, 12, 1)])
        self.assertEqual(sf.upcoming_expiries(contracts, date(2026, 12, 2)), [])
        self.assertEqual(sf.option_codes(contracts, date(2026, 12, 1), 25200), (252001, 252002))
        self.assertIsNone(sf.option_codes(contracts, date(2026, 12, 1), 99999))


class ReadingTests(unittest.TestCase):
    def test_reading_follows_atm_and_computes_synthetic(self):
        r = sf.take_reading(FakeClient(25230.0), make_contracts(), date(2026, 12, 1),
                            now=datetime(2026, 12, 1, 10, 0))
        self.assertEqual(r["atm"], 25250)
        self.assertEqual(r["strike"], 25250)
        # CE 25250 = 0 + 40, PE = 20 + 40 -> synthetic = 25250 + 40 - 60
        self.assertAlmostEqual(r["synthetic"], 25230.0)
        self.assertAlmostEqual(r["basis"], 0.0)

    def test_fixed_strike_is_monitored_separately_from_atm(self):
        r = sf.take_reading(FakeClient(25230.0), make_contracts(), date(2026, 12, 1),
                            mode="FIXED", fixed_strike=25100, now=datetime(2026, 12, 1, 10, 0))
        self.assertEqual(r["atm"], 25250)
        self.assertEqual(r["strike"], 25100)
        self.assertEqual(r["ce_intrinsic"], 130)

    def test_missing_contracts_gives_clear_error(self):
        with self.assertRaises(RuntimeError):
            sf.take_reading(FakeClient(26000.0), make_contracts(), date(2026, 12, 1))


class HistoryTests(unittest.TestCase):
    def reading(self, when, strike=25200, mode="ATM"):
        r = sf.take_reading(FakeClient(), make_contracts(), date(2026, 12, 1), now=when)
        r.update(recorded_at=when.isoformat(sep=" "), strike=strike, mode=mode)
        return r

    def test_one_row_per_five_minute_slot_and_market_hours_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "h.csv"
            self.assertTrue(sf.record_reading(self.reading(datetime(2026, 12, 1, 9, 15, 3)), path))
            self.assertFalse(sf.record_reading(self.reading(datetime(2026, 12, 1, 9, 19, 59)), path))
            self.assertTrue(sf.record_reading(self.reading(datetime(2026, 12, 1, 9, 20, 1)), path))
            self.assertFalse(sf.record_reading(self.reading(datetime(2026, 12, 1, 9, 10)), path))   # pre-open
            self.assertFalse(sf.record_reading(self.reading(datetime(2026, 12, 1, 15, 45)), path))  # after close
            self.assertTrue(sf.record_reading(self.reading(datetime(2026, 12, 1, 15, 30)), path))
            self.assertFalse(sf.record_reading(self.reading(datetime(2026, 12, 5, 10, 0)), path))   # Saturday
            self.assertEqual(len(sf.load_history(path)), 3)

    def test_other_strike_in_same_slot_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "h.csv"
            when = datetime(2026, 12, 1, 10, 0)
            self.assertTrue(sf.record_reading(self.reading(when, 25200), path))
            self.assertTrue(sf.record_reading(self.reading(when, 25250), path))
            self.assertFalse(sf.record_reading(self.reading(when, 25250), path))

    def test_empty_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(sf.load_history(Path(tmp) / "none.csv").empty)


if __name__ == "__main__":
    unittest.main()
