# track-crypto — 加密 / AI 算力市場每日快照

**這是原始資料存檔，不含任何分析、觀點或投資建議。**

## 授權
資料以 **CC BY 4.0** 釋出。使用時請標示來源。

## 這是什麼
每天對下列公開端點各取一次快照，永久保留。目的是保存「官方不提供歷史」的時間序列。
一天一檔，`YYYY-MM-DD.json.gz`，**永不覆蓋**。

| 來源 | 端點 | 為何值得存 | robots.txt |
|---|---|---|---|
| `x402_bazaar` | CDP x402 discovery | 官方 `/history` 回 404；賣家下架即消失 | 無 robots.txt（404） |
| `cex_symbols` | Bybit/OKX/Bitget/HTX/Gate/KuCoin/MEXC | 幣種下架後即從 API 消失 | 皆無限制；OKX 明文 `Allow: /api/*?` |
| `vast_gpu` | vast.ai bundles | GPU 現貨報價，無官方歷史 | `Allow: /` |
| `mcp_registry` | MCP 官方註冊表 | status/statusChangedAt 無歷史版本 | 無 robots.txt（404） |

**已排除**：Binance（robots 全站 `Disallow: /`）、Smithery `/api/`（robots `Disallow: /api/`）。

## 已知限制
- `vast_gpu`：免金鑰端點固定回傳 64 筆（非全量）。這是 vast.ai 的認證限制，非本專案錯誤。
- `mcp_registry`：全量約 82,000 筆，抓取約 14 分鐘。
- 所有來源每日僅請求一次，附帶可識別的 User-Agent。

## 資料結構
```
data/<source>/YYYY-MM-DD.json.gz    # {"_meta":{...},"data":{...}}
data/_manifest/YYYY-MM-DD.json      # 當日各來源成功與否、大小、耗時
logs/cron.log                        # 執行日誌
```

## 免責
本存檔僅記錄公開端點在特定時間點的回應內容，**不對資料正確性作任何保證**，
**不構成任何投資建議或分析意見**。使用者應自行驗證。


## `track-crypto/data/cex_events/` — 上架／下架事件流

`bybit` / `okx` / `mexc` 三家交易所的 API **只回傳存活中的交易對**，下架後直接從回應中消失。
只有 `htx` 保留 `offline` 狀態（1,547 / 2,159 筆）。

用未修正生存者偏誤的資料做回測，會**系統性高估報酬** —— 因為死掉的標的從資料裡消失了。

本檔逐日比對快照，累積成 `events.jsonl`（只追加）：
```json
{"date":"2026-08-27","exchange":"bybit","symbol":"XXXUSDT","event":"DELISTED","from":"Trading","to":null}
```
`event` 為 `LISTED` / `DELISTED` / `STATUS_CHANGED`。

**本檔只記錄事實，不含任何解讀、預測或建議。**
