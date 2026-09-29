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


def load_stock_info(token):
    """取得上市、上櫃普通股清單：{stock_id: {"name", "market", "industry"}}。"""
    info = {}
    for row in fetch_dataset(token, "TaiwanStockInfo"):
        stock_id = str(row.get("stock_id", ""))
        market = row.get("type")
        if market not in MARKET_LABELS or not COMMON_STOCK_PATTERN.match(stock_id):
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
