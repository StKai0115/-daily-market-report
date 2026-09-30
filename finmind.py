"""FinMind API 資料讀取"""

import re
from datetime import timedelta

import requests

API_URL = "https://api.finmindtrade.com/api/v4/data"
TIMEOUT = 60

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


def load_stock_info(token, extra_ids=()):
    """取得上市、上櫃普通股清單：{stock_id: {"name", "market", "industry"}}。

    extra_ids 為額外要納入的代號（例如 ETF），這些代號的 industry 固定為 "ETF"。
    """
    extra_ids = set(extra_ids)
    info = {}
    for row in fetch_dataset(token, "TaiwanStockInfo"):
        stock_id = str(row.get("stock_id", ""))
        market = row.get("type")
        if market not in MARKET_LABELS:
            continue
        if stock_id in extra_ids:
            info.setdefault(
                stock_id,
                {"name": row.get("stock_name", ""), "market": MARKET_LABELS[market], "industry": "ETF"},
            )
            continue
        if not COMMON_STOCK_PATTERN.match(stock_id):
            continue
        # 同一檔股票可能因多個產業分類重複出現，保留第一筆即可
        info.setdefault(
            stock_id,
            {
                "name": row.get("stock_name", ""),
                "market": MARKET_LABELS[market],
                "industry": row.get("industry_category") or "其他",
            },
        )
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


def load_prices(token, trade_date):
    """取得指定日期全市場股價：{stock_id: row}。"""
    day = trade_date.isoformat()
    rows = fetch_dataset(token, "TaiwanStockPrice", start_date=day, end_date=day)
    return {str(row.get("stock_id", "")): row for row in rows}


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


def load_history(token, trade_date, days):
    """取得 trade_date 之前 days 個交易日的法人資料，由近到遠：[(日期, rows)]。"""
    history = []
    day = trade_date
    # 最多往前找 days×2＋10 個日曆日，涵蓋週末與連假
    for _ in range(days * 2 + 10):
        if len(history) >= days:
            break
        day -= timedelta(days=1)
        if day.weekday() >= 5:
            continue
        rows = load_institutional(token, day)
        if rows:
            history.append((day, rows))
    return history


def _date_range(trade_date, days):
    return {
        "start_date": (trade_date - timedelta(days=days)).isoformat(),
        "end_date": trade_date.isoformat(),
    }


def load_futures_institutional(token, trade_date, futures_id="TX"):
    """期貨三大法人未平倉（近兩週，用來計算日增減）。"""
    return fetch_dataset(
        token, "TaiwanFuturesInstitutionalInvestors", data_id=futures_id,
        **_date_range(trade_date, 14),
    )


def load_option_institutional(token, trade_date, option_id="TXO"):
    """選擇權三大法人未平倉（近兩週）。"""
    return fetch_dataset(
        token, "TaiwanOptionInstitutionalInvestors", data_id=option_id,
        **_date_range(trade_date, 14),
    )


def load_option_daily(token, day, option_id="TXO"):
    """指定日期的選擇權各履約價行情（含未平倉量）。"""
    return fetch_dataset(
        token, "TaiwanOptionDaily", data_id=option_id,
        start_date=day.isoformat(), end_date=day.isoformat(),
    )


def load_margin(token, trade_date):
    """指定日期全市場個股融資融券：{stock_id: row}。"""
    day = trade_date.isoformat()
    rows = fetch_dataset(token, "TaiwanStockMarginPurchaseShortSale", start_date=day, end_date=day)
    return {str(row.get("stock_id", "")): row for row in rows}


def load_holding_shares(token, day):
    """指定日期全市場集保股權分散表。"""
    return fetch_dataset(
        token, "TaiwanStockHoldingSharesPer", start_date=day.isoformat(), end_date=day.isoformat()
    )


def find_holding_weeks(token, trade_date, weeks=4):
    """找出最近兩週的集保資料：[(日期, rows), (前一週日期, rows)]。

    集保資料每週公布一次，資料日期通常是週五（遇假日提前），因此只檢查週五、週四、週三。
    """
    found = []
    friday = trade_date - timedelta(days=(trade_date.weekday() - 4) % 7)
    for week in range(weeks):
        for back in (0, 1, 2):
            day = friday - timedelta(days=7 * week + back)
            if day > trade_date:
                continue
            rows = load_holding_shares(token, day)
            if rows:
                found.append((day, rows))
                break
        if len(found) == 2:
            break
    return found
