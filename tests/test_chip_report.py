import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chip_report  # noqa: E402
import finmind  # noqa: E402
from analysis import build_report, build_stocks  # noqa: E402
from notify import build_summary  # noqa: E402
from outputs import render_html, render_markdown, write_excel  # noqa: E402

STOCK_INFO = [
    {"stock_id": "2330", "stock_name": "台積電", "type": "twse", "industry_category": "半導體業"},
    {"stock_id": "2330", "stock_name": "台積電", "type": "twse", "industry_category": "電子工業"},
    {"stock_id": "2317", "stock_name": "鴻海", "type": "twse", "industry_category": "其他電子業"},
    {"stock_id": "6488", "stock_name": "環球晶", "type": "tpex", "industry_category": "半導體業"},
    {"stock_id": "0050", "stock_name": "元大台灣50", "type": "twse", "industry_category": "ETF"},
]

INSTITUTIONAL = [
    {"stock_id": "2330", "name": "Foreign_Investor", "buy": 5_000_000, "sell": 2_000_000},
    {"stock_id": "2330", "name": "Foreign_Dealer_Self", "buy": 1_000, "sell": 0},
    {"stock_id": "2330", "name": "Investment_Trust", "buy": 300_000, "sell": 100_000},
    {"stock_id": "2330", "name": "Dealer_self", "buy": 50_000, "sell": 10_000},
    {"stock_id": "2317", "name": "Foreign_Investor", "buy": 100_000, "sell": 300_000},
    {"stock_id": "2317", "name": "Investment_Trust", "buy": 0, "sell": 50_000},
    {"stock_id": "6488", "name": "Foreign_Investor", "buy": 100_000, "sell": 900_000},
    {"stock_id": "0050", "name": "Foreign_Investor", "buy": 9_999_999, "sell": 0},
]

PRICES = [
    {"stock_id": "2330", "close": 1000.0, "spread": 20.0, "Trading_Volume": 30_000_000},
    {"stock_id": "2317", "close": 200.0, "spread": -4.0, "Trading_Volume": 20_000_000},
    # 6488 無股價，測試缺值處理
]


def fake_fetch(token, dataset, **params):
    if dataset == "TaiwanStockInfo":
        return STOCK_INFO
    if params.get("start_date") != "2026-09-25":
        return []
    if dataset == "TaiwanStockInstitutionalInvestorsBuySell":
        return INSTITUTIONAL
    if dataset == "TaiwanStockPrice":
        return PRICES
    raise AssertionError(dataset)


class ReportTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(finmind, "fetch_dataset", fake_fetch)
        patcher.start()
        self.addCleanup(patcher.stop)
        day = date(2026, 9, 25)
        stocks = build_stocks(
            finmind.load_institutional("t", day),
            finmind.load_prices("t", day),
            finmind.load_stock_info("t"),
        )
        self.stocks = stocks
        self.report = build_report(day, stocks, top=20)
        self.by_key = {s.key: s for s in self.report.sections}

    def test_etf_excluded_and_markets(self):
        self.assertNotIn("0050", self.stocks)
        self.assertEqual(self.stocks["6488"].market, "上櫃")
        self.assertEqual(self.stocks["2330"].industry, "半導體業")

    def test_price_fields(self):
        tsmc = self.stocks["2330"]
        self.assertAlmostEqual(tsmc.change_pct, 20 / 980 * 100)
        # 外資 +3,001 張 × 1000 元 = 30.01 億
        self.assertAlmostEqual(tsmc.amount_yi(tsmc.net("foreign")), 30.01)
        self.assertAlmostEqual(tsmc.volume_pct(tsmc.net("foreign")), 3_001_000 / 30_000_000 * 100)
        self.assertIsNone(self.stocks["6488"].amount_yi(1000))

    def test_rankings(self):
        ids = lambda key: [r[1] for r in self.by_key[key].rows]  # noqa: E731
        self.assertEqual(ids("foreign_buy"), ["2330"])
        self.assertEqual(ids("foreign_sell"), ["6488", "2317"])
        self.assertEqual(ids("trust_buy"), ["2330"])
        self.assertEqual(ids("trust_sell"), ["2317"])
        self.assertEqual(ids("sync_buy"), ["2330"])

    def test_rank_by_amount(self):
        report = build_report(date(2026, 9, 25), self.stocks, top=20, rank_by="amount")
        sell = next(s for s in report.sections if s.key == "foreign_sell")
        # 6488 無股價，金額視為 0，排在鴻海之後
        self.assertEqual([r[1] for r in sell.rows], ["2317", "6488"])

    def test_industry_and_overview(self):
        industry = {r[0]: r for r in self.by_key["industry"].rows}
        self.assertAlmostEqual(industry["半導體業"][1], 30.01)
        self.assertAlmostEqual(industry["半導體業"][2], 2.0)
        self.assertEqual(self.by_key["industry"].rows[0][0], "半導體業")
        overview = {r[0]: r for r in self.report.overview.rows}
        self.assertEqual(overview["外資"][1], 3001 - 200 - 800)
        self.assertEqual(overview["自營商"][1], 40)

    def test_outputs(self):
        md = render_markdown(self.report)
        self.assertIn("## 外資投信同步買超", md)
        self.assertIn("+30.01", md)
        page = render_html(self.report)
        self.assertIn('class="num up"', page)
        self.assertIn('class="num down"', page)
        summary = build_summary(self.report)
        self.assertIn("1. 2330 台積電 +3,001 張（+30.01 億）", summary)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.xlsx"
            write_excel(self.report, path)
            from openpyxl import load_workbook

            wb = load_workbook(path)
            self.assertIn("全部個股", wb.sheetnames)
            self.assertEqual(wb["外資買超"]["B2"].value, "2330")


class MainTest(unittest.TestCase):
    def setUp(self):
        # 固定「今天」，讓自動找交易日的結果不受實際日期影響
        patcher = mock.patch.object(chip_report, "taipei_today", return_value=date(2026, 9, 29))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_main_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(finmind, "fetch_dataset", fake_fetch), \
                mock.patch.dict(os.environ, {"FINMIND_TOKEN": "t"}), \
                mock.patch.object(sys, "argv", ["chip_report.py", "--output-dir", tmp]), \
                mock.patch("sys.stdout"):
            self.assertEqual(chip_report.main(), 0)
            names = sorted(p.name for p in Path(tmp).iterdir())
        self.assertEqual(
            names,
            ["chip_report_2026-09-25.html", "chip_report_2026-09-25.md", "chip_report_2026-09-25.xlsx"],
        )

    def test_missing_token(self):
        with mock.patch.dict(os.environ, {"FINMIND_TOKEN": ""}), \
                mock.patch.object(sys, "argv", ["chip_report.py"]), \
                mock.patch("sys.stderr"):
            self.assertEqual(chip_report.main(), 1)

    def test_notify_without_channels(self):
        env = {"FINMIND_TOKEN": "t", "TELEGRAM_BOT_TOKEN": "", "LINE_CHANNEL_ACCESS_TOKEN": ""}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(sys, "argv", ["chip_report.py", "--notify"]), \
                mock.patch("sys.stderr"):
            self.assertEqual(chip_report.main(), 1)

    def test_notify_sends_to_both_channels(self):
        env = {
            "FINMIND_TOKEN": "t",
            "TELEGRAM_BOT_TOKEN": "tg", "TELEGRAM_CHAT_ID": "123",
            "LINE_CHANNEL_ACCESS_TOKEN": "ln", "LINE_USER_ID": "U1",
        }
        ok = mock.Mock(status_code=200)
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(finmind, "fetch_dataset", fake_fetch), \
                mock.patch.dict(os.environ, env), \
                mock.patch.object(sys, "argv", ["chip_report.py", "--notify", "--formats", "md",
                                                "--output-dir", tmp]), \
                mock.patch("notify.requests.post", return_value=ok) as post, \
                mock.patch("sys.stdout"):
            self.assertEqual(chip_report.main(), 0)
        urls = [c.args[0] for c in post.call_args_list]
        self.assertEqual(urls, ["https://api.telegram.org/bottg/sendMessage",
                                "https://api.line.me/v2/bot/message/push"])
        line_body = post.call_args_list[1].kwargs["json"]
        self.assertEqual(line_body["to"], "U1")
        self.assertIn("【外資買超】", line_body["messages"][0]["text"])

    def _run_today_only(self, today):
        env = {"FINMIND_TOKEN": "t", "TELEGRAM_BOT_TOKEN": "tg", "TELEGRAM_CHAT_ID": "1"}
        ok = mock.Mock(status_code=200)
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(chip_report, "taipei_today", return_value=today), \
                mock.patch.object(finmind, "fetch_dataset", fake_fetch), \
                mock.patch.dict(os.environ, env), \
                mock.patch.object(sys, "argv", ["chip_report.py", "--today-only", "--notify",
                                                "--output-dir", tmp]), \
                mock.patch("notify.requests.post", return_value=ok) as post, \
                mock.patch("sys.stdout"):
            code = chip_report.main()
            files = list(Path(tmp).iterdir())
        return code, files, post

    def test_today_only_with_data(self):
        code, files, post = self._run_today_only(date(2026, 9, 25))
        self.assertEqual(code, 0)
        self.assertEqual(len(files), 3)
        post.assert_called_once()

    def test_today_only_without_data_skips(self):
        code, files, post = self._run_today_only(date(2026, 9, 28))
        self.assertEqual(code, 0)
        self.assertEqual(files, [])
        post.assert_not_called()

    def test_taipei_today_uses_utc_plus_8(self):
        fake_now = chip_report.datetime(2026, 9, 28, 17, 0, tzinfo=chip_report.timezone.utc)
        with mock.patch.object(chip_report, "datetime") as dt:
            dt.now.side_effect = lambda tz: fake_now.astimezone(tz)
            self.assertEqual(chip_report.taipei_today(), date(2026, 9, 29))


if __name__ == "__main__":
    unittest.main()
