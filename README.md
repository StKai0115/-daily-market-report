# 台股每日籌碼報告

使用 [FinMind API](https://finmindtrade.com/) 抓取三大法人買賣資料，產生台股每日籌碼報告。

## 報告內容

| 區塊 | 說明 |
|---|---|
| 全市場總覽 | 外資、投信、自營商當日合計買賣超（張數與估計金額） |
| 外資買超排行 | |
| 外資賣超排行 | |
| 投信買超排行 | |
| 投信賣超排行 | |
| 外資投信同步買超 | 外資與投信同一天都買超的股票 |
| 產業別法人淨買賣 | 各產業外資＋投信淨買賣金額，看資金流向哪個族群 |

每個排行包含以下欄位：代號、名稱、**產業**、市場、**收盤價**、**漲跌幅**、買賣超(張)、**買賣超金額(億)**、**佔成交量比例**。

- 涵蓋**上市＋上櫃**普通股（代號為 4 碼數字者），不排除權值股，不設連買天數門檻
- ETF、權證、特別股等非普通股不列入
- 外資數字為「外資及陸資」＋「外資自營商」合計；自營商為「自行買賣」＋「避險」合計
- 金額為「買賣超股數 × 當日收盤價」的估算值，非實際成交金額
- 手動執行，不含自動排程

## FinMind 帳號注意事項

本程式一次抓取「指定日期全市場」的三大法人資料與股價。依 FinMind 官方規定，**不指定個股、一次抓全市場的查詢僅限 Backer 或 Sponsor 付費會員**。若使用免費帳號，程式會顯示 FinMind 回傳的錯誤訊息。

## Windows 安裝步驟

### 1. 安裝 Python

1. 到 <https://www.python.org/downloads/windows/> 下載 Python 3.9 以上版本
2. 執行安裝程式時，**務必勾選「Add python.exe to PATH」**
3. 安裝完成後，開啟「命令提示字元」(cmd) 或 PowerShell，輸入以下指令確認安裝成功：

```bat
python --version
```

### 2. 下載本專案

用 Git 下載，或在 GitHub 頁面按「Code → Download ZIP」下載後解壓縮：

```bat
git clone https://github.com/StKai0115/-daily-market-report.git
cd -daily-market-report
```

### 3. 安裝套件

```bat
python -m pip install -r requirements.txt
```

（選用）若想使用虛擬環境隔離套件：

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

### 4. 設定 FinMind Token

請先到 FinMind 官網註冊並登入，在會員頁面取得 API Token。Token **不會寫在程式裡**，而是從環境變數 `FINMIND_TOKEN` 讀取。

**方法 A：永久設定（建議）**

在 cmd 執行一次即可，之後**重新開啟**的命令視窗都會生效：

```bat
setx FINMIND_TOKEN "你的token"
```

也可以從「開始 → 搜尋『編輯系統環境變數』→ 環境變數 → 使用者變數 → 新增」手動設定。

**方法 B：只在目前視窗暫時設定**

cmd：

```bat
set FINMIND_TOKEN=你的token
```

PowerShell：

```powershell
$env:FINMIND_TOKEN = "你的token"
```

## 執行

```bat
python chip_report.py
```

未指定日期時，程式會從今天往前自動找最近一個有資料的交易日。

其他用法：

```bat
:: 指定日期
python chip_report.py --date 2026-09-25

:: 每個排行顯示 30 檔（預設 20 檔）
python chip_report.py --top 30

:: 排行改依「金額」排序（預設依張數）
python chip_report.py --rank-by amount

:: 只輸出部分格式（可選 md、html、xlsx，預設三種都輸出）
python chip_report.py --formats html,xlsx

:: 產生報告後推播摘要到 Telegram / LINE（設定方式見下方）
python chip_report.py --notify

:: 指定報告輸出資料夾（預設為 reports）
python chip_report.py --output-dir D:\籌碼報告
```

參數可以組合使用，例如：`python chip_report.py --top 30 --rank-by amount --notify`

## 輸出

報告會直接顯示在命令視窗，並在 `reports` 資料夾存成三種格式：

| 檔案 | 用途 |
|---|---|
| `chip_report_YYYY-MM-DD.html` | 用瀏覽器開啟，買超／上漲為紅色、賣超／下跌為綠色，手機也好閱讀 |
| `chip_report_YYYY-MM-DD.xlsx` | Excel 檔，每個區塊一個工作表，另有「全部個股」工作表可自行篩選、排序 |
| `chip_report_YYYY-MM-DD.md` | 純文字 Markdown 版本 |

## 推播設定（選用）

加上 `--notify` 參數後，程式會把重點摘要（三大法人合計、各排行前 5 名）推播到手機。Telegram 與 LINE 可以只設定其中一個，兩個都設定就兩邊都會收到。設定方式和 `FINMIND_TOKEN` 一樣，用 `setx` 設定環境變數。

### Telegram（較簡單，推薦）

1. 在 Telegram 搜尋 **@BotFather**，傳送 `/newbot`，依指示建立機器人，取得 **Bot Token**
2. 在 Telegram 找到剛建立的機器人，傳任意一則訊息給它
3. 用瀏覽器開啟 `https://api.telegram.org/bot<你的BotToken>/getUpdates`，在回應中找到 `"chat":{"id":123456789` 這串數字，就是 **Chat ID**
4. 設定環境變數：

```bat
setx TELEGRAM_BOT_TOKEN "你的BotToken"
setx TELEGRAM_CHAT_ID "你的ChatID"
```

### LINE

LINE Notify 已於 2025 年停止服務，本程式改用 **LINE Messaging API**：

1. 到 [LINE Developers](https://developers.line.biz/) 登入，建立 Provider 與 **Messaging API channel**（LINE 官方帳號）
2. 在 channel 的「Messaging API」分頁最下方發行 **Channel access token (long-lived)**
3. 在「Basic settings」分頁最下方找到 **Your user ID**（U 開頭的字串）
4. 用手機 LINE 掃描「Messaging API」分頁的 QR code，把官方帳號加為好友
5. 設定環境變數：

```bat
setx LINE_CHANNEL_ACCESS_TOKEN "你的ChannelAccessToken"
setx LINE_USER_ID "你的UserID"
```

LINE 官方帳號免費方案每月有推播則數上限，個人每日使用一則通常足夠。

## 常見問題

- **顯示「找不到環境變數 FINMIND_TOKEN」**：用 `setx` 設定後需關閉並重新開啟命令視窗。
- **顯示「查無三大法人資料」**：該日可能為休市日，或當日資料尚未更新（FinMind 通常於收盤後數小時更新）。
- **Excel 檔寫入失敗**：同一天的報告若正在 Excel 中開啟，請先關閉再重新執行。
- **金額、漲跌幅顯示「-」**：該股票當日無股價資料（例如暫停交易）。
- **推播失敗**：確認 Token、Chat ID / User ID 是否正確；Telegram 需先傳過訊息給機器人，LINE 需先加官方帳號為好友。
- **FinMind 回傳權限相關錯誤**：請確認帳號等級是否為 Backer / Sponsor（見上方「FinMind 帳號注意事項」）。
