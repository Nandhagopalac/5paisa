import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from Option_chain import synthetic_future_cum_intrinsic as ci
from Option_chain.synthetic_future import INDIA_TIME


def at(h, m, s, day=27):
    return datetime(2026, 11, day, h, m, s, tzinfo=INDIA_TIME)


class CumTests(unittest.TestCase):
    def setUp(self):
        ci._state.clear()
        self.tmp = tempfile.TemporaryDirectory()
        ci.STATE_DIR = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_adds_each_second_on_top(self):
        ci.add_second(at(9, 15, 0), 23, 0)
        state = ci.add_second(at(9, 15, 1), 2, 0)
        self.assertEqual(state["ce"], 25)
        self.assertEqual(state["count"], 2)

    def test_same_second_counted_once(self):
        ci.add_second(at(9, 15, 0), 23, 0)
        state = ci.add_second(at(9, 15, 0), 23, 0)
        self.assertEqual(state["ce"], 23)

    def test_outside_market_hours_not_added(self):
        self.assertEqual(ci.add_second(at(16, 0, 0), 5, 5)["count"], 0)

    def test_new_day_resets_and_restart_resumes(self):
        ci.add_second(at(9, 15, 0), 10, 4)
        ci._state.clear()                       # simulate restart: file is read back
        self.assertEqual(ci.add_second(at(9, 15, 1), 1, 1)["ce"], 11)
        self.assertEqual(ci.add_second(at(9, 15, 1, day=30), 3, 0)["ce"], 3)


if __name__ == "__main__":
    unittest.main()


class SignalTests(unittest.TestCase):
    def setUp(self):
        ci._state.clear()
        self.tmp = tempfile.TemporaryDirectory()
        ci.STATE_DIR = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_signal_rule(self):
        window = [5.0] * 9 + [10.0]
        self.assertEqual(ci.signal(window, 11), "BUY")
        self.assertEqual(ci.signal(window, 10), "NO BUY")       # equal to the highest: no buy
        self.assertEqual(ci.signal(window[:9], 99), "NO BUY")  # window not full yet
        self.assertEqual(ci.signal(window, None), "NO BUY")

    def test_needs_to_beat_all_last_20_not_just_the_last(self):
        values = [10] * 10 + [3, 8]   # 8 beats the previous entry (3) but not the 10s
        for i, v in enumerate(values):
            s = ci.add_second(at(9, 15, i), v, 0)
        self.assertEqual(s["sig_ce"], "NO BUY")
        s = ci.add_second(at(9, 16, 0), 11, 0)
        self.assertEqual(s["sig_ce"], "BUY")

    def test_window_restored_after_restart(self):
        for i in range(11):
            ci.add_second(at(9, 15, i), 5, 0, extra={})
        ci._state.clear()
        s = ci.add_second(at(9, 16, 0), 6, 0, extra={})
        self.assertEqual(s["sig_ce"], "BUY")


class ZeroSkipTests(unittest.TestCase):
    def setUp(self):
        ci._state.clear()
        self.tmp = tempfile.TemporaryDirectory()
        ci.STATE_DIR = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_zeros_never_signal_and_are_skipped(self):
        self.assertEqual(ci.signal([1.0] * 10, 0), "NO BUY")
        n = 0
        for v in [1, 2, 2, 2, 2, 2, 2, 2, 2, 2]:   # 10 non-zero entries fill the window
            ci.add_second(at(9, 15, n), v, 0)
            n += 1
        for _ in range(15):                          # a long run of zeros changes nothing
            s = ci.add_second(at(9, 15, n), 0, 0)
            n += 1
            self.assertEqual(s["sig_ce"], "NO BUY")
        self.assertEqual(len(s["win_ce"]), 10)
        s = ci.add_second(at(9, 15, n), 3, 0)
        self.assertEqual(s["sig_ce"], "BUY")
