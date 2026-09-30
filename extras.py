"""籌碼延伸區塊：高股息 ETF、期貨選擇權、融資融券、千張大戶持股"""

from analysis import Column, Section, to_lots

# 預設追蹤的高股息 ETF
DEFAULT_ETFS = (
    "0056", "00878", "00919", "00929", "00713",
    "00915", "00918", "00934", "00939", "00940",
)


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def investor_label(value):
    """法人身分別統一成 外資／投信／自營商。"""
    text = str(value or "")
    if "外資" in text or "Foreign" in text:
        return "外資"
    if "投信" in text or "Trust" in text:
        return "投信"
    if "自營" in text or "Dealer" in text:
        return "自營商"
    return None


def call_put_label(value):
    """買賣權統一成 call／put。"""
    text = str(value or "").strip().lower()
    if text in ("call", "c") or "買" in text:
        return "call"
    if text in ("put", "p") or "賣" in text:
        return "put"
    return None


# ---------- 高股息 ETF ----------

def build_etf_section(etfs, order, with_streak=False):
    """高股息 ETF 法人買賣超；etfs 為 {代號: StockChip}，order 為設定的代號順序。"""
    section = Section(
        "etf",
        "高股息 ETF 法人買賣超",
        [
            Column("代號", "text"),
            Column("名稱", "text"),
            Column("三大法人(張)", "signed_int"),
            Column("外資(張)", "signed_int"),
            Column("投信(張)", "signed_int"),
            Column("自營商(張)", "signed_int"),
            Column("收盤", "price"),
            Column("漲跌幅", "signed_pct"),
            Column("成交量(張)", "int"),
        ],
        note="依三大法人合計買賣超排序；ETF 的自營商買賣多為造市避險，參考價值較低",
    )
    if with_streak:
        section.columns.append(Column("外資連續天數", "signed_int"))
        section.note += "；外資連續天數正數為連買、負數為連賣"

    def total(s):
        return s.net("foreign") + s.net("trust") + s.net("dealer")

    listed = [etfs[i] for i in order if i in etfs]
    listed.sort(key=total, reverse=True)
    for s in listed:
        row = [
            s.stock_id, s.name, to_lots(total(s)),
            to_lots(s.net("foreign")), to_lots(s.net("trust")), to_lots(s.net("dealer")),
            s.close, s.change_pct, to_lots(s.volume),
        ]
        if with_streak:
            row.append(s.streak.get("foreign", 0))
        section.rows.append(row)
    return section


# ---------- 期貨選擇權 ----------

def _oi_by_date(rows, key=None):
    """{日期: {(key值, 法人): [多方未平倉, 空方未平倉]}}"""
    result = {}
    for row in rows:
        investor = investor_label(row.get("institutional_investors"))
        if investor is None:
            continue
        group = key(row) if key else None
        if key and group is None:
            continue
        entry = result.setdefault(str(row.get("date")), {}).setdefault((group, investor), [0, 0])
        entry[0] += int(_num(row.get("long_open_interest_balance_volume")))
        entry[1] += int(_num(row.get("short_open_interest_balance_volume")))
    return result


def put_call_ratio(option_daily_rows):
    """以未平倉量計算 Put/Call Ratio（%）；只取一般交易時段。"""
    totals = {"call": 0, "put": 0}
    for row in option_daily_rows:
        session = row.get("trading_session")
        if session not in (None, "", "position"):
            continue
        cp = call_put_label(row.get("call_put"))
        if cp:
            totals[cp] += int(_num(row.get("open_interest")))
    if not totals["call"]:
        return None
    return totals["put"] / totals["call"] * 100


def build_futures_section(trade_date, futures_rows, option_rows=(), pc_today=None, pc_prev=None):
    """台指期與台指選擇權法人未平倉。"""
    section = Section(
        "futures",
        "期貨選擇權籌碼",
        [
            Column("項目", "text"),
            Column("淨未平倉(口)", "signed_int"),
            Column("日增減(口)", "signed_int"),
            Column("多方未平倉(口)", "int"),
            Column("空方未平倉(口)", "int"),
        ],
    )
    notes = []

    def add_rows(by_date, items):
        dates = sorted(by_date)
        if not dates:
            return None
        latest = by_date[dates[-1]]
        prev = by_date[dates[-2]] if len(dates) > 1 else {}
        for label, key in items:
            if key not in latest:
                continue
            long_oi, short_oi = latest[key]
            net = long_oi - short_oi
            change = net - (prev[key][0] - prev[key][1]) if key in prev else None
            section.rows.append([label, net, change, long_oi, short_oi])
        return dates[-1]

    futures_date = add_rows(
        _oi_by_date(futures_rows),
        [(f"{inv}台指期", (None, inv)) for inv in ("外資", "投信", "自營商")],
    )
    if option_rows and "call_put" in option_rows[0]:
        add_rows(
            _oi_by_date(option_rows, key=lambda r: call_put_label(r.get("call_put"))),
            [("外資台指買權", ("call", "外資")), ("外資台指賣權", ("put", "外資"))],
        )
    if futures_date and futures_date != trade_date.isoformat():
        notes.append(f"期貨資料日期為 {futures_date}")
    if pc_today is not None:
        text = f"選擇權未平倉 Put/Call Ratio：{pc_today:.2f}%"
        if pc_prev is not None:
            text += f"（前一交易日 {pc_prev:.2f}%）"
        notes.append(text)
    notes.append("淨未平倉＝多方－空方，正數偏多、負數偏空")
    section.note = "；".join(notes)
    section.meta["pc_ratio"] = (pc_today, pc_prev)
    return section


# ---------- 融資融券 ----------

def build_margin_sections(stocks, margin, top):
    """融資增加、融資減少、融券增加排行；stocks 為普通股 StockChip 清單。"""
    items = []
    for s in stocks:
        row = margin.get(s.stock_id)
        if not row:
            continue
        m_bal = int(_num(row.get("MarginPurchaseTodayBalance")))
        m_chg = m_bal - int(_num(row.get("MarginPurchaseYesterdayBalance")))
        s_bal = int(_num(row.get("ShortSaleTodayBalance")))
        s_chg = s_bal - int(_num(row.get("ShortSaleYesterdayBalance")))
        ratio = s_bal / m_bal * 100 if m_bal else None
        items.append((s, m_chg, m_bal, s_chg, s_bal, ratio))

    columns = [
        Column("排名", "int"),
        Column("代號", "text"),
        Column("名稱", "text"),
        Column("融資增減(張)", "signed_int"),
        Column("融資餘額(張)", "int"),
        Column("融券增減(張)", "signed_int"),
        Column("融券餘額(張)", "int"),
        Column("券資比", "pct"),
        Column("外資(張)", "signed_int"),
        Column("收盤", "price"),
        Column("漲跌幅", "signed_pct"),
    ]
    total_m = sum(i[1] for i in items)
    total_s = sum(i[3] for i in items)
    market_note = f"上市櫃普通股合計：融資 {total_m:+,} 張、融券 {total_s:+,} 張"

    specs = [
        ("margin_up", "融資增加排行", 1, True),
        ("margin_down", "融資減少排行", 1, False),
        ("short_up", "融券增加排行", 3, True),
    ]
    sections = []
    for key, title, idx, increase in specs:
        picked = [i for i in items if (i[idx] > 0 if increase else i[idx] < 0)]
        picked.sort(key=lambda i: i[idx], reverse=increase)
        section = Section(key, f"{title}（前 {top} 名）", list(columns), note=market_note)
        for rank, (s, m_chg, m_bal, s_chg, s_bal, ratio) in enumerate(picked[:top], 1):
            section.rows.append([
                rank, s.stock_id, s.name, m_chg, m_bal, s_chg, s_bal, ratio,
                to_lots(s.net("foreign")), s.close, s.change_pct,
            ])
        sections.append(section)
    return sections


# ---------- 千張大戶 ----------

def _is_big_holder(level):
    """持股 1,000,001 股以上（超過 1,000 張）的分級。"""
    return "1,000,001" in str(level).replace(" ", "")


def _is_total(level):
    text = str(level).lower()
    return "total" in text or "合計" in text


def holder_stats(rows):
    """{stock_id: (千張大戶持股比例%, 總股東人數)}"""
    stats = {}
    for row in rows:
        level = row.get("HoldingSharesLevel")
        entry = stats.setdefault(str(row.get("stock_id", "")), [0.0, None])
        if _is_big_holder(level):
            entry[0] += _num(row.get("percent"))
        elif _is_total(level):
            entry[1] = int(_num(row.get("people")))
    return {k: tuple(v) for k, v in stats.items()}


def build_holder_sections(stocks, weeks, top):
    """千張大戶持股比例週增加、週減少排行；weeks 為 [(日期, rows), (前一週日期, rows)]。"""
    (day, rows), (prev_day, prev_rows) = weeks[0], weeks[1]
    now, prev = holder_stats(rows), holder_stats(prev_rows)
    items = []
    for s in stocks:
        if s.stock_id not in now or s.stock_id not in prev:
            continue
        pct, people = now[s.stock_id]
        prev_pct, prev_people = prev[s.stock_id]
        people_chg = people - prev_people if people is not None and prev_people is not None else None
        items.append((s, pct, pct - prev_pct, people, people_chg))

    columns = [
        Column("排名", "int"),
        Column("代號", "text"),
        Column("名稱", "text"),
        Column("週增減(百分點)", "signed_float"),
        Column("千張大戶持股", "pct"),
        Column("股東人數", "int"),
        Column("人數增減", "signed_int"),
        Column("收盤", "price"),
        Column("漲跌幅", "signed_pct"),
    ]
    note = (
        f"集保資料日期 {day.isoformat()}（與前一週 {prev_day.isoformat()} 比較），每週更新一次；"
        "千張大戶指持股超過 1,000 張的股東；股東人數減少通常代表籌碼集中"
    )
    sections = []
    for key, title, increase in (("holder_up", "千張大戶持股增加", True),
                                 ("holder_down", "千張大戶持股減少", False)):
        picked = [i for i in items if (i[2] > 0 if increase else i[2] < 0)]
        picked.sort(key=lambda i: i[2], reverse=increase)
        section = Section(key, f"{title}（前 {top} 名）", list(columns), note=note)
        for rank, (s, pct, change, people, people_chg) in enumerate(picked[:top], 1):
            section.rows.append([
                rank, s.stock_id, s.name, change, pct, people, people_chg, s.close, s.change_pct,
            ])
        sections.append(section)
    return sections
