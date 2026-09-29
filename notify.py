"""推播報告摘要到 Telegram / LINE"""

import os
import sys
from pathlib import Path

import requests

from outputs import format_cell

TIMEOUT = 30
SUMMARY_SECTIONS = {
    "foreign_buy": ("外資買超", "買賣超(張)", "金額(億)"),
    "foreign_sell": ("外資賣超", "買賣超(張)", "金額(億)"),
    "trust_buy": ("投信買超", "買賣超(張)", "金額(億)"),
    "sync_buy": ("外資投信同步買超", "外資(張)", "合計金額(億)"),
}


STREAK_SECTIONS = {
    "foreign_streak": "外資連買",
    "trust_streak": "投信連買",
}


def build_summary(report, top=5, report_url=None):
    """產生推播用純文字摘要；report_url 為完整報告網址（選用）。"""
    lines = [f"📊 台股籌碼報告 {report.trade_date.isoformat()}", "", "【三大法人】"]
    ov = report.overview
    for row in ov.rows:
        label, lots, amount = row
        lines.append(f"{label} {format_cell(amount, 'signed_yi')} 億（{format_cell(lots, 'signed_int')} 張）")

    by_key = {s.key: s for s in report.sections}
    for key, (label, lots_header, amount_header) in SUMMARY_SECTIONS.items():
        section = by_key.get(key)
        if section is None:
            continue
        lines += ["", f"【{label}】"]
        if not section.rows:
            lines.append("（無資料）")
            continue
        id_i, name_i = section.col("代號"), section.col("名稱")
        lots_i, amount_i = section.col(lots_header), section.col(amount_header)
        trust_i = section.col("投信(張)") if key == "sync_buy" else None
        for row in section.rows[:top]:
            lots = f"{format_cell(row[lots_i], 'signed_int')} 張"
            if trust_i is not None:
                lots = (
                    f"外資 {format_cell(row[lots_i], 'signed_int')}／"
                    f"投信 {format_cell(row[trust_i], 'signed_int')} 張"
                )
            amount = row[amount_i]
            amount_text = "" if amount is None else f"（{format_cell(amount, 'signed_yi')} 億）"
            lines.append(f"{row[0]}. {row[id_i]} {row[name_i]} {lots}{amount_text}")

    for key, label in STREAK_SECTIONS.items():
        section = by_key.get(key)
        if section is None:
            continue
        lines += ["", f"【{label}】"]
        if not section.rows:
            lines.append("（無資料）")
            continue
        id_i, name_i = section.col("代號"), section.col("名稱")
        days_i, total_i = section.col("連買天數"), section.col("累計買超(張)")
        for row in section.rows[:top]:
            lines.append(
                f"{row[0]}. {row[id_i]} {row[name_i]} 連 {row[days_i]} 天"
                f"（累計 {format_cell(row[total_i], 'signed_int')} 張）"
            )

    if report_url:
        lines += ["", f"完整報告：{report_url}"]
    return "\n".join(lines)


def send_telegram(bot_token, chat_id, text):
    resp = requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={"chat_id": chat_id, "text": text[:4096]},
        timeout=TIMEOUT,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Telegram 推播失敗（HTTP {resp.status_code}）：{resp.text[:200]}")


def send_line(channel_token, user_id, text):
    resp = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={"Authorization": f"Bearer {channel_token}"},
        json={"to": user_id, "messages": [{"type": "text", "text": text[:5000]}]},
        timeout=TIMEOUT,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"LINE 推播失敗（HTTP {resp.status_code}）：{resp.text[:200]}")


def configured_channels():
    """回傳已設定好環境變數的推播管道：[(名稱, 發送函式)]。"""
    channels = []
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if tg_token and tg_chat:
        channels.append(("Telegram", lambda text: send_telegram(tg_token, tg_chat, text)))
    line_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
    line_user = os.environ.get("LINE_USER_ID", "").strip()
    if line_token and line_user:
        channels.append(("LINE", lambda text: send_line(line_token, line_user, text)))
    return channels


def send_all(channels, text):
    """發送到所有管道，回傳是否全部成功。"""
    ok = True
    for name, send in channels:
        try:
            send(text)
            print(f"已推播到 {name}")
        except Exception as exc:  # 單一管道失敗不影響其他管道
            print(f"錯誤：{exc}", file=sys.stderr)
            ok = False
    return ok


def main(argv):
    """推播已產生的摘要檔：python notify.py 摘要檔路徑"""
    if len(argv) != 2:
        print("用法：python notify.py 摘要檔路徑", file=sys.stderr)
        return 1
    channels = configured_channels()
    if not channels:
        print(
            "錯誤：需設定 TELEGRAM_BOT_TOKEN＋TELEGRAM_CHAT_ID，"
            "或 LINE_CHANNEL_ACCESS_TOKEN＋LINE_USER_ID。",
            file=sys.stderr,
        )
        return 1
    text = Path(argv[1]).read_text(encoding="utf-8")
    return 0 if send_all(channels, text) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
