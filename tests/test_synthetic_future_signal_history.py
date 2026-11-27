import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from Option_chain import synthetic_future_cum_intrinsic as ci
from Option_chain import synthetic_future_signal_history as sh
from Option_chain.synthetic_future import INDIA_TIME


def at(s):
    return datetime(2026, 11, 27, 9, 15, s, tzinfo=INDIA_TIME)


class SignalHistoryTests(unittest.TestCase):
    def setUp(self):
        ci._state.clear()
        self.tmp = tempfile.TemporaryDirectory()
        ci.STATE_DIR = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_log_and_counts(self):
        extra = {"spot": 25700.5, "strike": 25700, "ce": 150, "pe": 160}
        for sec, (ce, pe) in enumerate([(10, 0), (15, 0), (12, 3), (20, 4)]):
            ci.add_second(at(sec), ce, pe, extra=extra)
        frame = sh.load_log("2026-11-27")
        self.assertEqual(len(frame), 4)
        summary = sh.summarize(frame)
        self.assertEqual((summary["ce_buys"], summary["pe_buys"], summary["both"]), (2, 2, 1))
        self.assertEqual(float(frame["cum_ce"].iloc[-1]), 57.0)
        self.assertEqual(sh.available_days(), ["2026-11-27"])
        self.assertIn("BUY", sh._table(frame))

    def test_empty(self):
        self.assertEqual(sh.summarize(sh.load_log("2026-01-01"))["seconds"], 0)


if __name__ == "__main__":
    unittest.main()
