# 抓取原則

回上層：[README](../README.md)　｜　相關：[operations.md](operations.md)

## 每日一輪

每個來源每日僅抓取一輪。需分頁的來源在該輪內依序請求：

| 來源 | 一輪請求次數 |
|---|---|
| `x402_bazaar` | 約 16 次（`limit=1000`） |
| `cex_symbols` | 7 次（每家交易所 1 次） |
| `vast_gpu` | 1 次 |
| `track-gov` 各機關 | 每個來源約 50–130 次（清單分頁 + 每筆內頁各 1 次） |

2026-08-27（UTC）實測：`track-crypto` 全部來源合計約 67 秒；
`track-gov` 共 11 個機關、約 1,150 次請求、約 58 分鐘（排程 09:30 起跑，11:30 提交前完成）。

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
| 衛福部 / 法務部 / 內政部 / 數位部 | 無 Disallow 或 robots.txt 404 | 收錄 |
| 中央銀行 | 不提供 robots.txt | 收錄（依排除協定視為無限制） |
| 行政院 / 財政部 / 勞動部 / 教育部 | Disallow 僅涵蓋附件或技術路徑 | 收錄（未觸及） |
| 經濟部 | `Disallow: /` **只綁定具名爬蟲 ZoomEye**；對 `*` 僅禁 `/MNS_OLD/` | 收錄（新聞稿在 `/MNS/`） |
| **環境部** | 明文禁止 `/Page/`、`/News_Content.aspx` | **排除** |
| Binance | 全站 `Disallow: /` | **排除** |
| Smithery `/api/` | `Disallow: /api/` | **排除** |

| Tasker | 限制 | **排除** |
| udn.com | 禁止商業用途 | **排除** |

## 原子寫入，絕不覆蓋

寫檔流程（`write_gz`）：

1. 序列化為 JSON，計算 sha256。
2. 若當日檔案已存在且內容 hash 相同 → 直接返回，不重寫。
3. 若已存在但內容不同 → 改寫入 `YYYY-MM-DDTHHMMSS.json.gz`，**保留原檔**。
4. 先寫 `*.tmp`，再 `os.replace()` 換名。中途中斷不會留下半份檔案。

歷史快照一旦寫入即不再修改。

同一 UTC 日期若存在多份快照（重跑或遷移產生），變動偵測**只取當日最後一份**，
不把同日重跑當成改寫事件。

## 揮發性內容過濾

部分機關頁面的正文區塊內含「瀏覽人次」計數器，每次抓取數字都不同。
這類行在寫入快照前即被移除（`snap_gov.py` 的 `strip_volatile`）。

不過濾的後果是實測過的：2026-08-27 遷移後第一次比對，50 篇金管會澄清稿**全部**被判定為
「內容改寫」，實際差異只有瀏覽人次由 23694 變成 23697。
每日誤報 100% 會讓真正的改寫訊號完全失去意義。

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
