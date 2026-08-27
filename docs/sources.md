# 來源細節

回上層：[README](../README.md)　｜　相關：[data-format.md](data-format.md)、[why.md](why.md)

所有筆數與體積為 **2026-08-27（UTC）** 快照實測值，除非另外標註日期。

## track-crypto

抓取程式：`track-crypto/scripts/snap_crypto.py`

### `x402_bazaar`

| 項目 | 值 |
|---|---|
| 端點 | `https://api.cdp.coinbase.com/platform/v2/x402/discovery/resources` |
| 分頁 | `limit=1000` + `offset`，一輪約 16 次請求 |
| 筆數 | 14,755（2026-08-26 為 15,122） |
| 壓縮後 | 6,045,267 B |
| 耗時 | 約 52 秒 |
| robots.txt | 無（回 404） |
| 已知限制 | 回應為賣家自報內容，本專案不驗證其真偽 |

### `cex_symbols`

| 項目 | 值 |
|---|---|
| 交易所 | bybit、okx、bitget、htx、gateio、kucoin、mexc（共 **7** 家） |
| 筆數 | 合計 10,744 |
| 壓縮後 | 407,121 B |
| 耗時 | 約 13 秒 |
| 已排除 | **Binance**（robots.txt 全站 `Disallow: /`） |

各交易所端點：

| 交易所 | 端點 | 2026-08-27 筆數 |
|---|---|---|
| bybit | `api.bybit.com/v5/market/instruments-info?category=spot` | 546 |
| okx | `www.okx.com/api/v5/public/instruments?instType=SPOT` | 1,383 |
| bitget | `api.bitget.com/api/v2/spot/public/symbols` | 1,296 |
| htx | `api.huobi.pro/v1/common/symbols` | 2,159 |
| gateio | `api.gateio.ws/api/v4/spot/currency_pairs` | 2,231 |
| kucoin | `api.kucoin.com/api/v2/symbols` | 1,006 |
| mexc | `api.mexc.com/api/v3/exchangeInfo` | 2,123 |

已知限制：bybit、okx、mexc 只回傳存活標的，回應中不含下架紀錄。

### `vast_gpu`

| 項目 | 值 |
|---|---|
| 端點 | `https://console.vast.ai/api/v0/bundles/`（`type=on-demand`，依 `dph_total` 遞增排序） |
| 筆數 | 512 |
| 壓縮後 | 173,851 B |
| 耗時 | 約 2 秒 |
| robots.txt | `Allow: /` |
| 已知限制 | **未帶 API 金鑰時端點只回 64 筆**。2026-08-26 快照即為 64 筆；2026-08-27 起改用金鑰認證，回 512 筆。快照中的 `_authenticated` 欄位記錄該次是否認證。 |

### `mcp_registry`（已停抓）

| 項目 | 值 |
|---|---|
| 端點 | `https://registry.modelcontextprotocol.io/v0/servers` |
| 最後一份快照 | 2026-08-26，82,612 筆，6,625,684 B |
| 停抓日 | 2026-08-27 |
| 停抓理由 | 官方支援 `updated_since`，且單日快照即含多版本，逐日快照的邊際資訊近乎零。該來源佔當日抓取時間 946.9 秒（約 93%）。詳見 [revisions.md](revisions.md) |

已抓資料保留不刪。

## track-gov

抓取程式：`track-gov/scripts/snap_gov.py`

### `fsc_clarification`

| 項目 | 值 |
|---|---|
| 來源 | 金管會 即時新聞澄清（`https://www.fsc.gov.tw/ch/`，`id=609`） |
| 筆數 | 50（全部歷史，2017-03 起） |
| 壓縮後 | 42,908 B |
| 請求次數 | 一輪約 52 次（列表 2 頁 + 內頁 50 筆） |
| 耗時 | 約 113 秒 |
| robots.txt | 僅 `Disallow: /uploaddowndoc`，本專案未觸及 |
| 每筆欄位 | `dataserno`、`url`、`title`、`date`、`body_text`、`body_sha256`、`raw_sha256`、`raw_bytes` |

已知限制與技術細節：

- 內頁 URL **必須帶 `&dtable=News`**，否則回傳頁面不含正文。
- 分頁參數是 **`&page=N`**；`pageNum`、`currentPage` 等皆無效。
- `class="page-edit"` **是內容容器，不是頁尾**。正文結構為
  `ap > maincontent > subject/date > page-edit > zbox > main-a_01 > main-a_03`。
- 純靜態 HTML，無 Cloudflare，無 rate limit。

法律依據：著作權法第 9 條第 2 項明文「公文包括公務員職務上草擬之文告、講稿、**新聞稿**」，
不受著作權保護。個資風險低：裁罰受處分人多為法人，自然人姓名官方已遮罩（如「林00先生」）。

## 已排除的來源

| 來源 | 排除理由 |
|---|---|
| Binance | robots.txt 全站 `Disallow: /` |
| Smithery `/api/` | robots.txt `Disallow: /api/` |
| 經濟部 | robots.txt 限制 |
| Tasker | robots.txt 限制 |
| udn.com | robots.txt 禁止商業用途 |
