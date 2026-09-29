"""把 HTML 報告發布到 GitHub Pages 網站資料夾，並重建首頁的報告列表

使用方式：
    python pages.py 網站資料夾 reports/chip_report_YYYY-MM-DD.html
"""

import re
import sys
from datetime import date
from pathlib import Path

from outputs import HTML_STYLE

REPORT_NAME = re.compile(r"chip_report_(\d{4}-\d{2}-\d{2})\.html$")
PAGE_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})\.html$")
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
"""

BACK_LINK = '<p class="subtitle"><a href="index.html" style="color: inherit">← 所有報告</a></p>\n'


def render_index(dates):
    """報告列表首頁；dates 為由新到舊的日期字串。"""
    items = []
    for i, day in enumerate(dates):
        weekday = WEEKDAYS[date.fromisoformat(day).weekday()]
        badge = '<span class="badge">最新</span>' if i == 0 else ""
        items.append(
            f'<li><a href="{day}.html"><span>{day}（{weekday}）</span>{badge}</a></li>'
        )
    body = "\n".join(items) or "<li>（尚無報告）</li>"
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
<p class="subtitle">資料來源：FinMind｜共 {len(dates)} 份報告</p>
<section>
<ul class="reports">
{body}
</ul>
</section>
</main>
</body>
</html>
"""


def publish(site_dir, report_path):
    """複製報告到網站資料夾（檔名為 YYYY-MM-DD.html）並重建首頁，回傳日期字串。"""
    site_dir, report_path = Path(site_dir), Path(report_path)
    match = REPORT_NAME.search(report_path.name)
    if not match:
        raise ValueError(f"檔名格式不符（應為 chip_report_YYYY-MM-DD.html）：{report_path.name}")
    day = match.group(1)

    site_dir.mkdir(parents=True, exist_ok=True)
    page = report_path.read_text(encoding="utf-8").replace("<main>\n", "<main>\n" + BACK_LINK, 1)
    (site_dir / f"{day}.html").write_text(page, encoding="utf-8")
    # 關閉 GitHub Pages 的 Jekyll 處理，直接提供靜態檔案
    (site_dir / ".nojekyll").touch()

    dates = sorted(
        (m.group(1) for p in site_dir.iterdir() if (m := PAGE_NAME.match(p.name))),
        reverse=True,
    )
    (site_dir / "index.html").write_text(render_index(dates), encoding="utf-8")
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
