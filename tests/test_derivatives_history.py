import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from Option_chain.derivatives_history import INDIA_TIME, load_history, record_sample


def at(hour, minute, second=0):
    return datetime(2026, 11, 23, hour, minute, second, tzinfo=INDIA_TIME)


class DerivativesHistoryTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "history.csv"
        self.status = {"marketStatusMessage": "Normal Market is Open"}

    def save(self, ce, pe, stamp, now):
        return record_sample({"Call": ce, "Put": pe}, {"Call": 10, "Put": 10}, stamp,
                             self.status, path=self.path, now=now)

    def test_one_reading_per_ten_minute_slot(self):
        self.assertTrue(self.save(100, 80, "23-Nov-2026 09:50:00", at(9, 50, 5)))
        self.assertFalse(self.save(101, 81, "23-Nov-2026 09:55:00", at(9, 55)))
        self.assertTrue(self.save(150, 120, "23-Nov-2026 10:00:00", at(10, 0, 8)))
        self.assertEqual(len(load_history(self.path)), 2)

    def test_same_nse_timestamp_is_not_saved_twice(self):
        self.assertTrue(self.save(100, 80, "22-Nov-2026 15:30:00", at(15, 30)))
        self.assertFalse(self.save(100, 80, "22-Nov-2026 15:30:00", at(15, 40)))
        self.assertEqual(len(load_history(self.path)), 1)

    def test_history_table_has_lead_and_survives_restart(self):
        self.save(100, 130, "t1", at(9, 50))
        self.save(200, 150, "t2", at(10, 0))
        table = load_history(self.path)
        self.assertEqual(list(table["Lead"]), [-30, 50])
        self.assertEqual(table["Time"].iloc[0], datetime(2026, 11, 23, 9, 50))
        self.assertEqual(table["Status"].iloc[0], "Normal Market is Open")

    def test_empty_when_nothing_saved(self):
        self.assertTrue(load_history(self.path).empty)


if __name__ == "__main__":
    unittest.main()
