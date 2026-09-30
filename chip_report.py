"""台股每日籌碼報告（資料來源：FinMind API）

報告內容：全市場總覽、期貨選擇權籌碼、外資買超／賣超、投信買超／賣超、外資投信同步買超、
          外資／投信連續買超、產業別法人淨買賣、高股息 ETF、融資融券、千張大戶持股
涵蓋範圍：上市（TWSE）與上櫃（TPEx）普通股（高股息 ETF 另列）

使用方式：
    python chip_report.py                    # 自動抓最近一個有資料的交易日
    python chip_report.py --date 2026-09-25  # 指定日期
    python chip_report.py --top 30           # 每個排行顯示 30 檔
    python chip_report.py --rank-by amount   # 排行改依金額排序
    python chip_report.py --notify           # 產生報告後推播摘要到 Telegram / LINE
    python chip_report.py --today-only       # 今天沒有資料（休市或尚未更新）就不產生報告
    python chip_report.py --streak-min 5     # 連續買超區塊只列連買 5 天以上
    python chip_report.py --no-streak        # 不計算連續買超天數（少抓歷史資料）
    python chip_report.py --etfs 0056,00878  # 自訂追蹤的高股息 ETF
    python chip_report.py --no-margin        # 不產生融資融券區塊（另有 --no-etf、--no-futures、--no-holders）
    python chip_report.py --weekly           # 非週五也產生週報（週五會自動產生；--no-weekly 可關閉）
    python chip_report.py --no-events        # 不產生美股重大事件行事曆
"""

import argparse
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import finmind
from analysis import apply_streaks, build_report, build_stocks
from events import build_events_section, collect_events
from extras import (
    DEFAULT_ETFS,
    build_etf_section,
    build_futures_section,
    build_holder_sections,
    build_margin_sections,
    put_call_ratio,
)
from notify import MESSAGE_SEPARATOR, build_summary, configured_channels, send_all
from outputs import render_html, render_markdown, write_excel
from weekly import build_weekly_report, build_weekly_summary, previous_trading_day, week_days

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
        "--streak-days",
        type=int,
        default=10,
        help="連續買超天數最多回溯幾個交易日（含當日，預設 10）",
    )
    parser.add_argument(
        "--streak-min",
        type=int,
        default=3,
        help="連續買超區塊的最少連買天數（預設 3）",
    )
    parser.add_argument(
        "--no-streak",
        action="store_true",
        help="不計算連續買超天數（不抓歷史資料，執行較快）",
    )
    parser.add_argument(
        "--etfs",
        default=",".join(DEFAULT_ETFS),
        help="追蹤的高股息 ETF 代號，以逗號分隔（預設 " + ",".join(DEFAULT_ETFS) + "）",
    )
    parser.add_argument("--no-etf", action="store_true", help="不產生高股息 ETF 區塊")
    parser.add_argument("--no-futures", action="store_true", help="不產生期貨選擇權區塊")
    parser.add_argument("--no-margin", action="store_true", help="不產生融資融券區塊")
    parser.add_argument("--no-holders", action="store_true", help="不產生千張大戶持股區塊")
    parser.add_argument("--no-events", action="store_true", help="不產生未來 7 天美股重大事件行事曆")
    parser.add_argument("--weekly", action="store_true", help="非週五也產生本週週報")
    parser.add_argument("--no-weekly", action="store_true", help="週五不產生週報")
    parser.add_argument(
        "--summary-file",
        help="另存推播摘要文字檔（供之後用 notify.py 推播）",
    )
    parser.add_argument(
        "--today-only",
        action="store_true",
        help="只處理今天（台灣時間，或 --date 指定日期）的資料；沒有資料時不產生報告也不推播，並正常結束",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="推播摘要到 Telegram / LINE（需設定對應環境變數）",
    )
    return parser.parse_args()


def run_optional(label, func):
    """執行延伸區塊；抓不到資料或解析失敗時只略過該區塊，不影響主報告。"""
    print(f"讀取{label}資料…")
    try:
        return func()
    except Exception as exc:  # 延伸資料格式未知或權限不足時，不讓整份報告失敗
        print(f"警告：{label}資料讀取失敗，略過此區塊（{exc}）", file=sys.stderr)
        return None


def futures_section(token, trade_date):
    futures_rows = finmind.load_futures_institutional(token, trade_date)
    if not futures_rows:
        raise finmind.FinMindError("查無台指期法人資料")
    try:
        option_rows = finmind.load_option_institutional(token, trade_date)
    except finmind.FinMindError as exc:
        print(f"警告：選擇權法人資料讀取失敗（{exc}）", file=sys.stderr)
        option_rows = []
    pc_today = put_call_ratio(finmind.load_option_daily(token, trade_date))
    earlier = sorted({str(r.get("date")) for r in futures_rows if str(r.get("date")) < trade_date.isoformat()})
    pc_prev = None
    if earlier:
        pc_prev = put_call_ratio(finmind.load_option_daily(token, date.fromisoformat(earlier[-1])))
    return build_futures_section(trade_date, futures_rows, option_rows, pc_today, pc_prev)


def holder_sections(token, trade_date, stocks, top):
    weeks = finmind.find_holding_weeks(token, trade_date)
    if len(weeks) < 2:
        raise finmind.FinMindError("找不到最近兩週的集保資料")
    return build_holder_sections(stocks, weeks, top)


def write_outputs(report, base, formats):
    """依指定格式輸出報告，回傳已儲存的檔案路徑；Excel 開啟中無法寫入時丟出 PermissionError。"""
    saved = []
    if "md" in formats:
        path = base.with_suffix(".md")
        path.write_text(render_markdown(report), encoding="utf-8")
        saved.append(path)
    if "html" in formats:
        path = base.with_suffix(".html")
        path.write_text(render_html(report), encoding="utf-8")
        saved.append(path)
    if "xlsx" in formats:
        path = base.with_suffix(".xlsx")
        write_excel(report, path)
        saved.append(path)
    return saved


def main():
    args = parse_args()

    token = os.environ.get("FINMIND_TOKEN", "").strip()
    if not token:
        print("錯誤：找不到環境變數 FINMIND_TOKEN，請先設定 FinMind API token。", file=sys.stderr)
        return 1
    if args.top <= 0:
        print("錯誤：--top 必須大於 0。", file=sys.stderr)
        return 1
    if not args.no_streak and not 2 <= args.streak_min <= args.streak_days:
        print("錯誤：--streak-min 需介於 2 與 --streak-days 之間。", file=sys.stderr)
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
        etf_ids = [] if args.no_etf else [e.strip() for e in args.etfs.split(",") if e.strip()]
        stock_info = finmind.load_stock_info(token, etf_ids)

        print("讀取三大法人買賣資料…")
        if trade_date:
            inst_rows = finmind.load_institutional(token, trade_date)
            if not inst_rows and args.today_only:
                print(f"{trade_date} 沒有三大法人資料（休市或尚未更新），本次不產生報告。")
                return 0
            if not inst_rows:
                print(f"錯誤：{trade_date} 查無三大法人資料（可能是休市日或資料尚未更新）。", file=sys.stderr)
                return 1
        else:
            trade_date, inst_rows = finmind.find_latest_trading_day(token, taipei_today())

        print("讀取股價資料…")
        prices = finmind.load_prices(token, trade_date)

        # 週五自動產生週報（週報需要本週每日資料與上週最後一個交易日）
        weekly = not args.no_weekly and (args.weekly or trade_date.weekday() == 4)
        history_days = 0 if args.no_streak else args.streak_days - 1
        if weekly:
            history_days = max(history_days, 5)
        history = []
        if history_days:
            print(f"讀取前 {history_days} 個交易日的法人資料（計算連續買超天數與週報）…")
            history = finmind.load_history(token, trade_date, history_days)
    except finmind.FinMindError as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1

    if not prices:
        print(f"警告：{trade_date} 查無股價資料，金額、漲跌幅、佔成交量將顯示為「-」。", file=sys.stderr)

    stocks = build_stocks(inst_rows, prices, stock_info)
    streak_window = None
    if not args.no_streak:
        apply_streaks(stocks, history)
        streak_window = len(history) + 1
    # ETF 另外列在高股息 ETF 區塊，不納入個股排行與全市場統計
    etf_stocks = {k: v for k, v in stocks.items() if k in etf_ids}
    common = {k: v for k, v in stocks.items() if k not in etf_ids}
    report = build_report(
        trade_date, common, args.top, args.rank_by, streak_window, args.streak_min
    )

    common_list = list(common.values())
    if not args.no_futures:
        section = run_optional("期貨選擇權", lambda: futures_section(token, trade_date))
        if section:
            report.sections.insert(0, section)
    if not args.no_events:
        def events_section():
            warn = lambda msg: print(msg, file=sys.stderr)  # noqa: E731
            return build_events_section(collect_events(datetime.now(TAIPEI_TZ), warn=warn))

        section = run_optional("美股重大事件", events_section)
        if section:
            # 放在期貨選擇權之後、個股排行之前
            index = 1 if report.sections and report.sections[0].key == "futures" else 0
            report.sections.insert(index, section)
    if etf_ids:
        report.sections.append(build_etf_section(etf_stocks, etf_ids, streak_window is not None))
    if not args.no_margin:
        report.sections += run_optional(
            "融資融券", lambda: build_margin_sections(common_list, finmind.load_margin(token, trade_date), args.top)
        ) or []
    if not args.no_holders:
        report.sections += run_optional(
            "集保大戶持股", lambda: holder_sections(token, trade_date, common_list, args.top)
        ) or []

    weekly_report = None
    if weekly:
        prev_day = previous_trading_day(trade_date, history)
        prev_prices = None
        if prev_day:
            prev_prices = run_optional("上週收盤價", lambda: finmind.load_prices(token, prev_day))
        weekly_report = build_weekly_report(
            trade_date, week_days(trade_date, inst_rows, history), common, args.top, prev_prices
        )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    day = trade_date.isoformat()
    outputs = [(report, output_dir / f"chip_report_{day}")]
    if weekly_report:
        outputs.append((weekly_report, output_dir / f"weekly_report_{day}"))

    saved = []
    for rpt, base in outputs:
        print()
        print(render_markdown(rpt))
        try:
            saved += write_outputs(rpt, base, args.formats)
        except PermissionError:
            print(f"錯誤：無法寫入 {base}.xlsx，請先關閉已開啟的 Excel 檔案。", file=sys.stderr)
            return 1

    for path in saved:
        print(f"報告已儲存：{path}")

    # 設定 REPORT_BASE_URL（例如 GitHub Pages 網址）時，摘要會附上完整報告連結
    base_url = os.environ.get("REPORT_BASE_URL", "").strip().rstrip("/")
    report_url = f"{base_url}/{day}.html" if base_url else None
    summary = build_summary(report, report_url=report_url)
    if weekly_report:
        weekly_url = f"{base_url}/weekly-{day}.html" if base_url else None
        # 週報作為同一次推播的第二則訊息，不另外消耗推播額度
        summary += MESSAGE_SEPARATOR + build_weekly_summary(weekly_report, report_url=weekly_url)
    if args.summary_file:
        Path(args.summary_file).write_text(summary, encoding="utf-8")
        print(f"推播摘要已儲存：{args.summary_file}")

    if channels and not send_all(channels, summary):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
