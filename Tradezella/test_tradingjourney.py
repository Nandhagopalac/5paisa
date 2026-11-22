import tempfile
import unittest
from datetime import date
from io import BytesIO
from pathlib import Path

from PIL import Image

from Tradezella.tradingjourney import (
    add_rule,
    calculate_trade_pnl,
    create_strategy,
    delete_rule,
    get_rule_stats,
    get_strategies,
    get_strategy_overview,
    rename_rule,
    set_strategy_archived,
    delete_trade,
    default_lot_size,
    get_journal,
    get_month_activity,
    get_trade_screenshots,
    get_screenshots,
    get_trades,
    initialize_storage,
    save_journal,
    save_screenshot,
    save_trade_journal,
    save_trade_screenshot,
    save_trade,
    update_trade,
)


class TradingJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name) / "data"
        initialize_storage(self.data_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_updating_journal_preserves_trades_and_checklist(self):
        trade_date = date(2026, 11, 22)
        save_journal(
            trade_date,
            plan="Opening plan",
            rules_checked=["1:1:1"],
            data_dir=self.data_dir,
        )
        save_trade(
            trade_date,
            "NIFTY",
            "CE",
            lots=1,
            buy_price=100,
            sell_price=102,
            data_dir=self.data_dir,
        )

        save_journal(
            trade_date,
            plan="Updated plan",
            rules_checked=["Risk limit"],
            data_dir=self.data_dir,
        )

        journal = get_journal(trade_date, self.data_dir)
        trade = get_trades(trade_date, self.data_dir)[0]
        self.assertEqual(journal["plan"], "Updated plan")
        self.assertEqual(journal["rules_checked"], ["Risk limit"])
        self.assertEqual(trade["instrument"], "NIFTY")
        self.assertEqual(trade["option_type"], "CE")
        self.assertEqual(trade["lots"], 1)
        self.assertEqual(trade["lot_size"], 65)
        self.assertEqual(trade["quantity"], 65)
        self.assertEqual(trade["pnl"], 130)

        update_trade(
            trade_date,
            trade["id"],
            "BANK NIFTY",
            "PE",
            lots=2,
            buy_price=100,
            sell_price=90,
            notes="Updated result",
            data_dir=self.data_dir,
        )
        updated_trade = get_trades(trade_date, self.data_dir)[0]
        self.assertEqual(updated_trade["lot_size"], 30)
        self.assertEqual(updated_trade["quantity"], 60)
        self.assertEqual(updated_trade["pnl"], -600)
        self.assertEqual(updated_trade["notes"], "Updated result")
        self.assertTrue((self.data_dir / "journals" / "2026-11-22.json").is_file())

    def test_trade_profit_and_loss_use_buy_sell_prices_and_quantity(self):
        self.assertEqual(calculate_trade_pnl(50, 100, 105), 250)
        self.assertEqual(calculate_trade_pnl(50, 105, 100), -250)
        self.assertIsNone(calculate_trade_pnl(50, 100, None))
        self.assertEqual(default_lot_size("NIFTY 50"), 65)
        self.assertEqual(default_lot_size("BANK NIFTY"), 30)
        self.assertEqual(default_lot_size("RELIANCE"), 1)
        with self.assertRaises(ValueError):
            save_trade(
                date(2026, 11, 22),
                "NIFTY",
                "PE",
                lots=1,
                buy_price=100,
                sell_price=None,
                data_dir=self.data_dir,
            )

    def test_default_strategy_has_the_three_rule_groups(self):
        strategy = get_strategies(self.data_dir)[0]
        self.assertEqual(strategy["name"], "Trendline break reversal")
        self.assertEqual(len(strategy["rules"]["entry"]), 5)
        self.assertEqual(len(strategy["rules"]["market"]), 1)
        self.assertEqual(len(strategy["rules"]["exit"]), 1)

    def test_strategy_and_rule_editing(self):
        sid = create_strategy("Break & retest", self.data_dir)
        with self.assertRaises(ValueError):
            create_strategy("break & RETEST", self.data_dir)
        rule_id = add_rule(sid, "entry", " Wait for the retest ", self.data_dir)
        rename_rule(sid, rule_id, "Wait for a clean retest", self.data_dir)
        strategy = next(x for x in get_strategies(self.data_dir) if x["id"] == sid)
        self.assertEqual(strategy["rules"]["entry"][0]["text"], "Wait for a clean retest")
        with self.assertRaises(ValueError):
            add_rule(sid, "entry", "  ", self.data_dir)
        with self.assertRaises(ValueError):
            rename_rule(sid, rule_id, "", self.data_dir)
        delete_rule(sid, rule_id, self.data_dir)
        strategy = next(x for x in get_strategies(self.data_dir) if x["id"] == sid)
        self.assertEqual(strategy["rules"]["entry"], [])

    def test_last_active_strategy_cannot_be_archived(self):
        first = get_strategies(self.data_dir)[0]["id"]
        with self.assertRaises(ValueError):
            set_strategy_archived(first, True, self.data_dir)
        second = create_strategy("Second", self.data_dir)
        set_strategy_archived(second, True, self.data_dir)
        self.assertEqual(len(get_strategies(self.data_dir)), 1)
        self.assertEqual(len(get_strategies(self.data_dir, include_archived=True)), 2)

    def test_screenshot_is_saved_under_local_data_directory(self):
        buffer = BytesIO()
        Image.new("RGB", (2, 2), color="blue").save(buffer, format="PNG")

        save_screenshot(
            date(2026, 11, 22),
            "chart.png",
            buffer.getvalue(),
            self.data_dir,
        )

        screenshots = get_screenshots(date(2026, 11, 22), self.data_dir)
        self.assertEqual(len(screenshots), 1)
        self.assertEqual(screenshots[0]["original_name"], "chart.png")
        self.assertTrue(screenshots[0]["path"].is_file())

    def test_month_activity_uses_daily_result_or_complete_trade_results(self):
        save_journal(date(2026, 11, 6), pnl=-932.1, data_dir=self.data_dir)
        save_trade(
            date(2026, 11, 6), "NIFTY", "PE", 1, 100, 82,
            data_dir=self.data_dir,
        )
        save_trade(
            date(2026, 11, 9), "NIFTY", "CE", 2, 100, 105,
            data_dir=self.data_dir,
        )
        save_trade(
            date(2026, 11, 10), "BANKNIFTY", "PE", 2, 100, 90,
            data_dir=self.data_dir,
        )

        activity = get_month_activity(2026, 11, self.data_dir)

        self.assertEqual(activity["2026-11-06"], {"pnl": -932.1, "trade_count": 1})
        self.assertEqual(activity["2026-11-09"], {"pnl": 650, "trade_count": 1})
        self.assertEqual(activity["2026-11-10"], {"pnl": -600, "trade_count": 1})


    def test_trade_journal_survives_trade_edit_and_counts_rules(self):
        d = date(2026, 11, 22)
        tid = save_trade(d, "NIFTY", "CE", 6, 480, 510, data_dir=self.data_dir)
        strategy = get_strategies(self.data_dir)[0]
        every_rule = [r["id"] for rules in strategy["rules"].values() for r in rules]
        save_trade_journal(d, tid, mood_before="Calm", thinking="Waited for retest",
                           rules_followed=every_rule, data_dir=self.data_dir)
        update_trade(d, tid, "NIFTY", "CE", 6, 480, 520, "edited", data_dir=self.data_dir)
        trade = get_trades(d, self.data_dir)[0]
        self.assertEqual(trade["journal"]["thinking"], "Waited for retest")
        self.assertEqual(trade["pnl"], 15600.0)
        stats = get_rule_stats(strategy["id"], 2026, 11, self.data_dir)
        self.assertTrue(all(r["follow_rate"] == 100 for g in stats for r in g["rules"]))

    def test_trade_screenshot_saved_on_the_trade(self):
        d = date(2026, 11, 22)
        tid = save_trade(d, "BANKNIFTY", "PE", 4, 700, 680, data_dir=self.data_dir)
        buffer = BytesIO()
        Image.new("RGB", (4, 4)).save(buffer, format="PNG")
        save_trade_screenshot(d, tid, "chart.png", buffer.getvalue(), data_dir=self.data_dir)
        shots = get_trade_screenshots(get_trades(d, self.data_dir)[0], self.data_dir)
        self.assertEqual(len(shots), 1)
        self.assertTrue(shots[0]["path"].is_file())
        with self.assertRaises(ValueError):
            save_trade_screenshot(d, "missing", "x.png", buffer.getvalue(), data_dir=self.data_dir)


    def test_delete_trade_removes_trade_and_its_screenshots(self):
        d = date(2026, 11, 22)
        keep = save_trade(d, "NIFTY", "CE", 1, 100, 110, data_dir=self.data_dir)
        gone = save_trade(d, "BANKNIFTY", "PE", 1, 100, 90, data_dir=self.data_dir)
        buffer = BytesIO()
        Image.new("RGB", (4, 4)).save(buffer, format="PNG")
        save_trade_screenshot(d, gone, "a.png", buffer.getvalue(), data_dir=self.data_dir)
        save_trade_screenshot(d, keep, "b.png", buffer.getvalue(), data_dir=self.data_dir)
        trades = get_trades(d, self.data_dir)
        gone_file = get_trade_screenshots(trades[1], self.data_dir)[0]["path"]
        keep_file = get_trade_screenshots(trades[0], self.data_dir)[0]["path"]
        self.assertEqual(delete_trade(d, gone, data_dir=self.data_dir), 1)
        self.assertFalse(gone_file.exists())
        self.assertTrue(keep_file.exists())
        self.assertEqual([t["id"] for t in get_trades(d, self.data_dir)], [keep])
        with self.assertRaises(ValueError):
            delete_trade(d, gone, data_dir=self.data_dir)

    def test_strategy_overview_and_rule_stats(self):
        d = date(2026, 11, 22)
        first = get_strategies(self.data_dir)[0]
        other = create_strategy("Other", self.data_dir)
        win = save_trade(d, "NIFTY", "CE", 1, 100, 110, strategy_id=first["id"], data_dir=self.data_dir)
        loss = save_trade(d, "NIFTY", "PE", 1, 100, 90, strategy_id=first["id"], data_dir=self.data_dir)
        save_trade(d, "NIFTY", "PE", 1, 100, 120, strategy_id=other, data_dir=self.data_dir)
        old = save_trade(d, "NIFTY", "CE", 1, 100, 100, data_dir=self.data_dir)  # default strategy
        retest = first["rules"]["entry"][1]["id"]
        save_trade_journal(d, win, rules_followed=[retest], data_dir=self.data_dir)
        save_trade_journal(d, loss, rules_followed=[], data_dir=self.data_dir)

        overview = {r["name"]: r for r in get_strategy_overview(data_dir=self.data_dir)}
        mine = overview["Trendline break reversal"]
        self.assertEqual(mine["trades"], 3)
        self.assertAlmostEqual(mine["win_rate"], 100 / 3)
        self.assertEqual(overview["Other"]["net_pnl"], 20 * 65)
        self.assertEqual(get_strategy_overview(2026, 10, self.data_dir)[0]["trades"], 0)

        stats = get_rule_stats(first["id"], data_dir=self.data_dir)
        rule = next(r for g in stats for r in g["rules"] if r["id"] == retest)
        self.assertEqual((rule["journalled"], rule["followed"], rule["follow_rate"]), (2, 1, 50))
        self.assertEqual(rule["net_pnl"], 650)
        self.assertEqual(rule["profit_factor"], float("inf"))
        self.assertEqual(rule["win_rate"], 100)


if __name__ == "__main__":
    unittest.main()
