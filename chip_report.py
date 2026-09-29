"""台股每日籌碼報告（資料來源：FinMind API）

報告內容：全市場總覽、外資買超／賣超、投信買超／賣超、外資投信同步買超、產業別法人淨買賣
涵蓋範圍：上市（TWSE）與上櫃（TPEx）普通股

使用方式：
    python chip_report.py                    # 自動抓最近一個有資料的交易日
    python chip_report.py --date 2026-09-25  # 指定日期
    python chip_report.py --top 30           # 每個排行顯示 30 檔
    python chip_report.py --rank-by amount   # 排行改依金額排序
    python chip_report.py --notify           # 產生報告後推播摘要到 Telegram / LINE
    python chip_report.py --today-only       # 今天沒有資料（休市或尚未更新）就不產生報告
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import finmind
from analysis import build_report, build_stocks
from notify import build_summary, configured_channels
from outputs import render_html, render_markdown, write_excel

FORMATS = ("md", "html", "xlsx")

# 台灣時區（無日光節約時間）；雲端主機多為 UTC，日期需以台灣時間判斷
TAIPEI_TZ = timezone(timedelta(hours=8))


def taipei_today():
    return datetime.now(TAIPEI_TZ).date()


def parse_formats(value):
    formats = [f.strip().lower() for f in value.split(",") if f.strip()]
    unknown = [f for f in formats if f not in FORMATS]
    if unknown or not formats:
        raise argparse.ArgumentTypeError(f"格式只能是 {', '.join(FORMATS)}，以逗號分隔")
    return formats


def parse_args():
    parser = argparse.ArgumentParser(description="台股每日籌碼報告（FinMind）")
    parser.add_argument(
        "--date",
        help="查詢日期 YYYY-MM-DD；未指定時自動找最近一個有資料的交易日",
    )
    parser.add_argument("--top", type=int, default=20, help="每個排行顯示幾檔（預設 20）")
    parser.add_argument(
        "--rank-by",
        choices=("lots", "amount"),
        default="lots",
        help="排行依據：lots＝張數（預設）、amount＝金額",
    )
    parser.add_argument(
        "--formats",
        type=parse_formats,
        default=list(FORMATS),
        help="輸出格式，以逗號分隔（預設 md,html,xlsx）",
    )
    parser.add_argument(
        "--output-dir",
        default="reports",
        help="報告輸出資料夾（預設 reports）",
    )
    parser.add_argument(
        "--today-only",
        action="store_true",
        help="只處理今天（台灣時間）的資料；今天沒有資料時不產生報告也不推播",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="推播摘要到 Telegram / LINE（需設定對應環境變數）",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    token = os.environ.get("FINMIND_TOKEN", "").strip()
    if not token:
        print("錯誤：找不到環境變數 FINMIND_TOKEN，請先設定 FinMind API token。", file=sys.stderr)
        return 1
    if args.top <= 0:
        print("錯誤：--top 必須大於 0。", file=sys.stderr)
        return 1

    trade_date = None
    if args.date:
        try:
            trade_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            print("錯誤：日期格式應為 YYYY-MM-DD，例如 2026-09-25。", file=sys.stderr)
            return 1
    elif args.today_only:
        trade_date = taipei_today()

    channels = configured_channels() if args.notify else []
    if args.notify and not channels:
        print(
            "錯誤：使用 --notify 需設定 TELEGRAM_BOT_TOKEN＋TELEGRAM_CHAT_ID，"
            "或 LINE_CHANNEL_ACCESS_TOKEN＋LINE_USER_ID。",
            file=sys.stderr,
        )
        return 1

    try:
        print("讀取上市櫃股票清單…")
        stock_info = finmind.load_stock_info(token)

        print("讀取三大法人買賣資料…")
        if trade_date:
            inst_rows = finmind.load_institutional(token, trade_date)
            if not inst_rows and args.today_only and not args.date:
                print(f"{trade_date} 沒有三大法人資料（休市或尚未更新），本次不產生報告。")
                return 0
            if not inst_rows:
                print(f"錯誤：{trade_date} 查無三大法人資料（可能是休市日或資料尚未更新）。", file=sys.stderr)
                return 1
        else:
            trade_date, inst_rows = finmind.find_latest_trading_day(token, taipei_today())

        print("讀取股價資料…")
        prices = finmind.load_prices(token, trade_date)
    except finmind.FinMindError as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1

    if not prices:
        print(f"警告：{trade_date} 查無股價資料，金額、漲跌幅、佔成交量將顯示為「-」。", file=sys.stderr)

    stocks = build_stocks(inst_rows, prices, stock_info)
    report = build_report(trade_date, stocks, args.top, args.rank_by)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    base = output_dir / f"chip_report_{trade_date.isoformat()}"

    markdown = render_markdown(report)
    print()
    print(markdown)

    saved = []
    if "md" in args.formats:
        path = base.with_suffix(".md")
        path.write_text(markdown, encoding="utf-8")
        saved.append(path)
    if "html" in args.formats:
        path = base.with_suffix(".html")
        path.write_text(render_html(report), encoding="utf-8")
        saved.append(path)
    if "xlsx" in args.formats:
        path = base.with_suffix(".xlsx")
        try:
            write_excel(report, path)
            saved.append(path)
        except PermissionError:
            print(f"錯誤：無法寫入 {path}，請先關閉已開啟的 Excel 檔案。", file=sys.stderr)
            return 1

    for path in saved:
        print(f"報告已儲存：{path}")

    exit_code = 0
    if channels:
        summary = build_summary(report)
        for name, send in channels:
            try:
                send(summary)
                print(f"已推播到 {name}")
            except Exception as exc:  # 推播失敗不影響已產生的報告
                print(f"錯誤：{exc}", file=sys.stderr)
                exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
