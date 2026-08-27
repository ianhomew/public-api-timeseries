# track-crypto — 加密貨幣與 AI 算力市場每日快照

回上層：[專案總覽](../README.md)

這是原始資料存檔，**不含任何分析、觀點或投資建議**。

每天對下列公開端點各取一次快照，一天一檔 `YYYY-MM-DD.json.gz`（日期為 **UTC**），**永不覆蓋**。

## 收錄來源

| 來源 | 端點 | 2026-08-27 筆數 | 狀態 |
|---|---|---|---|
| `x402_bazaar` | CDP x402 discovery | 14,755 | 每日抓取 |
| `cex_symbols` | Bybit / OKX / Bitget / HTX / Gate / KuCoin / MEXC（7 家） | 10,744 | 每日抓取 |
| `vast_gpu` | vast.ai bundles | 512 | 每日抓取 |
| `mcp_registry` | MCP 官方註冊表 | 82,612（2026-08-26） | **2026-08-27 起停抓**，資料保留 |

每日壓縮後合計約 **6.6 MB**，抓取約 67 秒。

端點全文、各交易所筆數、欄位與已知限制 → [docs/sources.md](../docs/sources.md)

## 需要先知道的兩件事

1. **`vast_gpu` 的筆數受認證狀態影響**：未帶 API 金鑰時端點只回 64 筆。
   跨日比較前請先看快照中的 `_authenticated` 欄位。
2. **`cex_symbols` 有生存者偏誤**：bybit、okx、mexc 只回傳存活標的，下架後直接消失。
   只有 HTX 保留 `offline` 狀態（2026-08-26：1,547 / 2,159 筆）。

## `data/cex_events/`

`scripts/cex_events.py` 逐日比對快照，把上架／下架事件累積寫入 `events.jsonl`（只追加）：

```json
{"date":"2026-08-27","exchange":"bybit","symbol":"XXXUSDT","event":"DELISTED","from":"Trading","to":null}
```

`event` 為 `LISTED` / `DELISTED` / `STATUS_CHANGED`。本檔只記錄事實，不含任何解讀、預測或建議。

## 目錄

```
data/<source>/YYYY-MM-DD.json.gz    {"_meta":{...},"data":{...}}
data/_manifest/YYYY-MM-DD.json      當日各來源成敗、大小、耗時
data/cex_events/events.jsonl        上／下架事件流
scripts/snap_crypto.py              抓取程式
logs/cron.log                       執行日誌（不入 GitHub）
```

`data/**/*.json.gz` 目前不入 GitHub（見專案根目錄 `.gitignore`），原始資料保存於 VPS。

檔案結構與讀取範例 → [docs/data-format.md](../docs/data-format.md)
抓取原則與 robots.txt → [docs/methodology.md](../docs/methodology.md)

## 授權

資料 **CC BY 4.0**，程式碼 **MIT**。使用時請標示來源。

## 免責

本存檔僅記錄公開端點在特定時間點的回應內容，不對資料正確性作任何保證，
不構成任何投資建議或分析意見。使用者應自行驗證。
