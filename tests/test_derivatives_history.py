import tempfile
import unittest
from datetime import datetime
from pathlib import Path
import pandas as pd

from Option_chain.derivatives_history import INDIA_TIME, load_history, record_sample
from Option_chain.derivatives_history_view import bar_chart, line_chart


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

    def test_charts_survive_all_zero_values(self):
        frame = pd.DataFrame({
            "Time": pd.to_datetime(["2026-11-26 09:10:00"]),
            "CE": [0],
            "PE": [0],
            "Lead": [0],
        })

        self.assertIn("<svg", line_chart(frame, "CE vs PE volume"))
        self.assertIn("<svg", bar_chart(frame, ["Lead"], "Who leads"))


class EmptyReadingTests(unittest.TestCase):
    def test_zero_readings_are_not_saved_and_old_ones_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "h.csv"
            when = datetime(2026, 11, 26, 9, 14, tzinfo=INDIA_TIME)
            self.assertFalse(record_sample({"Call": 0, "Put": 0}, {"Call": 0, "Put": 0}, "t", {}, path, when))
            path.write_text("recorded_at,nse_timestamp,ce,pe,ce_rows,pe_rows,market_status\n"
                            "2026-11-26 09:14:00,t,0,0,0,0,\n"
                            "2026-11-26 09:30:00,u,500,400,5,5,\n")
            self.assertEqual(len(load_history(path)), 1)

    def test_chart_with_one_flat_value_does_not_divide_by_zero(self):
        import pandas as pd
        from Option_chain.derivatives_history_view import bar_chart, line_chart
        frame = pd.DataFrame({"Time": [datetime(2026, 11, 26, 9, 14)], "CE": [0], "PE": [0],
                              "Lead": [0], "CE added": [None], "PE added": [None]})
        self.assertIn("<svg", line_chart(frame, "x"))
        self.assertIn("<svg", bar_chart(frame, ["Lead"], "x"))


if __name__ == "__main__":
    unittest.main()
