"""美股重大事件行事曆：經濟數據、FOMC、財報、選擇權到期、休市日

資料來源：
- 經濟數據公布日期：FRED API（聖路易聯邦準備銀行），需環境變數 FRED_API_KEY
- FOMC 會議：Fed 官網年度日程（抓不到時使用內建備用清單）
- 財報日期：Alpha Vantage EARNINGS_CALENDAR，需環境變數 ALPHAVANTAGE_API_KEY
- 選擇權到期日、台指結算日、美股休市日：依規則計算
"""

import csv
import io
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import requests

from analysis import Column, Section

NEW_YORK = ZoneInfo("America/New_York")
TAIPEI = ZoneInfo("Asia/Taipei")
TIMEOUT = 30
WEEKDAYS = "一二三四五六日"

# FRED 經濟數據：release_id -> (名稱, 重要性)。公布時間皆為美東 8:30
FRED_RELEASES = {
    10: ("CPI 消費者物價指數", 3),
    50: ("非農就業報告", 3),
    54: ("PCE 物價指數（個人所得與支出）", 2),
    46: ("PPI 生產者物價指數", 2),
    53: ("GDP 國內生產毛額", 2),
}
FRED_RELEASE_TIME = time(8, 30)

# 財報追蹤名單：代號 -> (名稱, 重要性)
EARNINGS_WATCH = {
    # 大型權值股（S&P 500、那斯達克 100 權重最高）
    "NVDA": ("輝達", 3),
    "AAPL": ("蘋果", 3),
    "MSFT": ("微軟", 3),
    "GOOGL": ("Alphabet", 3),
    "AMZN": ("亞馬遜", 3),
    "META": ("Meta", 3),
    "TSLA": ("特斯拉", 3),
    "AVGO": ("博通", 3),
    "TSM": ("台積電 ADR", 3),
    # 半導體與 AI 供應鏈
    "AMD": ("超微", 2),
    "MU": ("美光", 2),
    "ASML": ("艾司摩爾", 2),
    "QCOM": ("高通", 2),
    "ARM": ("安謀", 2),
    # 其他高權重或高波動
    "NFLX": ("網飛", 2),
    "ORCL": ("甲骨文", 2),
    "PLTR": ("Palantir", 2),
    "LLY": ("禮來", 2),
    "JPM": ("摩根大通", 2),  # 大型銀行財報是每季財報季的開端
    "WMT": ("沃爾瑪", 2),
}

# FOMC 備用日程（Fed 官網抓不到時使用）：(決議日, 是否公布經濟預測／點陣圖)
FOMC_FALLBACK = [
    (date(2026, 1, 28), False),
    (date(2026, 3, 18), True),
    (date(2026, 4, 29), False),
    (date(2026, 6, 17), True),
    (date(2026, 7, 29), False),
    (date(2026, 9, 16), True),
    (date(2026, 10, 28), False),
    (date(2026, 12, 9), True),
]
FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
FOMC_DECISION_TIME = time(14, 0)  # 美東 14:00 公布決議，14:30 主席記者會

MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], 1)}
MONTH_ABBR = {name[:3]: num for name, num in MONTHS.items()}


@dataclass
class Event:
    day: date  # 台灣日期
    time_text: str  # 台灣時間，例如 "20:30"、"清晨"；空字串表示整天
    title: str
    stars: int
    note: str = ""
    at: datetime = None  # 台灣時間（有明確時間時），用來判斷是否已經過去


def ny_to_taipei(day, at):
    """美東日期時間換算成台灣時間（自動處理夏令／冬令時間）。"""
    return datetime.combine(day, at, tzinfo=NEW_YORK).astimezone(TAIPEI)


def _timed_event(day, at, title, stars, note=""):
    tw = ny_to_taipei(day, at)
    return Event(tw.date(), tw.strftime("%H:%M"), title, stars, note, tw)


# ---------- 規則計算：選擇權到期、台指結算、美股休市 ----------

def nth_weekday(year, month, weekday, n):
    """某月第 n 個星期幾（weekday：週一為 0）；n 為 -1 表示最後一個。"""
    if n > 0:
        first = date(year, month, 1)
        return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
    last = (date(year, month % 12 + 1, 1) if month < 12 else date(year + 1, 1, 1)) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def easter(year):
    """復活節日期（西曆，Anonymous Gregorian 演算法）。"""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    return date(year, month, (h + l_ - 7 * m + 114) % 31 + 1)


def _observed(day):
    """固定日期假日遇週六提前到週五、遇週日延到週一。"""
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def us_market_holidays(year):
    """美股（NYSE）休市日：{日期: 名稱}。不含臨時休市。"""
    holidays = {
        nth_weekday(year, 1, 0, 3): "馬丁路德金恩紀念日",
        nth_weekday(year, 2, 0, 3): "總統日",
        easter(year) - timedelta(days=2): "耶穌受難日",
        nth_weekday(year, 5, 0, -1): "陣亡將士紀念日",
        _observed(date(year, 6, 19)): "六月節",
        _observed(date(year, 7, 4)): "獨立紀念日",
        nth_weekday(year, 9, 0, 1): "勞動節",
        nth_weekday(year, 11, 3, 4): "感恩節",
        _observed(date(year, 12, 25)): "聖誕節",
    }
    new_year = date(year, 1, 1)
    if new_year.weekday() != 5:  # 元旦遇週六時，NYSE 不在前一年 12/31 補假
        holidays[_observed(new_year)] = "元旦"
    return holidays


def us_early_closes(year):
    """美股提前收盤日（美東 13:00）：{日期: 說明}。"""
    closes = {nth_weekday(year, 11, 3, 4) + timedelta(days=1): "感恩節隔天"}
    for day, label in ((date(year, 7, 3), "獨立紀念日前一天"), (date(year, 12, 24), "聖誕夜")):
        if day.weekday() < 5 and day not in us_market_holidays(year):
            closes[day] = label
    return closes


def _us_trading_day_before(day):
    holidays = us_market_holidays(day.year)
    while day.weekday() >= 5 or day in holidays:
        day -= timedelta(days=1)
    return day


def rule_events(start, end):
    """start～end（含）期間依規則計算的事件。"""
    events = []
    for year in range(start.year, end.year + 1):
        for day, name in us_market_holidays(year).items():
            events.append(Event(day, "", f"美股休市（{name}）", 1))
        for day, name in us_early_closes(year).items():
            tw = ny_to_taipei(day, time(13, 0))
            events.append(Event(day, "", f"美股提前收盤（{name}）", 1, f"台灣時間 {tw:%H:%M} 收盤"))
        for month in range(1, 13):
            opex = _us_trading_day_before(nth_weekday(year, month, 4, 3))
            if month in (3, 6, 9, 12):
                events.append(Event(opex, "", "美股四巫日（季度選擇權、期貨到期）", 2))
            else:
                events.append(Event(opex, "", "美股選擇權月到期", 2))
            events.append(Event(nth_weekday(year, month, 2, 3), "", "台指期／台指選擇權月結算", 1,
                                "遇台股休市順延"))
    return [e for e in events if start <= e.day <= end]


# ---------- FRED：經濟數據公布日期 ----------

def fred_events(api_key, start, end):
    resp = requests.get(
        "https://api.stlouisfed.org/fred/releases/dates",
        params={
            "api_key": api_key,
            "file_type": "json",
            "realtime_start": start.isoformat(),
            "realtime_end": end.isoformat(),
            "include_release_dates_with_no_data": "true",
            "limit": 1000,
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    events = []
    for item in resp.json().get("release_dates", []):
        release = FRED_RELEASES.get(int(item.get("release_id", 0)))
        if not release:
            continue
        day = date.fromisoformat(item["date"])
        events.append(_timed_event(day, FRED_RELEASE_TIME, release[0], release[1]))
    return events


# ---------- FOMC ----------

def parse_fomc_calendar(html_text):
    """解析 Fed 官網 FOMC 日程：[(決議日, 是否公布經濟預測)]。"""
    meetings = []
    panels = re.split(r"(\d{4}) FOMC Meetings", html_text)
    # re.split 結果：[前言, 年份, 內容, 年份, 內容, ...]
    for year_text, body in zip(panels[1::2], panels[2::2]):
        year = int(year_text)
        months = re.findall(r'fomc-meeting__month[^>]*>\s*<strong>([^<]+)</strong>', body)
        dates = re.findall(r'fomc-meeting__date[^>]*>([^<]+)<', body)
        for month_text, date_text in zip(months, dates):
            date_text = date_text.strip()
            match = re.fullmatch(r"(\d{1,2})\s*[-–]\s*(\d{1,2})(\*?)", date_text)
            if not match:
                continue  # 非例行會議或格式不同
            last_month = month_text.strip().split("/")[-1].strip()
            month = MONTHS.get(last_month) or MONTH_ABBR.get(last_month[:3])
            if not month:
                continue
            meetings.append((date(year, month, int(match.group(2))), bool(match.group(3))))
    return meetings


def fomc_events(start, end, fetch=True):
    meetings = []
    if fetch:
        try:
            resp = requests.get(FOMC_URL, timeout=TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            meetings = parse_fomc_calendar(resp.text)
        except (requests.RequestException, ValueError):
            meetings = []
    note = ""
    if not meetings:
        meetings = FOMC_FALLBACK
        note = "內建日程，以 Fed 官網為準"
    events = []
    for day, sep in meetings:
        title = "FOMC 利率決議＋主席記者會" + ("（含點陣圖）" if sep else "")
        event = _timed_event(day, FOMC_DECISION_TIME, title, 3, note)
        if start <= event.day <= end:
            events.append(event)
    return events


# ---------- 財報 ----------

def parse_earnings_csv(text, watch=EARNINGS_WATCH):
    """解析 Alpha Vantage EARNINGS_CALENDAR 的 CSV。"""
    events = []
    for row in csv.DictReader(io.StringIO(text)):
        symbol = (row.get("symbol") or "").strip().upper()
        if symbol not in watch or not row.get("reportDate"):
            continue
        name, stars = watch[symbol]
        day = date.fromisoformat(row["reportDate"].strip())
        timing = (row.get("timeOfTheDay") or "").strip().lower()
        title = f"{symbol} {name} 財報"
        if "pre" in timing:
            # 美股盤前公布（時間不固定），約台灣時間當天晚上
            tw = ny_to_taipei(day, time(7, 0))
            events.append(Event(tw.date(), "晚上", title, stars, "美股盤前公布", tw))
        elif "post" in timing:
            tw = ny_to_taipei(day, time(16, 0))
            events.append(Event(tw.date(), "清晨", title, stars, f"美股 {day:%m/%d} 盤後公布", tw))
        else:
            events.append(Event(day, "", title, stars, f"美東 {day:%m/%d} 公布，盤前或盤後未定"))
    return events


def earnings_events(api_key, start, end):
    resp = requests.get(
        "https://www.alphavantage.co/query",
        params={"function": "EARNINGS_CALENDAR", "horizon": "3month", "apikey": api_key},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    text = resp.text
    if not text.lstrip().lower().startswith("symbol"):
        # 額度用完或金鑰錯誤時，Alpha Vantage 會回傳 JSON 說明
        raise ValueError(f"Alpha Vantage 回應異常：{text[:200]}")
    return [e for e in parse_earnings_csv(text) if start <= e.day <= end]


# ---------- 彙整 ----------

def collect_events(now, days=7, warn=print):
    """收集 now（台灣時間）起 days 天內的事件；個別來源失敗時呼叫 warn 並略過。"""
    today = now.date()
    end = today + timedelta(days=days)
    # 美東日期可能比台灣早一天，查詢範圍前後各多抓一天
    query_start, query_end = today - timedelta(days=1), end + timedelta(days=1)
    events = rule_events(today, end)

    sources = [("FOMC", lambda: fomc_events(query_start, query_end))]
    fred_key = os.environ.get("FRED_API_KEY", "").strip()
    if fred_key:
        sources.append(("FRED 經濟數據", lambda: fred_events(fred_key, query_start, query_end)))
    else:
        warn("警告：未設定 FRED_API_KEY，略過經濟數據公布日期")
    av_key = os.environ.get("ALPHAVANTAGE_API_KEY", "").strip()
    if av_key:
        sources.append(("財報", lambda: earnings_events(av_key, query_start, query_end)))
    else:
        warn("警告：未設定 ALPHAVANTAGE_API_KEY，略過財報日期")

    for label, func in sources:
        try:
            events += func()
        except Exception as exc:  # 單一來源失敗不影響其他事件
            warn(f"警告：{label}資料讀取失敗，略過（{exc}）")

    def upcoming(e):
        if e.at is not None:
            return now <= e.at and e.day <= end
        return today <= e.day <= end

    events = [e for e in events if upcoming(e)]
    events.sort(key=lambda e: (e.day, e.at or datetime.combine(e.day, time(0), tzinfo=TAIPEI), -e.stars))
    return events


def build_events_section(events, days=7):
    section = Section(
        "events",
        f"未來 {days} 天重大事件",
        [
            Column("日期", "text"),
            Column("台灣時間", "text"),
            Column("事件", "text"),
            Column("重要性", "text"),
            Column("備註", "text"),
        ],
        note="時間皆為台灣時間（已依美國夏令／冬令時間換算）；財報日期可能因公司調整而變動",
    )
    for e in events:
        section.rows.append([
            f"{e.day:%m/%d}（{WEEKDAYS[e.day.weekday()]}）", e.time_text or "-", e.title,
            "⭐" * e.stars, e.note or "-",
        ])
    return section


def event_lines(section):
    """推播摘要用的事件行。"""
    if section is None:
        return []
    lines = ["", f"【{section.title}】"]
    if not section.rows:
        return lines + ["（無）"]
    for day, at, title, stars, note in section.rows:
        text = f"{day} {'' if at == '-' else at + ' '}{title} {stars}"
        if note != "-":
            text += f"（{note}）"
        lines.append(text)
    return lines
