import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from Option_chain import synthetic_future_cum_oi as oi
from Option_chain import synthetic_future_panel as panel
from tests.test_synthetic_future import make_contracts
from tests.test_synthetic_future_panel import FUTURES, PanelClient


class OiClient(PanelClient):
    """CE OI = 1000 per strike step above 24800; PE OI = 5000; adds `bump` to every CE."""
    bump = 0

    def fetch_market_feed_scrip(self, requests):
        data = super().fetch_market_feed_scrip(requests)["Data"]
        for tick in data:
            code = tick["Token"]
            if code == 999920000 or code == self.FUTURE_CODE:
                continue
            strike, kind = divmod(code, 10)
            tick["OpenInterest"] = (1000 * (strike - 24800) // 50 + self.bump) if kind == 1 else 5000
        return {"Data": data}


def snapshot(client=None, spot=25367.5):
    return panel.take_panel(client or OiClient(spot), make_contracts(), FUTURES, date(2026, 12, 1))


class OiTests(unittest.TestCase):
    def test_oi_field_aliases(self):
        self.assertEqual(oi.oi_from_tick({"OpenInterest": "1500"}), 1500.0)
        self.assertEqual(oi.oi_from_tick({"OI": 20}), 20.0)
        self.assertIsNone(oi.oi_from_tick({"LastRate": 5}))

    def test_cumulative_oi_covers_atm_and_three_strikes_each_side(self):
        d = snapshot()
        s = d["oi"]
        self.assertTrue(s["available"])
        self.assertEqual(s["strikes"], [25200, 25250, 25300, 25350, 25400, 25450, 25500])
        self.assertEqual(s["pe"], 7 * 5000)
        self.assertEqual(s["ce"], sum(1000 * (k - 24800) // 50 for k in s["strikes"]))

    def test_bias_rule(self):
        self.assertIn("UP", oi.bias(100, 200)[0])
        self.assertIn("DOWN", oi.bias(300, 200)[0])
        self.assertIn("neutral", oi.bias(5, 5)[0])

    def test_missing_oi_is_reported_not_crashed(self):
        d = panel.take_panel(PanelClient(25367.5), make_contracts(), FUTURES, date(2026, 12, 1))
        self.assertFalse(d["oi"]["available"])
        self.assertIn("OI not in the quote feed", panel.panel_html(d))

    def test_table_shows_cumulative_rows(self):
        text = panel.panel_html(snapshot())
        for needle in ("Cumulative OI CE", "Cumulative OI PE", "PE − CE OI", "25200–25500"):
            self.assertIn(needle, text)

    def test_snapshot_once_per_slot_and_live_change_on_same_strikes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "oi.csv"
            first = snapshot()
            self.assertTrue(oi.record_snapshot(first["oi"]["oi_map"], date(2026, 12, 1), datetime(2026, 12, 1, 9, 16), path))
            self.assertFalse(oi.record_snapshot(first["oi"]["oi_map"], date(2026, 12, 1), datetime(2026, 12, 1, 9, 19), path))
            self.assertFalse(oi.record_snapshot(first["oi"]["oi_map"], date(2026, 12, 1), datetime(2026, 12, 1, 16, 0), path))
            client = OiClient(25367.5)
            client.bump = 300                              # every CE grows by 300
            later = snapshot(client)
            frame = oi.load_snapshots(date(2026, 12, 1), path)
            moved = oi.changes(later["oi"], frame, datetime(2026, 12, 1, 9, 22))
            self.assertEqual(moved["prev"], (7 * 300, 0))
            self.assertEqual(moved["open"], (7 * 300, 0))
            self.assertIsNone(oi.changes(later["oi"], frame, datetime(2026, 12, 1, 9, 17))["prev"])  # same slot

    def test_moving_atm_does_not_fake_a_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "oi.csv"
            first = snapshot(spot=25367.5)
            oi.record_snapshot(first["oi"]["oi_map"], date(2026, 12, 1), datetime(2026, 12, 1, 9, 16), path)
            moved_atm = snapshot(spot=25417.0)             # ATM 25400: different window, same OI per strike
            frame = oi.load_snapshots(date(2026, 12, 1), path)
            delta = oi.changes(moved_atm["oi"], frame, datetime(2026, 12, 1, 9, 22))
            self.assertEqual(delta["prev"], (0, 0))


class UpdateTrackerTests(unittest.TestCase):
    def test_tracks_when_oi_changes_and_typical_gap(self):
        state, base = {}, datetime(2026, 12, 1, 10, 0, 0)

        def at(seconds, bump):
            client = OiClient(25367.5)
            client.bump = bump
            return oi.track_updates(state, snapshot(client)["oi"], base.replace(second=0) + __import__("datetime").timedelta(seconds=seconds))
        self.assertIn("waiting", at(0, 0))
        self.assertIn("waiting", at(5, 0))                 # unchanged
        self.assertIn("10:00:10", at(10, 100))             # first change
        for t, b in ((40, 200), (70, 300), (100, 400)):    # changes every 30 s
            text = at(t, b)
        self.assertIn("typically every 30s", text)


if __name__ == "__main__":
    unittest.main()
