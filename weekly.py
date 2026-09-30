"""每週籌碼週報：彙總本週每日三大法人資料"""

from datetime import timedelta

from analysis import INVESTOR_GROUPS, Column, Report, Section, to_lots
from outputs import format_cell

GROUPS = ("foreign", "trust", "dealer")
GROUP_LABELS = {"foreign": "外資", "trust": "投信", "dealer": "自營商"}


def week_start(day):
    """該週週一。"""
    return day - timedelta(days=day.weekday())


def week_days(trade_date, inst_rows, history):
    """本週（週一到 trade_date）有資料的交易日：[(日期, rows)]，由舊到新。"""
    monday = week_start(trade_date)
    days = [(d, rows) for d, rows in history if monday <= d < trade_date]
    return sorted(days, key=lambda x: x[0]) + [(trade_date, inst_rows)]


def previous_trading_day(trade_date, history):
    """上週最後一個交易日（用來計算週漲跌幅）；history 不足時回傳 None。"""
    monday = week_start(trade_date)
    earlier = [d for d, _ in history if d < monday]
    return max(earlier) if earlier else None


def _daily_group_nets(rows):
    """{stock_id: {group: 買賣超股數}}"""
    nets = {}
    for row in rows:
        group = INVESTOR_GROUPS.get(row.get("name"))
        if group is None:
            continue
        entry = nets.setdefault(str(row.get("stock_id", "")), dict.fromkeys(GROUPS, 0))
        entry[group] += int(row.get("buy") or 0) - int(row.get("sell") or 0)
    return nets


class WeekChip:
    def __init__(self, stock):
        self.stock = stock  # 當日 StockChip（名稱、產業、收盤價）
        self.net = dict.fromkeys(GROUPS, 0)
        self.buy_days = dict.fromkeys(GROUPS, 0)
        self.sell_days = dict.fromkeys(GROUPS, 0)
        self.week_change_pct = None

    def amount_yi(self, shares):
        return self.stock.amount_yi(shares)


def aggregate_week(days, stocks, prev_prices=None):
    """彙總本週每檔股票的法人買賣超；stocks 為 {stock_id: StockChip}（普通股）。"""
    chips = {sid: WeekChip(s) for sid, s in stocks.items()}
    daily_totals = []
    for day, rows in days:
        totals = dict.fromkeys(GROUPS, 0.0)
        for sid, nets in _daily_group_nets(rows).items():
            chip = chips.get(sid)
            if chip is None:
                continue
            for group in GROUPS:
                chip.net[group] += nets[group]
                if nets[group] > 0:
                    chip.buy_days[group] += 1
                elif nets[group] < 0:
                    chip.sell_days[group] += 1
                totals[group] += chip.amount_yi(nets[group]) or 0
        daily_totals.append((day, totals))
    for sid, chip in chips.items():
        prev = (prev_prices or {}).get(sid)
        prev_close = float(prev.get("close") or 0) if prev else 0
        if prev_close > 0 and chip.stock.close:
            chip.week_change_pct = (chip.stock.close - prev_close) / prev_close * 100
    return chips, daily_totals


def _ranking(key, title, chips, group, top, buy_side, n_days):
    picked = [c for c in chips if (c.net[group] > 0 if buy_side else c.net[group] < 0)]
    picked.sort(key=lambda c: c.net[group], reverse=buy_side)
    section = Section(
        key,
        f"{title}（前 {top} 名）",
        [
            Column("排名", "int"),
            Column("代號", "text"),
            Column("名稱", "text"),
            Column("週買賣超(張)", "signed_int"),
            Column("估計金額(億)", "signed_yi"),
            Column("買超天數" if buy_side else "賣超天數", "int"),
            Column("週漲跌幅", "signed_pct"),
            Column("收盤", "price"),
            Column("產業", "text"),
        ],
        note=f"本週共 {n_days} 個交易日；金額以最新收盤價估算",
    )
    for rank, c in enumerate(picked[:top], 1):
        s = c.stock
        days = c.buy_days[group] if buy_side else c.sell_days[group]
        section.rows.append([
            rank, s.stock_id, s.name, to_lots(c.net[group]), c.amount_yi(c.net[group]),
            days, c.week_change_pct, s.close, s.industry,
        ])
    return section


def build_weekly_report(trade_date, days, stocks, top, prev_prices=None):
    chips_by_id, daily_totals = aggregate_week(days, stocks, prev_prices)
    chips = list(chips_by_id.values())
    n_days = len(days)
    start = days[0][0]

    overview = Section(
        "weekly_overview",
        "本週三大法人",
        [
            Column("法人", "text"),
            Column("週買賣超(張)", "signed_int"),
            Column("估計金額(億)", "signed_yi"),
        ],
        note=f"統計期間 {start.isoformat()}～{trade_date.isoformat()}（{n_days} 個交易日），"
             "上市櫃普通股，金額以最新收盤價估算",
    )
    total_lots, total_amount = 0, 0.0
    for group in GROUPS:
        lots = to_lots(sum(c.net[group] for c in chips))
        amount = sum(c.amount_yi(c.net[group]) or 0 for c in chips)
        overview.rows.append([GROUP_LABELS[group], lots, amount])
        total_lots += lots
        total_amount += amount
    overview.rows.append(["合計", total_lots, total_amount])

    daily = Section(
        "weekly_daily",
        "本週每日法人買賣超",
        [Column("日期", "text")] + [Column(f"{GROUP_LABELS[g]}(億)", "signed_yi") for g in GROUPS],
        note="金額以最新收盤價估算",
    )
    weekdays = "一二三四五六日"
    for day, totals in daily_totals:
        label = f"{day.strftime('%m/%d')}（{weekdays[day.weekday()]}）"
        daily.rows.append([label] + [totals[g] for g in GROUPS])

    industry_totals = {}
    for c in chips:
        entry = industry_totals.setdefault(c.stock.industry, [0.0, 0.0])
        entry[0] += c.amount_yi(c.net["foreign"]) or 0
        entry[1] += c.amount_yi(c.net["trust"]) or 0
    industry = Section(
        "weekly_industry",
        "產業別本週資金流向（外資＋投信）",
        [
            Column("產業", "text"),
            Column("外資(億)", "signed_yi"),
            Column("投信(億)", "signed_yi"),
            Column("合計(億)", "signed_yi"),
        ],
        note="金額以最新收盤價估算",
    )
    for name, (foreign, trust) in sorted(
        industry_totals.items(), key=lambda kv: kv[1][0] + kv[1][1], reverse=True
    ):
        industry.rows.append([name, foreign, trust, foreign + trust])

    sections = [
        daily,
        _ranking("weekly_foreign_buy", "外資週買超排行", chips, "foreign", top, True, n_days),
        _ranking("weekly_foreign_sell", "外資週賣超排行", chips, "foreign", top, False, n_days),
        _ranking("weekly_trust_buy", "投信週買超排行", chips, "trust", top, True, n_days),
        _ranking("weekly_trust_sell", "投信週賣超排行", chips, "trust", top, False, n_days),
        industry,
    ]

    all_stocks = Section(
        "weekly_all",
        "全部個股",
        [
            Column("代號", "text"),
            Column("名稱", "text"),
            Column("產業", "text"),
            Column("收盤", "price"),
            Column("週漲跌幅", "signed_pct"),
            Column("外資週買賣超(張)", "signed_int"),
            Column("外資買超天數", "int"),
            Column("投信週買賣超(張)", "signed_int"),
            Column("投信買超天數", "int"),
            Column("自營商週買賣超(張)", "signed_int"),
        ],
    )
    for c in sorted(chips, key=lambda c: c.stock.stock_id):
        s = c.stock
        all_stocks.rows.append([
            s.stock_id, s.name, s.industry, s.close, c.week_change_pct,
            to_lots(c.net["foreign"]), c.buy_days["foreign"],
            to_lots(c.net["trust"]), c.buy_days["trust"],
            to_lots(c.net["dealer"]),
        ])

    title = f"台股每週籌碼週報 {start.strftime('%m/%d')}～{trade_date.strftime('%m/%d')}"
    return Report(trade_date, overview, sections, all_stocks, title=title)


def build_weekly_summary(report, top=5, report_url=None):
    """週報推播摘要（純文字）。"""
    lines = [f"📅 {report.title}", "", "【本週三大法人】"]
    for label, lots, amount in report.overview.rows:
        lines.append(f"{label} {format_cell(amount, 'signed_yi')} 億（{format_cell(lots, 'signed_int')} 張）")

    by_key = {s.key: s for s in report.sections}
    for key, label, side in (("weekly_foreign_buy", "外資週買超", "買超"),
                             ("weekly_foreign_sell", "外資週賣超", "賣超"),
                             ("weekly_trust_buy", "投信週買超", "買超")):
        section = by_key[key]
        lines += ["", f"【{label}】"]
        if not section.rows:
            lines.append("（無）")
            continue
        lots_i, days_i = section.col("週買賣超(張)"), section.col(f"{side}天數")
        for row in section.rows[:top]:
            lines.append(
                f"{row[0]}. {row[1]} {row[2]} {format_cell(row[lots_i], 'signed_int')} 張"
                f"（{side} {row[days_i]} 天）"
            )

    industry = by_key["weekly_industry"].rows
    inflow = [r for r in industry if r[3] > 0][:3]
    outflow = [r for r in reversed(industry) if r[3] < 0][:3]
    lines += ["", "【資金流入產業】"]
    lines += [f"{r[0]} {format_cell(r[3], 'signed_yi')} 億" for r in inflow] or ["（無）"]
    lines += ["", "【資金流出產業】"]
    lines += [f"{r[0]} {format_cell(r[3], 'signed_yi')} 億" for r in outflow] or ["（無）"]

    if report_url:
        lines += ["", f"完整週報：{report_url}"]
    return "\n".join(lines)
