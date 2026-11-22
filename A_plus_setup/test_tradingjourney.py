import tempfile
import unittest
from datetime import date
from io import BytesIO
from pathlib import Path

from PIL import Image

from A_plus_setup.tradingjourney import (
    calculate_trade_pnl,
    default_lot_size,
    get_journal,
    get_month_activity,
    get_rules,
    get_screenshots,
    get_trades,
    initialize_storage,
    save_journal,
    save_rules,
    save_screenshot,
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

    def test_rules_are_saved_and_empty_rule_list_is_rejected(self):
        save_rules(
            ["My 1:1:1 definition", " ", "No unplanned trades"], self.data_dir
        )

        self.assertEqual(
            get_rules(self.data_dir),
            ["My 1:1:1 definition", "No unplanned trades"],
        )
        with self.assertRaises(ValueError):
            save_rules([" ", ""], self.data_dir)

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


if __name__ == "__main__":
    unittest.main()
