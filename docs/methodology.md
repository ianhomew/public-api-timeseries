# 抓取原則

回上層：[README](../README.md)　｜　相關：[operations.md](operations.md)

## 每日一輪

每個來源每日僅抓取一輪。需分頁的來源在該輪內依序請求：

| 來源 | 一輪請求次數 |
|---|---|
| `x402_bazaar` | 約 16 次（`limit=1000`） |
| `cex_symbols` | 7 次（每家交易所 1 次） |
| `vast_gpu` | 1 次 |
| `fsc_clarification` | 約 52 次（列表 2 頁 + 內頁 50 筆） |

2026-08-27（UTC）實測：`track-crypto` 全部來源合計約 67 秒，`track-gov` 約 113 秒。

## 禮貌措施

- 請求間隔 **1 秒**。
- 附帶可識別的 User-Agent，內含用途與聯絡位址：
  `snapshotter-research/1.0 (daily archival; …; github.com/ianhomew/public-api-timeseries)`
- 失敗最多重試 3 次，退避 3 秒、6 秒。
- 逾時 45 秒（`vast_gpu` 為 90 秒）。

## robots.txt 合規

施工前逐一查驗每個來源的 robots.txt，明確禁止者一律排除，不做例外。

| 來源 | robots.txt | 處置 |
|---|---|---|
| CDP x402 | 無（404） | 收錄 |
| OKX | 明文 `Allow: /api/*?` | 收錄 |
| Bybit / Bitget / HTX / Gate / KuCoin / MEXC | 無限制 | 收錄 |
| vast.ai | `Allow: /` | 收錄 |
| 金管會 | 僅 `Disallow: /uploaddowndoc` | 收錄（未觸及該路徑） |
| Binance | 全站 `Disallow: /` | **排除** |
| Smithery `/api/` | `Disallow: /api/` | **排除** |
| 經濟部 | 限制 | **排除** |
| Tasker | 限制 | **排除** |
| udn.com | 禁止商業用途 | **排除** |

## 原子寫入，絕不覆蓋

寫檔流程（`write_gz`）：

1. 序列化為 JSON，計算 sha256。
2. 若當日檔案已存在且內容 hash 相同 → 直接返回，不重寫。
3. 若已存在但內容不同 → 改寫入 `YYYY-MM-DDTHHMMSS.json.gz`，**保留原檔**。
4. 先寫 `*.tmp`，再 `os.replace()` 換名。中途中斷不會留下半份檔案。

歷史快照一旦寫入即不再修改。

## 時區

- 檔名日期、`fetched_at`、自我檢查比對基準：一律 **UTC**。
- cron 排程時間：**台北時間**（VPS 時區為 `Asia/Taipei`，UTC+8）。

兩者在任何文件中都必須標明，不可混寫。

## OpenTimestamps 時間戳

檔名、mtime、`fetched_at` 與 git commit date 都可以偽造。因此每日另外蓋一次時間戳：

1. 掃描所有 `track-*/data/*/*.json.gz`，產生 `timestamps/SHA256SUMS-YYYY-MM-DD.txt`。
2. 用 `ots stamp` 產生 `.ots`，把清單的 sha256 寫入 Bitcoin。
3. 兩個檔案都提交進 repo。

任何人可獨立驗證：

```bash
ots verify timestamps/SHA256SUMS-2026-08-27.txt.ots   # 需等 Bitcoin 確認
sha256sum -c timestamps/SHA256SUMS-2026-08-27.txt     # 驗證檔案未被竄改
```

## 不做的事

- 不改寫原始回應內容。
- 不刪除既有快照。
- 不對資料做任何分析、解讀、評分或預測。
