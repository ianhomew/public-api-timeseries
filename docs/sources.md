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

抓取程式：`track-gov/scripts/snap_gov.py`（自動載入 `track-gov/adapters/*.py`）

一個機關一支 adapter。每份快照的 `_meta` 內含該來源的 `robots_verified` 親驗紀錄。
每筆欄位：`id`、`url`、`title`、`date`、`body_text`、`body_sha256`
（`fsc_clarification` 另保留 `dataserno`，與 2026-08-27 前的快照相容）。

下表為 2026-08-27（UTC）在 VPS（德國 IP）實測值。「唯一 sha256」= 該來源所有正文互不重複的比例，
用來確認抓到的是正文而非頁面框架。

| channel | 機關與類別 | 筆數 | 唯一 sha256 | 壓縮後 | 耗時 | robots.txt 親驗結果 |
|---|---|---|---|---|---|---|
| `fsc_clarification` | 金管會 即時新聞澄清 | 50（全部歷史） | 50/50 | 40,066 B | 142s | 僅 `Disallow: /uploaddowndoc`（附件） |
| `moe_clarify` | 教育部 即時新聞澄清 | 80（全部歷史 82 筆，2 筆舊稿無正文） | 80/80 | 72,944 B | 327s | 4 條，皆為 `/WebResource.axd`、`/src`、`/Scripts/…`、`/search` |
| `moj_press` | 法務部 新聞發布 | 99 | 99/99 | 107,121 B | 596s | 全檔只有 `Sitemap:` 一行，無任何 Disallow |
| `cbc_press` | 中央銀行 新聞稿／新聞參考資料 | 99 | 99/99 | 47,464 B | 304s | 該站不提供 robots.txt（請求被導回首頁） |
| `mof_press` | 財政部 本部新聞 | 99 | 99/99 | 82,376 B | 308s | 僅 `Disallow: /download/` |
| `mol_press` | 勞動部 新聞稿 | 100 | 100/100 | 132,533 B | 289s | `/bin/`、`/App_Data/`、`/App_Plugins/`、`/Umbraco/` |
| `moda_press` | 數位發展部 新聞發布 | 100 | 100/100 | 98,098 B | 120s | robots.txt 404，無 Disallow |
| `moi_press` | 內政部 新聞稿 | 100 | 100/100 | 98,560 B | 381s | robots.txt 404，無 Disallow |
| `ey_press` | 行政院 本院新聞 | 100 | 100/100 | 175,792 B | 356s | `/Upload`、`/Program/EY/Hope_decision.ascx` |
| `mohw_press` | 衛生福利部 焦點新聞 | 100 | 100/100 | 117,701 B | 277s | 全檔僅 `User-agent: *`，零 Disallow |
| `moe_press` | 教育部 即時新聞 | 100 | 100/100 | 121,438 B | 420s | 同 `moe_clarify` |
| `moea_press` | 經濟部 本部新聞 | 100 | 100/100 | 114,500 B | 226s | 只有 `User-Agent:ZoomEye` 被全站封鎖；對 `*` 僅禁 `/MNS_OLD/` |

合計每日約 **1.19 MB**、約 1,260 次請求、約 62 分鐘。

### 各來源的已知限制與踩過的坑

- **`fsc_clarification`**：內頁 URL 必須帶 `&dtable=News`，否則回傳的頁面不含正文；分頁參數是
  `&page=N`；`class="page-edit"` **是內容容器不是頁尾**。正文含「瀏覽人次」計數器，已在寫入前過濾。
- **`moe_press` / `moe_clarify`**：分頁為真正的 GET 參數 `page=N&PageSize=20`；`p=`、`pageIndex=` 無效。
  日期為民國年（`115-08-27`），依規格保留原文不轉換。
- **`moj_press`**：清單頁**不含日期**，必須進內頁才拿得到。Umbraco 產出，正文被大量 `<span>` 切碎。
- **`cbc_press`**：內頁 URL 含隨機 5 碼雜湊，**不可自行組裝**，必須沿用清單連結。節點 id 錯誤時
  **不回 404 而是靜默 302 導回首頁**，極易誤判為「全部下架」，因此 0 筆時一律 raise。
  ⚠️ **相當比例為統計類新聞稿，正文只有一兩句，實質數字在 XLSX 附件內。本專案不抓附件，
  因此偵測不到附件被抽換。**
- **`mof_press`**：側欄「即時新聞澄清」也含 `cntId`，必須只解析 `<table class="table-list">`；
  頁尾也有 `<article>`，需先錨定 `<span class="span-page-title">`。
- **`mol_press`**：正文是 Word 貼上產生的巢狀 HTML，需抓 `section.cp` 內最內層的 `<body>`。
  該節點只滾動保留約一年（實測 289 筆，最舊 2025-08-28），更舊者移入「歷史新聞」。
- **`moda_press`**：分頁為純前端 JS，7 種 URL 參數實測全部無效；改用官網自己呼叫的公開端點
  `POST www-api.moda.gov.tw/WebsiteList/NewsList`（回傳 HTML 片段），`Dep` 參數必填。
- **`moi_press`**：頁面帶 UTF-8 BOM。日期為民國年。
- **`moea_press`**：換頁是 ASP.NET WebForms postback，必須帶 `__VIEWSTATE` 等 3 個隱藏欄位
  與 2 個 Cookie；缺 Cookie 時**回 HTTP 200 但內容是錯誤頁**，不能只看狀態碼判斷成功。
  8 種 GET 分頁參數實測全部無效。頁面 `<meta name="DC.Date">` 是全站樣板固定值
  （每篇都是 2009-09-09），不是真實發布日期，改用清單頁的 `lblBeginDate`。
  正文卡片外有「點閱數」計數器，但在切取範圍之外；已用「同篇間隔 1 秒重抓兩次」
  驗證 body_text 逐位元組相同，確認不含揮發性內容。
- **`ey_press`**：節點頁不能裸開，需帶 GUID 或 `?page=&PS=`；清單混入影音節點需過濾；
  內頁底部「最新新聞」連結列若混入正文會讓多筆高度雷同，已排除。
  「即時新聞澄清」欄目大量外連到其他部會（含全站禁止的經濟部），**刻意不收錄**，只取本院新聞。

法律依據：著作權法第 9 條第 2 項明文「公文包括公務員職務上草擬之文告、講稿、**新聞稿**」，
不受著作權保護。一律不抓附件。

### 個資揭露（2026-08-28 稽核後補充）

本專案**照原文保存，不做遮蔽**。理由：存檔的意義在於保留機關當時實際發布的原貌，
任何遮蔽都會讓「內容是否被改寫」的比對失去基準。

已知情況，如實揭露：

- **`mof_press`（財政部）**：部分新聞稿的聯絡人簽名檔含**承辦人姓名與個人行動電話**，
  重複出現於 4 篇以上。這些內容由機關自行公開刊登於官方網站，本專案僅原樣保存。
- 其他機關抽驗結果：聯絡電話多為機關代表號或分機，無個人號碼。
- 1,127 筆正文的結構化掃描：**0 筆**台灣身分證字號格式命中。
- 政府新聞稿中的裁罰對象多為法人；自然人姓名官方多已遮罩（如「林00先生」）。

若當事人要求移除，請至 GitHub 開 issue。

## 已排除的來源

| 來源 | 排除理由 |
|---|---|
| Binance | robots.txt 全站 `Disallow: /` |
| Smithery `/api/` | robots.txt `Disallow: /api/` |
| **環境部** | robots.txt 明文禁止 `/Page/`、`/page/`、`/News_Content.aspx`、`/*?page=*`，新聞稿清單與內頁**全部**落在禁止路徑，無合規替代路徑；且全站 Cloudflare JS 挑戰（`Cf-Mitigated: challenge`），標準函式庫無法取得內容，繞過等同規避防護措施。舊網域 `epa.gov.tw` 已 DNS 不存在 |
| Tasker | robots.txt 限制 |
| udn.com | robots.txt 禁止商業用途 |
