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

    def test_buy_when_rising_else_no_buy(self):
        ci.add_second(at(9, 15, 0), 10, 5)
        s = ci.add_second(at(9, 15, 1), 15, 3)
        self.assertEqual(ci.signal(s["prev_ce"], s["cur_ce"]), "BUY")
        self.assertEqual(ci.signal(s["prev_pe"], s["cur_pe"]), "NO BUY")
        self.assertEqual(ci.signal(10, 10), "NO BUY")
        self.assertEqual(ci.signal(None, 4), "NO BUY")
