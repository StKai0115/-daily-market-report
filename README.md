# 台股每日籌碼報告

使用 [FinMind API](https://finmindtrade.com/) 抓取三大法人買賣資料，產生台股每日籌碼報告。

## 報告內容

報告只有三個區塊：

1. **外資買超排行**
2. **外資賣超排行**
3. **投信買超排行**

- 涵蓋**上市＋上櫃**普通股（代號為 4 碼數字者），不排除權值股，不設連買天數門檻
- ETF、權證、特別股等非普通股不列入排行
- 外資數字為「外資及陸資」＋「外資自營商」合計
- 單位為「張」（1 張 = 1,000 股），買賣超以買進減賣出計算
- 手動執行，不含自動排程

## FinMind 帳號注意事項

本程式一次抓取「指定日期全市場」的三大法人資料。依 FinMind 官方規定，**不指定個股、一次抓全市場的查詢僅限 Backer 或 Sponsor 付費會員**。若使用免費帳號，程式會顯示 FinMind 回傳的錯誤訊息。

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

:: 指定報告輸出資料夾（預設為 reports）
python chip_report.py --output-dir D:\籌碼報告
```

## 輸出

- 報告會直接顯示在命令視窗
- 同時存成 Markdown 檔：`reports\chip_report_YYYY-MM-DD.md`

範例：

```
## 外資買超排行（前 20 名）

| 排名 | 代號 | 名稱 | 市場 | 買進(張) | 賣出(張) | 買賣超(張) |
|---:|:---|:---|:---:|---:|---:|---:|
| 1 | 2330 | 台積電 | 上市 | 5,001 | 2,000 | +3,001 |
```

## 常見問題

- **顯示「找不到環境變數 FINMIND_TOKEN」**：用 `setx` 設定後需關閉並重新開啟命令視窗。
- **顯示「查無三大法人資料」**：該日可能為休市日，或當日資料尚未更新（FinMind 通常於收盤後數小時更新）。
- **FinMind 回傳權限相關錯誤**：請確認帳號等級是否為 Backer / Sponsor（見上方「FinMind 帳號注意事項」）。
