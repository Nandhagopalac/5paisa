import tempfile
import time
import unittest
from datetime import date, datetime
from pathlib import Path

from Option_chain.synthetic_future import INDIA_TIME
from Rulebased_trading import rules, snapshot, trader


def rows(*pairs, start=36000):
    """Signal rows one second apart ending at start+len-1 (pairs = (ce, pe))."""
    out = []
    for i, (ce, pe) in enumerate(pairs):
        t = start + i
        out.append({"time": f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}", "spot": "25607.2",
                    "ce_signal": ce, "pe_signal": pe})
    return out


def snap(net=0.2, up=20, pcts=(0.5, 0.3, 0.1, -0.2, -0.4)):
    return {"net_impact": net, "gainers": up, "losers": 50 - up,
            "top5": [{"sym": f"S{i}", "pct": p, "imp": 0.0} for i, p in enumerate(pcts)]}


class StreakTests(unittest.TestCase):
    def test_three_in_a_row(self):
        r = rows(("NO BUY", "NO BUY"), ("BUY", "NO BUY"), ("BUY", "NO BUY"), ("BUY", "NO BUY"))
        now = 36003
        self.assertEqual(rules.streak(r, "CE", now), 3)
        self.assertEqual(rules.streak(r, "PE", now), 0)
        self.assertEqual(rules.candidate_side(r, now), "CE")

    def test_two_is_not_enough_and_a_break_resets(self):
        r = rows(("BUY", "NO BUY"), ("BUY", "NO BUY"), ("NO BUY", "NO BUY"), ("BUY", "NO BUY"), ("BUY", "NO BUY"))
        self.assertLess(rules.streak(r, "CE", 36004), 3)

    def test_stale_or_gapped_rows_do_not_count(self):
        r = rows(("BUY", "NO BUY"), ("BUY", "NO BUY"), ("BUY", "NO BUY"))
        self.assertEqual(rules.streak(r, "CE", 36002 + 30), 0)           # dashboard stopped
        r[1]["time"] = "10:00:10"                                          # gap in the seconds
        self.assertLess(rules.streak(r, "CE", 36002), 3)

    def test_both_legs_is_ambiguous(self):
        r = rows(("BUY", "BUY"), ("BUY", "BUY"), ("BUY", "BUY"))
        self.assertIsNone(rules.candidate_side(r, 36002))


class StrikeTests(unittest.TestCase):
    def test_itm_is_first_strike_inside(self):
        self.assertEqual(rules.itm_strike(25607.2, "CE"), 25600)
        self.assertEqual(rules.itm_strike(25607.2, "PE"), 25650)
        self.assertEqual(rules.itm_strike(25600, "CE"), 25550)    # exactly on a strike: one step inside
        self.assertEqual(rules.itm_strike(25600, "PE"), 25650)
        self.assertEqual(rules.itm_strike(25607.2, "CE", steps=2), 25550)


class RuleTests(unittest.TestCase):
    def ok(self, checks):
        return all(c.ok for c in checks)

    def test_ce_needs_everything(self):
        r = rows(("BUY", "NO BUY"), ("BUY", "NO BUY"), ("BUY", "NO BUY"))
        self.assertTrue(self.ok(rules.evaluate("CE", r, snap(), 36002)))
        self.assertFalse(self.ok(rules.evaluate("CE", r, snap(net=-0.1), 36002)))              # impact negative
        self.assertFalse(self.ok(rules.evaluate("CE", r, snap(up=15), 36002)))                 # needs MORE than 15
        self.assertFalse(self.ok(rules.evaluate("CE", r, snap(pcts=(0.5, -0.3, 0.1, 0, 0)), 36002)))  # top3 not all +
        self.assertFalse(self.ok(rules.evaluate("CE", r, None, 36002)))                        # no live data

    def test_pe_mirror(self):
        r = rows(("NO BUY", "BUY"), ("NO BUY", "BUY"), ("NO BUY", "BUY"))
        bearish = snap(net=-0.3, up=10, pcts=(-0.5, -0.3, -0.1, 0.2, 0.4))
        self.assertTrue(self.ok(rules.evaluate("PE", r, bearish, 36002)))
        self.assertFalse(self.ok(rules.evaluate("PE", r, snap(net=-0.3, up=16, pcts=(-1, -1, -1, 0, 0)), 36002)))


class PlumbingTests(unittest.TestCase):
    def test_snapshot_age(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "s.json"
            snapshot.write_snapshot({"ts": time.time(), "x": 1}, path)
            self.assertEqual(snapshot.read_snapshot(path)[0]["x"], 1)
            self.assertIsNone(snapshot.read_snapshot(path, now=time.time() + 60)[0])
            self.assertIsNone(snapshot.read_snapshot(Path(folder) / "missing.json")[0])

    def test_order_command_is_dry_unless_live(self):
        paper = trader.order_command(12345)
        live = trader.order_command(12345, live=True)
        self.assertNotIn("--confirm", paper)
        self.assertIn("--confirm", live)
        self.assertEqual(live[live.index("--qty") + 1], "65")
        self.assertEqual(live[live.index("--side") + 1], "B")
        self.assertEqual(live[live.index("--exchtype") + 1], "D")

    def test_reads_signal_tail(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "nifty_intrinsic_signals_2026-11-27.csv").write_text(
                ",".join(trader.SIGNAL_COLUMNS) + "\n"
                + "\n".join(f"10:00:0{i},25600,25600,1,1,0,0,BUY,NO BUY,1,1" for i in range(5)) + "\n")
            got = trader.read_signal_rows("2026-11-27", count=3, directory=folder)
            self.assertEqual([r["time"] for r in got], ["10:00:02", "10:00:03", "10:00:04"])

    def test_entry_window(self):
        tue = datetime(2026, 12, 1, 10, 0, tzinfo=INDIA_TIME)
        self.assertTrue(trader.entry_allowed_now(tue, "15:15")[0])
        self.assertFalse(trader.entry_allowed_now(tue.replace(hour=15, minute=20), "15:15")[0])
        self.assertFalse(trader.entry_allowed_now(tue.replace(day=28, month=11), "15:15")[0])  # Saturday


if __name__ == "__main__":
    unittest.main()
