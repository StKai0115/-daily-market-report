"""台股每日籌碼報告（資料來源：FinMind API）

報告內容：外資買超排行、外資賣超排行、投信買超排行
涵蓋範圍：上市（TWSE）與上櫃（TPEx）普通股

使用方式：
    python chip_report.py                   # 自動抓最近一個有資料的交易日
    python chip_report.py --date 2026-09-25 # 指定日期
    python chip_report.py --top 30          # 每個排行顯示 30 檔
"""

import argparse
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

API_URL = "https://api.finmindtrade.com/api/v4/data"
TIMEOUT = 60

# FinMind 三大法人資料中的法人名稱
FOREIGN_NAMES = ("Foreign_Investor", "Foreign_Dealer_Self")  # 外資及陸資（含外資自營商）
TRUST_NAME = "Investment_Trust"  # 投信

MARKET_LABELS = {"twse": "上市", "tpex": "上櫃"}

# 普通股代號：4 碼數字、首碼非 0（排除 ETF、權證、特別股等）
COMMON_STOCK_PATTERN = re.compile(r"^[1-9]\d{3}$")


class FinMindError(RuntimeError):
    pass


def fetch_dataset(token, dataset, **params):
    """呼叫 FinMind v4 API，回傳 data 陣列。"""
    query = {"dataset": dataset, **params}
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = requests.get(API_URL, params=query, headers=headers, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise FinMindError(f"連線 FinMind 失敗：{exc}") from exc

    try:
        payload = resp.json()
    except ValueError:
        raise FinMindError(f"FinMind 回應格式錯誤（HTTP {resp.status_code}）：{resp.text[:200]}")

    if resp.status_code != 200 or payload.get("status") != 200:
        msg = payload.get("msg", resp.text[:200])
        raise FinMindError(f"FinMind 回傳錯誤（HTTP {resp.status_code}）：{msg}")
    return payload.get("data", [])


def load_stock_info(token):
    """取得上市、上櫃普通股清單：{stock_id: (名稱, 市場)}。"""
    info = {}
    for row in fetch_dataset(token, "TaiwanStockInfo"):
        stock_id = str(row.get("stock_id", ""))
        market = row.get("type")
        if market not in MARKET_LABELS or not COMMON_STOCK_PATTERN.match(stock_id):
            continue
        # 同一檔股票可能因多個產業分類重複出現，保留第一筆即可
        info.setdefault(stock_id, (row.get("stock_name", ""), MARKET_LABELS[market]))
    return info


def load_institutional(token, trade_date):
    """取得指定日期全市場三大法人買賣資料。"""
    day = trade_date.isoformat()
    return fetch_dataset(
        token,
        "TaiwanStockInstitutionalInvestorsBuySell",
        start_date=day,
        end_date=day,
    )


def find_latest_trading_day(token, start, lookback=10):
    """從 start 往前找，回傳第一個有法人資料的日期與資料。"""
    for offset in range(lookback + 1):
        day = start - timedelta(days=offset)
        if day.weekday() >= 5:  # 週六、週日略過
            continue
        rows = load_institutional(token, day)
        if rows:
            return day, rows
    raise FinMindError(f"{start} 往前 {lookback} 天內都查不到三大法人資料")


def aggregate(rows, stock_info):
    """彙總每檔股票的外資、投信買賣股數。"""
    result = {}
    for row in rows:
        stock_id = str(row.get("stock_id", ""))
        if stock_id not in stock_info:
            continue
        name = row.get("name")
        if name in FOREIGN_NAMES:
            key = "foreign"
        elif name == TRUST_NAME:
            key = "trust"
        else:
            continue
        entry = result.setdefault(
            stock_id,
            {"foreign": [0, 0], "trust": [0, 0]},  # [買進股數, 賣出股數]
        )
        entry[key][0] += int(row.get("buy") or 0)
        entry[key][1] += int(row.get("sell") or 0)
    return result


def build_ranking(summary, stock_info, key, top, descending):
    """依買賣超排序，descending=True 為買超排行，False 為賣超排行。"""
    items = []
    for stock_id, entry in summary.items():
        buy, sell = entry[key]
        net = buy - sell
        if (descending and net <= 0) or (not descending and net >= 0):
            continue
        name, market = stock_info[stock_id]
        items.append((stock_id, name, market, buy, sell, net))
    items.sort(key=lambda x: x[5], reverse=descending)
    return items[:top]


def to_lots(shares):
    """股數換算成張數（1 張 = 1000 股），四捨五入。"""
    return round(shares / 1000)


def format_table(title, items):
    lines = [f"## {title}", ""]
    if not items:
        lines += ["（無資料）", ""]
        return "\n".join(lines)
    lines.append("| 排名 | 代號 | 名稱 | 市場 | 買進(張) | 賣出(張) | 買賣超(張) |")
    lines.append("|---:|:---|:---|:---:|---:|---:|---:|")
    for rank, (stock_id, name, market, buy, sell, net) in enumerate(items, 1):
        lines.append(
            f"| {rank} | {stock_id} | {name} | {market} | "
            f"{to_lots(buy):,} | {to_lots(sell):,} | {to_lots(net):+,} |"
        )
    lines.append("")
    return "\n".join(lines)


def build_report(trade_date, summary, stock_info, top):
    sections = [
        ("外資買超排行", "foreign", True),
        ("外資賣超排行", "foreign", False),
        ("投信買超排行", "trust", True),
    ]
    parts = [
        f"# 台股每日籌碼報告 {trade_date.isoformat()}",
        "",
        "資料來源：FinMind（上市＋上櫃普通股；外資含外資自營商）",
        "",
    ]
    for title, key, descending in sections:
        items = build_ranking(summary, stock_info, key, top, descending)
        parts.append(format_table(f"{title}（前 {top} 名）", items))
    return "\n".join(parts)


def parse_args():
    parser = argparse.ArgumentParser(description="台股每日籌碼報告（FinMind）")
    parser.add_argument(
        "--date",
        help="查詢日期 YYYY-MM-DD；未指定時自動找最近一個有資料的交易日",
    )
    parser.add_argument("--top", type=int, default=20, help="每個排行顯示幾檔（預設 20）")
    parser.add_argument(
        "--output-dir",
        default="reports",
        help="報告輸出資料夾（預設 reports）",
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

    try:
        if args.date:
            trade_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        else:
            trade_date = None
    except ValueError:
        print("錯誤：日期格式應為 YYYY-MM-DD，例如 2026-09-25。", file=sys.stderr)
        return 1

    try:
        print("讀取上市櫃股票清單…")
        stock_info = load_stock_info(token)

        print("讀取三大法人買賣資料…")
        if trade_date:
            rows = load_institutional(token, trade_date)
            if not rows:
                print(f"錯誤：{trade_date} 查無三大法人資料（可能是休市日或資料尚未更新）。", file=sys.stderr)
                return 1
        else:
            trade_date, rows = find_latest_trading_day(token, date.today())
    except FinMindError as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1

    summary = aggregate(rows, stock_info)
    report = build_report(trade_date, summary, stock_info, args.top)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"chip_report_{trade_date.isoformat()}.md"
    output_path.write_text(report, encoding="utf-8")

    print()
    print(report)
    print(f"報告已儲存：{output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
