# 台股每日籌碼報告

使用 [FinMind API](https://finmindtrade.com/) 抓取三大法人買賣資料，產生台股每日籌碼報告。

## 報告內容

| 區塊 | 說明 |
|---|---|
| 全市場總覽 | 外資、投信、自營商當日合計買賣超（張數與估計金額） |
| 期貨選擇權籌碼 | 三大法人台指期淨未平倉、外資台指買權／賣權淨未平倉（含日增減）、選擇權 Put/Call Ratio |
| 外資買超排行 | |
| 外資賣超排行 | |
| 投信買超排行 | |
| 投信賣超排行 | |
| 外資投信同步買超 | 外資與投信同一天都買超的股票 |
| 外資連續買超 | 外資連續買超 3 天以上的股票，依連買天數排序 |
| 投信連續買超 | 投信連續買超 3 天以上的股票，依連買天數排序 |
| 產業別法人淨買賣 | 各產業外資＋投信淨買賣金額，看資金流向哪個族群 |
| 高股息 ETF 法人買賣超 | 預設追蹤 0056、00878、00919、00929、00713、00915、00918、00934、00939、00940 |
| 融資增加／融資減少／融券增加排行 | 個股融資融券餘額增減，另附全市場合計 |
| 千張大戶持股增加／減少 | 集保股權分散表，持股超過 1,000 張的大戶持股比例週增減 |

每個排行包含以下欄位：代號、名稱、**產業**、市場、**收盤價**、**漲跌幅**、買賣超(張)、**買賣超金額(億)**、**佔成交量比例**、**連買／連賣天數**。

### 延伸指標說明

- **淨未平倉**＝多方未平倉口數－空方未平倉口數；外資台指期淨未平倉常被當成大盤多空的參考，正數偏多、負數偏空
- **Put/Call Ratio**＝賣權未平倉量 ÷ 買權未平倉量（一般交易時段）
- **券資比**＝融券餘額 ÷ 融資餘額
- **千張大戶**：集保每週公布一次（資料日期通常是週五），所以這兩個區塊一週內的內容相同，直到下一次公布；報告中會註明資料日期
- **高股息 ETF**：只列在自己的區塊，不會出現在個股排行，也不計入全市場總覽與產業統計
- **修改雲端追蹤的 ETF 清單**：在 GitHub 網頁上編輯 `extras.py` 開頭的 `DEFAULT_ETFS`，存檔後下一次排程就會套用
- 期貨選擇權、融資融券、千張大戶這三塊任一項抓不到資料（例如 FinMind 權限不足）時，只會略過該區塊，其他內容與推播照常產生

### 連續買超天數怎麼算

- 從報告當日往前逐日檢查，法人每天都買超才算「連買」，中間任何一天賣超或沒有買賣就中斷
- 預設最多回溯 **10 個交易日**；天數顯示 10 代表「至少連買 10 天」
- 「累計買超」是連買期間每天買超張數的加總，「累計金額」以報告當日收盤價估算
- 外資買超／投信買超排行裡的「連買天數」欄位只是參考資訊，**不會**用來篩選排行（排行本身仍不設天數門檻）

- 涵蓋**上市＋上櫃**普通股（代號為 4 碼數字者），不排除權值股，不設連買天數門檻
- ETF、權證、特別股等非普通股不列入個股排行（高股息 ETF 另列一個區塊）
- 外資數字為「外資及陸資」＋「外資自營商」合計；自營商為「自行買賣」＋「避險」合計
- 金額為「買賣超股數 × 當日收盤價」的估算值，非實際成交金額
- 可手動執行，也可以用 GitHub Actions 在雲端每天自動推播（見「雲端自動推播」）

## FinMind 帳號注意事項

本程式一次抓取「指定日期全市場」的三大法人資料與股價。依 FinMind 官方規定，**不指定個股、一次抓全市場的查詢僅限 Backer 或 Sponsor 付費會員**。若使用免費帳號，程式會顯示 FinMind 回傳的錯誤訊息。

延伸區塊會另外查詢以下資料集：

| 區塊 | FinMind 資料集 | 每次查詢次數 |
|---|---|---|
| 期貨選擇權籌碼 | `TaiwanFuturesInstitutionalInvestors`、`TaiwanOptionInstitutionalInvestors`、`TaiwanOptionDaily` | 約 4 次 |
| 融資融券 | `TaiwanStockMarginPurchaseShortSale`（一次抓全市場，需付費會員） | 1 次 |
| 千張大戶持股 | `TaiwanStockHoldingSharesPer`（一次抓全市場，需付費會員） | 約 2～6 次 |

計算連續買超天數時，程式會多抓前 9 個交易日的法人資料，每次執行大約多 9～15 次 API 查詢（遇到週末、連假會多幾次）。若想減少查詢次數，可以加上 `--no-streak` 關閉此功能。

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

:: 只處理今天的資料；休市或資料尚未更新時不產生報告、不推播
python chip_report.py --today-only --notify

:: 連續買超區塊改為只列連買 5 天以上（預設 3 天）
python chip_report.py --streak-min 5

:: 連續天數改為最多回溯 20 個交易日（預設 10）
python chip_report.py --streak-days 20

:: 不計算連續買超天數（少抓歷史資料，執行較快）
python chip_report.py --no-streak

:: 自訂追蹤的高股息 ETF
python chip_report.py --etfs 0056,00878,00919

:: 關閉不需要的延伸區塊（可任意組合）
python chip_report.py --no-etf --no-futures --no-margin --no-holders

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

## 雲端自動推播（GitHub Actions）

設定完成後，GitHub 會在**週一至週五傍晚自動產生報告並推播**，電腦關機也不影響。

- 排程在 **18:07～22:07（台灣時間）每小時執行一次**。GitHub 的排程在系統忙碌時可能延遲或被略過，所以多排幾次當作備援
- 當天報告發布成功後，之後的排程會自動跳過，**每天只會推播一次**
- 排程執行時會自動加上 `--today-only`：FinMind 資料還沒更新時，會等下一個小時再試；國定假日則整晚都會跳過，不會推播舊資料
- 通常 18:00～19:00 之間就會收到推播（視 GitHub 排程延遲而定）
- 排程設定在 `.github/workflows/daily-report.yml`，要改時間請修改 `cron` 那一行（使用 UTC 時間，台灣時間減 8 小時）

### 1. 把 token 存到 GitHub Secrets

Secrets 會加密保存，不會出現在程式碼或執行記錄中。

1. 打開 GitHub 上的本專案頁面，點上方「**Settings**」
2. 左側選單點「**Secrets and variables**」→「**Actions**」
3. 按「**New repository secret**」，依序新增以下項目（**Name 必須完全一致**，Secret 欄位貼上對應的值）：

| Name | 內容 | 是否必要 |
|---|---|---|
| `FINMIND_TOKEN` | FinMind API token | 必要 |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Channel access token | 使用 LINE 時 |
| `LINE_USER_ID` | LINE User ID（U 開頭 33 碼） | 使用 LINE 時 |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token | 使用 Telegram 時 |
| `TELEGRAM_CHAT_ID` | Telegram Chat ID | 使用 Telegram 時 |

### 2. 手動測試一次

1. 點專案頁面上方「**Actions**」
   （第一次使用若出現提示，按「I understand my workflows, go ahead and enable them」啟用）
2. 左側點「**台股每日籌碼報告**」
3. 右側按「**Run workflow**」→ 日期留白、勾選推播 → 按綠色「**Run workflow**」
4. 約 1 分鐘後手機收到推播即設定完成；若出現紅色 ✗，點進去展開「產生報告」步驟看錯誤訊息

手動執行時未指定日期，會抓最近一個交易日的資料（不受 `--today-only` 限制），方便隨時測試。

#### 只測試、不推播（不消耗 LINE 額度）

按「Run workflow」時，把下面兩個選項都**取消勾選**：

- **推播到 Telegram / LINE**：取消後不會發送訊息
- **發布報告網頁**：取消後不會更新報告網頁。若手動執行時發布了當天報告，晚上的排程會以為當天已完成而跳過推播，所以測試時建議取消

執行完成後：

1. 點進該次執行 → 展開「產生報告」步驟，檢查有沒有「警告：…資料讀取失敗」的訊息
2. 頁面下方「Artifacts」下載 ZIP，裡面的 `summary.txt` 就是**原本會推播的訊息內容**，HTML、Excel 則是完整報告

### 3. 設定報告網頁（GitHub Pages）

每次雲端執行後，HTML 報告會自動發布成網頁，推播訊息最後會附上連結，手機點開就能看完整報告：

- 當日報告：`https://<你的GitHub帳號小寫>.github.io/-daily-market-report/YYYY-MM-DD.html`
- 所有報告列表：`https://<你的GitHub帳號小寫>.github.io/-daily-market-report/`

⚠️ GitHub 免費方案只有**公開（public）專案**能使用 Pages，而且 **Pages 網頁任何人都能瀏覽**（報告內容只有公開的市場資料）。Token 都存在 Secrets 中，專案公開也不會外洩。

設定步驟（只需做一次）：

1. **把專案改為公開**：「Settings」→「General」→ 捲到最下方「Danger Zone」→「Change visibility」→「Change to public」
2. **先手動執行一次 workflow**（見上方第 2 步）：第一次執行會自動建立 `gh-pages` 分支，存放報告網頁
3. **啟用 Pages**：「Settings」→ 左側「**Pages**」→「Build and deployment」的 Source 選「**Deploy from a branch**」→ Branch 選「**gh-pages**」、資料夾選「**/ (root)**」→ 按「Save」
4. 約 1～2 分鐘後，打開上面的「所有報告列表」網址，看得到報告就完成了

之後每次執行都會新增一份當日報告，舊報告會一直保留在列表中。

### 4. 下載 Excel 報告

每次執行產生的報告檔（含 Excel）會保存 30 天：進入「Actions」→ 點選某次執行 → 頁面下方「**Artifacts**」即可下載 ZIP 檔。

### 注意事項

- **執行失敗會收到 Email**：例如 token 過期、推播失敗，GitHub 會寄信通知帳號信箱
- **公開（public）專案**：Actions 執行時間不限額度；但連續 60 天沒有任何 commit，GitHub 會自動停用排程，屆時到「Actions」頁面重新啟用即可
- **私人（private）專案**：無法使用 Pages（見上方第 3 步）；每次執行約 2～4 分鐘，免費帳號每月有 2,000 分鐘額度，足夠使用
- 若已改用雲端推播，記得停用電腦上的「工作排程器」工作，避免重複推播

## 常見問題

- **晚上都沒收到推播**：到「Actions」頁面看當天有沒有「schedule」觸發的執行紀錄。如果完全沒有，代表 GitHub 當天的排程被略過了，可以按「Run workflow」手動補跑一次
- **推播的報告連結打不開（404）**：確認已完成「設定報告網頁」的步驟 3；Pages 剛啟用或剛更新時需等 1～2 分鐘

- **顯示「找不到環境變數 FINMIND_TOKEN」**：用 `setx` 設定後需關閉並重新開啟命令視窗。
- **顯示「查無三大法人資料」**：該日可能為休市日，或當日資料尚未更新（FinMind 通常於收盤後數小時更新）。
- **Excel 檔寫入失敗**：同一天的報告若正在 Excel 中開啟，請先關閉再重新執行。
- **金額、漲跌幅顯示「-」**：該股票當日無股價資料（例如暫停交易）。
- **推播失敗**：確認 Token、Chat ID / User ID 是否正確；Telegram 需先傳過訊息給機器人，LINE 需先加官方帳號為好友。
- **FinMind 回傳權限相關錯誤**：請確認帳號等級是否為 Backer / Sponsor（見上方「FinMind 帳號注意事項」）。
