"""把 HTML 報告發布到 GitHub Pages 網站資料夾，並重建首頁的報告列表

使用方式：
    python pages.py 網站資料夾 reports/chip_report_YYYY-MM-DD.html
    python pages.py 網站資料夾 reports/weekly_report_YYYY-MM-DD.html   # 週報，發布為 weekly-YYYY-MM-DD.html
"""

import re
import sys
from datetime import date, timedelta
from pathlib import Path

from outputs import HTML_STYLE

REPORT_NAME = re.compile(r"(chip|weekly)_report_(\d{4}-\d{2}-\d{2})\.html$")
PAGE_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})\.html$")
WEEKLY_PAGE_NAME = re.compile(r"^weekly-(\d{4}-\d{2}-\d{2})\.html$")
WEEKDAYS = "一二三四五六日"

INDEX_STYLE = """
ul.reports { list-style: none; margin: 0; padding: 0; }
ul.reports li { border-bottom: 1px solid var(--border); }
ul.reports li:last-child { border-bottom: 0; }
ul.reports a {
  display: flex; justify-content: space-between; padding: 12px 4px;
  color: var(--text); text-decoration: none;
}
ul.reports a:hover { background: var(--head); }
.badge { color: var(--up); font-size: 12px; }
h2.list-title { font-size: 16px; margin: 0 0 4px; }
"""

BACK_LINK = '<p class="subtitle"><a href="index.html" style="color: inherit">← 所有報告</a></p>\n'


def _list_items(dates, prefix, label):
    items = []
    for i, day in enumerate(dates):
        badge = '<span class="badge">最新</span>' if i == 0 else ""
        items.append(f'<li><a href="{prefix}{day}.html"><span>{label(day)}</span>{badge}</a></li>')
    return "\n".join(items) or "<li>（尚無報告）</li>"


def _daily_label(day):
    return f"{day}（{WEEKDAYS[date.fromisoformat(day).weekday()]}）"


def _weekly_label(day):
    end = date.fromisoformat(day)
    start = end - timedelta(days=end.weekday())
    return f"{start.strftime('%m/%d')}～{end.strftime('%m/%d')} 週報"


def render_index(dates, weekly_dates=()):
    """報告列表首頁；dates、weekly_dates 為由新到舊的日期字串。"""
    weekly_block = ""
    if weekly_dates:
        weekly_block = f"""<section>
<h2 class="list-title">每週週報</h2>
<ul class="reports">
{_list_items(weekly_dates, "weekly-", _weekly_label)}
</ul>
</section>
"""
    return f"""<!doctype html>
<html lang="zh-Hant-TW">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>台股籌碼報告</title>
<style>{HTML_STYLE}{INDEX_STYLE}</style>
</head>
<body>
<main>
<h1>台股每日籌碼報告</h1>
<p class="subtitle">資料來源：FinMind｜共 {len(dates)} 份日報、{len(weekly_dates)} 份週報</p>
{weekly_block}<section>
<h2 class="list-title">每日報告</h2>
<ul class="reports">
{_list_items(dates, "", _daily_label)}
</ul>
</section>
</main>
</body>
</html>
"""


def publish(site_dir, report_path):
    """複製報告到網站資料夾並重建首頁，回傳日期字串。

    日報發布為 YYYY-MM-DD.html，週報發布為 weekly-YYYY-MM-DD.html。
    """
    site_dir, report_path = Path(site_dir), Path(report_path)
    match = REPORT_NAME.search(report_path.name)
    if not match:
        raise ValueError(
            f"檔名格式不符（應為 chip_report_ 或 weekly_report_YYYY-MM-DD.html）：{report_path.name}"
        )
    kind, day = match.group(1), match.group(2)
    page_name = f"weekly-{day}.html" if kind == "weekly" else f"{day}.html"

    site_dir.mkdir(parents=True, exist_ok=True)
    page = report_path.read_text(encoding="utf-8").replace("<main>\n", "<main>\n" + BACK_LINK, 1)
    (site_dir / page_name).write_text(page, encoding="utf-8")
    # 關閉 GitHub Pages 的 Jekyll 處理，直接提供靜態檔案
    (site_dir / ".nojekyll").touch()

    names = [p.name for p in site_dir.iterdir()]
    dates = sorted((m.group(1) for n in names if (m := PAGE_NAME.match(n))), reverse=True)
    weekly_dates = sorted((m.group(1) for n in names if (m := WEEKLY_PAGE_NAME.match(n))), reverse=True)
    (site_dir / "index.html").write_text(render_index(dates, weekly_dates), encoding="utf-8")
    return day


def main(argv):
    if len(argv) != 3:
        print("用法：python pages.py 網站資料夾 報告檔.html", file=sys.stderr)
        return 1
    day = publish(argv[1], argv[2])
    print(f"已發布 {day} 報告到 {argv[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
