"""籌碼資料彙總與報告區塊建立"""

from dataclasses import dataclass, field

# FinMind 三大法人資料中的法人名稱
INVESTOR_GROUPS = {
    "Foreign_Investor": "foreign",  # 外資及陸資
    "Foreign_Dealer_Self": "foreign",  # 外資自營商
    "Investment_Trust": "trust",  # 投信
    "Dealer_self": "dealer",  # 自營商（自行買賣）
    "Dealer_Hedging": "dealer",  # 自營商（避險）
}


@dataclass
class StockChip:
    stock_id: str
    name: str
    market: str
    industry: str
    close: float = None
    change_pct: float = None
    volume: int = 0  # 成交股數
    buy: dict = field(default_factory=lambda: {"foreign": 0, "trust": 0, "dealer": 0})
    sell: dict = field(default_factory=lambda: {"foreign": 0, "trust": 0, "dealer": 0})
    # 連續買賣超天數：正數為連買、負數為連賣；streak_net 為連續期間累計買賣超股數
    streak: dict = field(default_factory=dict)
    streak_net: dict = field(default_factory=dict)

    def net(self, group):
        """買賣超股數。"""
        return self.buy[group] - self.sell[group]

    def amount_yi(self, shares):
        """以收盤價估算金額（億元）；無股價時回傳 None。"""
        if not self.close:
            return None
        return shares * self.close / 1e8

    def volume_pct(self, shares):
        """佔當日成交量百分比；無成交量時回傳 None。"""
        if not self.volume:
            return None
        return abs(shares) / self.volume * 100


@dataclass
class Column:
    header: str
    # text / int / signed_int / price / pct / signed_pct / signed_yi
    kind: str


@dataclass
class Section:
    key: str
    title: str
    columns: list
    rows: list = field(default_factory=list)
    note: str = ""

    def col(self, header):
        return [c.header for c in self.columns].index(header)


@dataclass
class Report:
    trade_date: object
    overview: Section
    sections: list
    all_stocks: Section


def to_lots(shares):
    """股數換算成張數（1 張 = 1000 股），四捨五入。"""
    return round(shares / 1000)


def build_stocks(inst_rows, prices, stock_info):
    """合併法人買賣、股價與股票基本資料，回傳 {stock_id: StockChip}。"""
    stocks = {}
    for row in inst_rows:
        stock_id = str(row.get("stock_id", ""))
        group = INVESTOR_GROUPS.get(row.get("name"))
        if stock_id not in stock_info or group is None:
            continue
        stock = stocks.get(stock_id)
        if stock is None:
            info = stock_info[stock_id]
            stock = StockChip(stock_id, info["name"], info["market"], info["industry"])
            price = prices.get(stock_id)
            if price:
                stock.close = float(price.get("close") or 0) or None
                stock.volume = int(price.get("Trading_Volume") or 0)
                spread = float(price.get("spread") or 0)
                prev_close = (stock.close or 0) - spread
                if stock.close and prev_close > 0:
                    stock.change_pct = spread / prev_close * 100
            stocks[stock_id] = stock
        stock.buy[group] += int(row.get("buy") or 0)
        stock.sell[group] += int(row.get("sell") or 0)
    return stocks


STREAK_GROUPS = ("foreign", "trust")


def daily_nets(rows):
    """單日法人資料換算成 {stock_id: {"foreign": 買賣超股數, "trust": 買賣超股數}}。"""
    nets = {}
    for row in rows:
        group = INVESTOR_GROUPS.get(row.get("name"))
        if group not in STREAK_GROUPS:
            continue
        entry = nets.setdefault(str(row.get("stock_id", "")), {g: 0 for g in STREAK_GROUPS})
        entry[group] += int(row.get("buy") or 0) - int(row.get("sell") or 0)
    return nets


def apply_streaks(stocks, history):
    """依今日與歷史資料（由近到遠）計算外資、投信連續買賣超天數。"""
    past = [daily_nets(rows) for _, rows in history]
    for s in stocks.values():
        for group in STREAK_GROUPS:
            today = s.net(group)
            if today == 0:
                s.streak[group], s.streak_net[group] = 0, 0
                continue
            sign = 1 if today > 0 else -1
            days, total = 1, today
            for nets in past:
                net = nets.get(s.stock_id, {}).get(group, 0)
                if net * sign <= 0:
                    break
                days += 1
                total += net
            s.streak[group], s.streak_net[group] = sign * days, total


STOCK_COLUMNS = [
    Column("排名", "int"),
    Column("代號", "text"),
    Column("名稱", "text"),
    Column("產業", "text"),
    Column("市場", "text"),
    Column("收盤", "price"),
    Column("漲跌幅", "signed_pct"),
]


def _stock_cells(rank, s):
    return [rank, s.stock_id, s.name, s.industry, s.market, s.close, s.change_pct]


def _sort_value(stock, shares, rank_by):
    if rank_by == "amount":
        amount = stock.amount_yi(shares)
        return amount if amount is not None else 0
    return shares


def build_ranking(key, title, stocks, group, top, buy_side, rank_by, with_streak=False):
    """法人買超（buy_side=True）或賣超排行。"""
    candidates = [s for s in stocks if (s.net(group) > 0 if buy_side else s.net(group) < 0)]
    candidates.sort(key=lambda s: _sort_value(s, s.net(group), rank_by), reverse=buy_side)
    section = Section(
        key,
        f"{title}（前 {top} 名）",
        STOCK_COLUMNS
        + [
            Column("買賣超(張)", "signed_int"),
            Column("金額(億)", "signed_yi"),
            Column("佔成交量", "pct"),
        ],
    )
    if with_streak:
        section.columns.append(Column("連買天數" if buy_side else "連賣天數", "int"))
    for rank, s in enumerate(candidates[:top], 1):
        net = s.net(group)
        row = _stock_cells(rank, s) + [to_lots(net), s.amount_yi(net), s.volume_pct(net)]
        if with_streak:
            row.append(abs(s.streak.get(group, 0)))
        section.rows.append(row)
    return section


def build_sync_buy(stocks, top, rank_by):
    """外資與投信同步買超。"""
    candidates = [s for s in stocks if s.net("foreign") > 0 and s.net("trust") > 0]

    def combined(s):
        return s.net("foreign") + s.net("trust")

    candidates.sort(key=lambda s: _sort_value(s, combined(s), rank_by), reverse=True)
    section = Section(
        "sync_buy",
        f"外資投信同步買超（前 {top} 名）",
        STOCK_COLUMNS
        + [
            Column("外資(張)", "signed_int"),
            Column("投信(張)", "signed_int"),
            Column("合計金額(億)", "signed_yi"),
            Column("合計佔成交量", "pct"),
        ],
    )
    for rank, s in enumerate(candidates[:top], 1):
        section.rows.append(
            _stock_cells(rank, s)
            + [
                to_lots(s.net("foreign")),
                to_lots(s.net("trust")),
                s.amount_yi(combined(s)),
                s.volume_pct(combined(s)),
            ]
        )
    return section


def build_streak(key, title, stocks, group, top, min_days, window, rank_by):
    """法人連續買超排行：連買天數達 min_days 以上，依天數、累計買超排序。"""
    candidates = [s for s in stocks if s.streak.get(group, 0) >= min_days]
    candidates.sort(
        key=lambda s: (s.streak[group], _sort_value(s, s.streak_net[group], rank_by)),
        reverse=True,
    )
    section = Section(
        key,
        f"{title}（連買 {min_days} 天以上，前 {top} 名）",
        # 連買天數與累計數字放前面，手機不用左右滑動就看得到
        [
            Column("排名", "int"),
            Column("代號", "text"),
            Column("名稱", "text"),
            Column("連買天數", "int"),
            Column("累計買超(張)", "signed_int"),
            Column("累計金額(億)", "signed_yi"),
            Column("今日買超(張)", "signed_int"),
            Column("收盤", "price"),
            Column("漲跌幅", "signed_pct"),
            Column("產業", "text"),
            Column("市場", "text"),
        ],
        note=(
            f"最多回溯 {window} 個交易日，天數為 {window} 表示至少連買 {window} 天；"
            "累計金額以今日收盤價估算"
        ),
    )
    for rank, s in enumerate(candidates[:top], 1):
        total = s.streak_net[group]
        section.rows.append(
            [
                rank, s.stock_id, s.name,
                s.streak[group], to_lots(total), s.amount_yi(total), to_lots(s.net(group)),
                s.close, s.change_pct, s.industry, s.market,
            ]
        )
    return section


def build_industry(stocks):
    """產業別外資、投信淨買賣金額彙總，依合計金額排序。"""
    totals = {}
    for s in stocks:
        entry = totals.setdefault(s.industry, [0.0, 0.0])
        entry[0] += s.amount_yi(s.net("foreign")) or 0
        entry[1] += s.amount_yi(s.net("trust")) or 0
    ordered = sorted(totals.items(), key=lambda kv: kv[1][0] + kv[1][1], reverse=True)
    section = Section(
        "industry",
        "產業別法人淨買賣（外資＋投信）",
        [
            Column("產業", "text"),
            Column("外資(億)", "signed_yi"),
            Column("投信(億)", "signed_yi"),
            Column("合計(億)", "signed_yi"),
        ],
        note="金額以個股收盤價估算",
    )
    for industry, (foreign, trust) in ordered:
        section.rows.append([industry, foreign, trust, foreign + trust])
    return section


def build_overview(stocks):
    """三大法人當日合計買賣超。"""
    section = Section(
        "overview",
        "全市場總覽",
        [
            Column("法人", "text"),
            Column("買賣超(張)", "signed_int"),
            Column("估計金額(億)", "signed_yi"),
        ],
        note="統計範圍為上市櫃普通股，金額以個股收盤價估算",
    )
    total_lots, total_amount = 0, 0.0
    for label, group in (("外資", "foreign"), ("投信", "trust"), ("自營商", "dealer")):
        shares = sum(s.net(group) for s in stocks)
        amount = sum(s.amount_yi(s.net(group)) or 0 for s in stocks)
        section.rows.append([label, to_lots(shares), amount])
        total_lots += to_lots(shares)
        total_amount += amount
    section.rows.append(["合計", total_lots, total_amount])
    return section


def build_all_stocks(stocks, with_streak=False):
    """全部個股明細（供 Excel 篩選用）。"""
    section = Section(
        "all",
        "全部個股",
        [
            Column("代號", "text"),
            Column("名稱", "text"),
            Column("產業", "text"),
            Column("市場", "text"),
            Column("收盤", "price"),
            Column("漲跌幅", "signed_pct"),
            Column("成交量(張)", "int"),
            Column("外資買進(張)", "int"),
            Column("外資賣出(張)", "int"),
            Column("外資買賣超(張)", "signed_int"),
            Column("外資金額(億)", "signed_yi"),
            Column("投信買進(張)", "int"),
            Column("投信賣出(張)", "int"),
            Column("投信買賣超(張)", "signed_int"),
            Column("投信金額(億)", "signed_yi"),
            Column("自營商買賣超(張)", "signed_int"),
        ],
    )
    if with_streak:
        section.columns += [Column("外資連續天數", "signed_int"), Column("投信連續天數", "signed_int")]
        section.note = "連續天數：正數為連買、負數為連賣"
    for s in sorted(stocks, key=lambda s: s.stock_id):
        row = [
            s.stock_id, s.name, s.industry, s.market, s.close, s.change_pct,
            to_lots(s.volume),
            to_lots(s.buy["foreign"]), to_lots(s.sell["foreign"]),
            to_lots(s.net("foreign")), s.amount_yi(s.net("foreign")),
            to_lots(s.buy["trust"]), to_lots(s.sell["trust"]),
            to_lots(s.net("trust")), s.amount_yi(s.net("trust")),
            to_lots(s.net("dealer")),
        ]
        if with_streak:
            row += [s.streak.get("foreign", 0), s.streak.get("trust", 0)]
        section.rows.append(row)
    return section


def build_report(trade_date, stocks, top, rank_by="lots", streak_window=None, streak_min=3):
    """streak_window 為連續天數的回溯交易日數（含今日）；None 表示不計算連續天數。"""
    stocks = list(stocks.values()) if isinstance(stocks, dict) else list(stocks)
    streak = streak_window is not None
    sections = [
        build_ranking("foreign_buy", "外資買超排行", stocks, "foreign", top, True, rank_by, streak),
        build_ranking("foreign_sell", "外資賣超排行", stocks, "foreign", top, False, rank_by, streak),
        build_ranking("trust_buy", "投信買超排行", stocks, "trust", top, True, rank_by, streak),
        build_ranking("trust_sell", "投信賣超排行", stocks, "trust", top, False, rank_by, streak),
        build_sync_buy(stocks, top, rank_by),
    ]
    if streak:
        sections += [
            build_streak("foreign_streak", "外資連續買超", stocks, "foreign", top,
                         streak_min, streak_window, rank_by),
            build_streak("trust_streak", "投信連續買超", stocks, "trust", top,
                         streak_min, streak_window, rank_by),
        ]
    sections.append(build_industry(stocks))
    return Report(trade_date, build_overview(stocks), sections, build_all_stocks(stocks, streak))
