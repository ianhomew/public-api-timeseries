# 來源細節

回上層：[README](../README.md)　｜　相關：[track-gov README](../track-gov/README.md)

資料來源：2026-08-31（多數來源）／2026-09-02（本輪新增 `payment_pricing_pages`、
確認 `x402_index_thirdparty` 停抓狀態）直接讀取 VPS `/home/agentops/snap/public-api-timeseries/{track-crypto,track-gov}/adapters/*.py` 原始碼，
欄位取自各檔案內的 `KEY`／`DESC`／`SOURCE_HOME`／`ROBOTS_VERIFIED`／`PARSER_VERSION`／`MAX_ITEMS`／`MAX_PAGES` 等常數，
以及 VPS `crontab -l` 的排程設定。**缺的欄位一律標「未記載」，不臆造。**

## 抓取頻率（全部來源共通）

依 VPS `crontab -l`（2026-08-31 查核）：

| 項目 | 排程（台北時間） | 執行程式 |
|---|---|---|
| `track-crypto`（24 個來源，另有 1 個已停抓 `x402_index_thirdparty`、1 個人工封存 `mcp_pulsemcp`，兩者歷史資料皆保留） | 每日 08:00 | `track-crypto/scripts/snap_crypto.py` |
| `track-gov`（18 個來源） | 每日 09:30（`flock -w 1800` 等抓取鎖，最多等 30 分鐘） | `track-gov/scripts/snap_gov.py` |
| git push | 每日 11:30（`flock -w 7200`，最多等 2 小時） | `scripts/push.sh` |

每個來源**每日僅抓取一輪**，同一 track 內部無來源別排程差異；`fetch()` 請求間隔固定 1 秒。

## 來源狀態說明（活躍／已停抓／人工封存）

`track-crypto/` 的來源依所在目錄分三種狀態，決定是否被每日排程與自動探索機制（`snap_crypto.py`／`detect_changes.py`／`healthcheck.py`／`daily_report.py` 共用同一套探索邏輯）納入：

| 狀態 | 目錄 | 是否每日排程 | 是否被自動探索 | 目前數量 |
|---|---|---|---|---|
| **活躍** | `track-crypto/adapters/`、`track-gov/adapters/` | 是 | 是 | 42（track-crypto 24 ＋ track-gov 18） |
| **已停抓** | `track-crypto/retired_adapters/` | 否 | 否 | 1（`x402_index_thirdparty`） |
| **人工封存** | `track-crypto/manual_adapters/` | 否（人工不定期手動執行） | 否 | 1（`mcp_pulsemcp`） |

三者差異：

- **活躍**＝每日自動抓取，計入來源總數。
- **已停抓**＝曾每日抓取，因故永久停止（例如與既有來源高度重疊、觸及第三方站台自身收錄上限）；
  依目前慣例，adapter 原始碼**搬移**（非刪除）到 `retired_adapters/`，方便查證但不再被排程／自動探索；
  已抓歷史資料**保留，不刪除、不覆寫**。
- **人工封存**＝從未進入每日排程，由人工在特定時機（例如官方即將關閉端點前）手動執行一次或多次，
  adapter 原始碼放在 `manual_adapters/`，同樣不被自動探索。

**例外／慣例沿革說明**（避免讀者誤以為所有已停抓來源都能在 `retired_adapters/` 找到原始碼）：
`mcp_registry`（2026-08-27 起停抓，本專案第一個「停抓」案例）早於 `retired_adapters/` 這個目錄慣例
設立之前，其 adapter 原始碼已**直接刪除**、未保留移動版本；只有 `data/mcp_registry/` 下的歷史快照
資料保留。`x402_index_thirdparty`（本專案第二個「停抓」案例）才開始採用「搬移保留原始碼」的現行慣例。

`track-gov/` 目前沒有 `retired_adapters/` 或 `manual_adapters/` 目錄，尚無已停抓或人工封存案例。

## track-crypto（24 個來源）

抓取程式：`track-crypto/scripts/snap_crypto.py`（自動載入 `track-crypto/adapters/*.py`）

> 已停抓來源 `mcp_registry`（2026-08-27 起停止，已抓資料保留）**不計入本次 24 個**，
> 因其 adapter 檔已不在 `track-crypto/adapters/` 目錄下（沿用既有文件記載，本輪未重新驗證）。
>
> 已停抓來源 `x402_index_thirdparty`（2026-09-02 起停止，已抓資料保留）**同樣不計入本次 24 個**，
> 詳細停抓日期／理由／歷史資料保留說明見本節末〈已停抓〉小節。
>
> 人工封存來源 `mcp_pulsemcp`（`manual_adapters/`，不在每日排程內，人工不定期執行）
> **同樣不計入本次 24 個**，詳見本檔末〈人工封存來源〉小節。
>
> 本輪新增 `payment_pricing_pages`（2026-09-02 起，見下方同名小節）**已計入本次 24 個**。

### `agent_virtuals`

| 項目 | 值 |
|---|---|
| 中文名／內容 | Virtuals Protocol agent 清單 |
| 程式內 DESC | Virtuals Protocol agent 清單（精簡欄位：id/status/tokenAddress 等，用於偵測代幣消失與狀態變更） |
| 端點 | `https://api.virtuals.io/api/virtuals?pagination[page]=N&pagination[pageSize]=500` |
| parser_version | 2 |
| MAX_ITEMS／等效上限 | MAX_PAGES=200 |
| 抓取頻率 | 每日一次（台北時間 08:00，`snap_crypto.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-28 親驗 https://api.virtuals.io/robots.txt：Content-Signal 格式，search=yes（預設）, ai-train=no；User-agent: * 未見路徑 Disallow |
| 實測值（2026-08-31 UTC） | 36,000 筆（官方回報總數 82,317 筆；`truncated=true`，600 秒時間預算截斷於第 72/165 頁，屬預期降級非異常）；887,296 B（約 867 KB）；耗時 608.7s；已累積天數 4 天（2026-08-28～08-31） |

### `airdrop_claim_pages`

| 項目 | 值 |
|---|---|
| 中文名／內容 | 空投資格規則頁（Starknet Provisions） |
| 程式內 DESC | 空投資格規則頁（本輪僅收錄 Starknet Provisions 地區限制規則頁，見模組說明） |
| 端點 | `https://www.starknet.io/provisions-geo-regulations/` |
| parser_version | 1 |
| MAX_ITEMS／等效上限 | 未記載 |
| 抓取頻率 | 每日一次（台北時間 08:00，`snap_crypto.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-28 親驗 https://www.starknet.io/robots.txt：HTTP 200，User-agent: * 的 Disallow 清單（查詢參數、/wp-admin、/tag/ 等）未涵蓋 /provisions-geo-regulations/，允許存取 |

### `audit_registry_certik`

| 項目 | 值 |
|---|---|
| 中文名／內容 | CertiK Skynet 首頁「Recently Audited」清單 |
| 程式內 DESC | CertiK Skynet 首頁「Recently Audited」最新審計清單（僅約 8 筆，非完整審計資料庫，見模組說明） |
| 端點 | `https://skynet.certik.com/` |
| parser_version | 1 |
| MAX_ITEMS／等效上限 | MIN_ITEMS=3（驗收下限，非上限） |
| 抓取頻率 | 每日一次（台北時間 08:00，`snap_crypto.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-28 親驗 https://skynet.certik.com/robots.txt：HTTP 200，User-agent: * 為 Allow: /，但 Disallow: /api/、/my/、/mobile/；本 adapter 只抓首頁 / 本體，未觸碰 /api/ |

### `cex_announcements`

| 項目 | 值 |
|---|---|
| 中文名／內容 | 交易所公告（標題／URL／時間／分類） |
| 程式內 DESC | 交易所公告（新幣上架等分類），僅存標題/URL/時間/分類，不存全文 |
| 端點（共 4 個） | `https://www.binance.com/bapi/composite/v1/public/cms/article/list/query`；`https://api.bybit.com/v5/announcements/index`；`https://www.okx.com/api/v5/support/announcements`；`https://api-manager.upbit.com/api/v1/announcements` |
| parser_version | 1 |
| MAX_ITEMS／等效上限 | 未記載 |
| 抓取頻率 | 每日一次（台北時間 08:00，`snap_crypto.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-28 沿用規格書實測結論：www.binance.com 此 API 路徑本輪未被 WAF 攔截（但主機同時存在會被 WAF 擋的頁面，每次改版須重新確認）；api.bybit.com、www.okx.com 本輪正常回應；api-manager.upbit.com 本輪撞到 HTTP 429，限流比 api.upbit.com 更嚴格，未親驗 robots.txt 內容（見已知的坑） |

### `cex_currency_status`

| 項目 | 值 |
|---|---|
| 中文名／內容 | 交易所幣種層級狀態旗標 |
| 程式內 DESC | 交易所幣種層級狀態旗標（Gate delisted／Coinbase status），HTX 沿用既有 cex_symbols 欄位 |
| 端點（共 2 個） | `https://api.gateio.ws/api/v4/spot/currencies`；`https://api.exchange.coinbase.com/currencies` |
| parser_version | 1 |
| MAX_ITEMS／等效上限 | 未記載 |
| 抓取頻率 | 每日一次（台北時間 08:00，`snap_crypto.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-28 親驗：Gate api.gateio.ws/robots.txt 未見 Disallow；Coinbase Exchange api.exchange.coinbase.com/robots.txt 回 401 Unauthorized（與 A6 相同的不尋常行為，但 /currencies 資料端點本輪實測不需認證、正常回 200） |

### `cex_earn_apr`

| 項目 | 值 |
|---|---|
| 中文名／內容 | CEX 理財年化率 |
| 程式內 DESC | CEX 理財年化率（Bybit 活期理財 FlexibleSaving／OKX 借貸利率總覽） |
| 端點（共 2 個） | `https://api.bybit.com/v5/earn/product?category=FlexibleSaving`；`https://www.okx.com/api/v5/finance/savings/lending-rate-summary` |
| parser_version | 1 |
| MAX_ITEMS／等效上限 | 未記載 |
| 抓取頻率 | 每日一次（台北時間 08:00，`snap_crypto.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-28 沿用規格書重驗結論：api.bybit.com、www.okx.com 本輪皆正常回應 200，規格書已列出實測筆數（Bybit 229 筆／OKX 169 筆），本 adapter 實作時另行親驗 robots.txt。 |

### `cex_symbols`

| 項目 | 值 |
|---|---|
| 中文名／內容 | 7 家 CEX 交易對／幣種狀態 |
| 程式內 DESC | 7 家 CEX 交易對／幣種狀態（Bybit／OKX／Bitget／HTX／Gate／KuCoin／MEXC） |
| 端點（共 7 個） | `https://api.bybit.com/v5/market/instruments-info?category=spot`；`https://www.okx.com/api/v5/public/instruments?instType=SPOT`；`https://api.bitget.com/api/v2/spot/public/symbols`；`https://api.huobi.pro/v1/common/symbols`；`https://api.gateio.ws/api/v4/spot/currency_pairs`；`https://api.kucoin.com/api/v2/symbols`；`https://api.mexc.com/api/v3/exchangeInfo` |
| parser_version | 1 |
| MAX_ITEMS／等效上限 | 未記載 |
| 抓取頻率 | 每日一次（台北時間 08:00，`snap_crypto.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-28 親驗：api.bybit.com/robots.txt HTTP 404（無限制）；www.okx.com/robots.txt HTTP 200，User-agent: * 的 Disallow 清單未涵蓋 /api/v5/public/instruments（允許）；api.bitget.com/robots.txt HTTP 403（略過，沿用既有實作已在抓取的行為，未變更）；api.huobi.pro/robots.txt HTTP 404（無限制）；api.gateio.ws/robots.txt HTTP 404（無限制）；api.kucoin.com/robots.txt HTTP 404（無限制）；api.mexc.com/robots.txt HTTP 404（無限制）。Binance 沿用既有實作排除（既有程式碼註記：robots 全站 Disallow），本輪未重新驗證 Binance，維持既有排除決定 |

### `cex_symbols_ext`

| 項目 | 值 |
|---|---|
| 中文名／內容 | 再 3 家 CEX 交易對清單（Kraken／Coinbase Exchange／Upbit） |
| 程式內 DESC | 新增 3 家交易所（Kraken／Coinbase Exchange／Upbit）交易對清單，擴充既有 cex_symbols |
| 端點（共 3 個） | `https://api.kraken.com/0/public/AssetPairs`；`https://api.exchange.coinbase.com/products`；`https://api.upbit.com/v1/market/all` |
| parser_version | 1 |
| MAX_ITEMS／等效上限 | 未記載 |
| 抓取頻率 | 每日一次（台北時間 08:00，`snap_crypto.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-28 親驗：Kraken api.kraken.com/robots.txt 無限制；Coinbase Exchange api.exchange.coinbase.com/robots.txt 回 401 Unauthorized（不尋常，但資料端點 /products 本身本輪實測不需認證、正常回 200，每次改版建議重新確認）；Upbit api.upbit.com/robots.txt 未見 Disallow（該站另一子網域 api-manager.upbit.com 對高頻請求會回 429，已於本 adapter 對 Upbit 使用較保守的 sleep） |

### `cex_withdrawal_limits`

| 項目 | 值 |
|---|---|
| 中文名／內容 | KuCoin 幣種提幣費與最低提幣額 |
| 程式內 DESC | KuCoin 幣種提幣費與最低提幣額（含各鏈參數） |
| 端點 | `https://api.kucoin.com/api/v3/currencies` |
| parser_version | 1 |
| MAX_ITEMS／等效上限 | MIN_ITEMS=1500（驗收下限，非上限） |
| 抓取頻率 | 每日一次（台北時間 08:00，`snap_crypto.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-28 親驗 https://api.kucoin.com/robots.txt：404（無 robots.txt，視為無限制） |

### `crypto_project_liveness`

| 項目 | 值 |
|---|---|
| 中文名／內容 | DefiLlama 駭客事件清單 |
| 程式內 DESC | DefiLlama 駭客事件清單（死亡監控資料面；網域存活監控面本輪列為未實作，見模組說明） |
| 端點 | `https://api.llama.fi/hacks` |
| parser_version | 1 |
| MAX_ITEMS／等效上限 | MIN_ITEMS=300（驗收下限，非上限） |
| 抓取頻率 | 每日一次（台北時間 08:00，`snap_crypto.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-28 親驗 https://api.llama.fi/robots.txt：HTTP 404（無 robots.txt，視為無限制） |

### `dao_proposal_snapshot`

| 項目 | 值 |
|---|---|
| 中文名／內容 | Snapshot DAO 提案中繼資料 |
| 程式內 DESC | Snapshot DAO 提案中繼資料快照（用於偵測提案被管理員刪除，不存投票紀錄） |
| 端點 | `https://hub.snapshot.org/graphql` |
| parser_version | 1 |
| MAX_ITEMS／等效上限 | MAX_PAGES=5；MIN_ITEMS=1（驗收下限，非上限） |
| 抓取頻率 | 每日一次（台北時間 08:00，`snap_crypto.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-28 親驗 https://hub.snapshot.org/robots.txt：60B 版本號 JSON banner（非傳統 robots.txt 格式，無路徑限制內容，依慣例視同無限制） |

### `defi_yield_rates`

| 項目 | 值 |
|---|---|
| 中文名／內容 | LST/LRT 質押與 DeFi 借貸利率 |
| 程式內 DESC | LST/LRT 質押與 DeFi 借貸利率（Lido／Rocket Pool／Ethena／Sky，四個原始回應各自一個子 key） |
| 端點（共 4 個） | `https://eth-api.lido.fi/v1/protocol/steth/apr/last`；`https://api.rocketpool.net/api/mainnet/payload`；`https://app.ethena.fi/api/yields/protocol-and-staking-yield`；`https://info-sky.blockanalitica.com/api/v1/overall/` |
| parser_version | 1 |
| MAX_ITEMS／等效上限 | 未記載 |
| 抓取頻率 | 每日一次（台北時間 08:00，`snap_crypto.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-28 沿用規格書重驗結論：四個端點本輪皆正常回應 200（Lido 137B／Rocket Pool 1,379B／Ethena 448B／Sky 1,084B），本 adapter 實作時另行親驗 robots.txt。 |

### `eth_validator_queue`

| 項目 | 值 |
|---|---|
| 中文名／內容 | 以太坊驗證者進出隊列各狀態筆數 |
| 程式內 DESC | 以太坊驗證者進出隊列各狀態筆數（pending_queued／pending_initialized／active_exiting／exited_unslashed），僅存計數不存個別公鑰 |
| 端點 | `https://ethereum-beacon-api.publicnode.com/eth/v1/beacon/states/head/validators?status={status}` |
| parser_version | 1 |
| MAX_ITEMS／等效上限 | 未記載 |
| 抓取頻率 | 每日一次（台北時間 08:00，`snap_crypto.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-28 沿用規格書重驗結論：ethereum-beacon-api.publicnode.com 本輪 4 個 status 皆正常回應 200，本 adapter 實作時另行親驗 robots.txt。 |

### `hf_trending_models`

| 項目 | 值 |
|---|---|
| 中文名／內容 | HuggingFace trending 模型清單 |
| 程式內 DESC | HuggingFace trending 模型清單（id / likes / downloads / trendingScore 等） |
| 端點 | `https://huggingface.co/api/models?sort=trendingScore&limit=1000` |
| parser_version | 1 |
| MAX_ITEMS／等效上限 | MIN_ITEMS=500（驗收下限，非上限） |
| 抓取頻率 | 每日一次（台北時間 08:00，`snap_crypto.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-28 親驗 https://huggingface.co/robots.txt：HTTP 200，User-Agent: * / Allow: / （全站無 Disallow） |

### `mcp_smithery`

| 項目 | 值 |
|---|---|
| 中文名／內容 | Smithery MCP 註冊表 |
| 程式內 DESC | Smithery MCP 註冊表（依 API 預設排序前段可見範圍，非全量；覆蓋率實測約 271 筆 / 官方宣稱總數約 10,916 筆，約 2.5%。API 硬性只能翻到第 5 頁，且跨頁排序會漂移造成大量重疊，271 筆左右是去重後可拿到的實際上限，非人為限量） |
| 端點 | `https://registry.smithery.ai/servers?page=N&pageSize=100` |
| parser_version | 2 |
| MAX_ITEMS／等效上限 | MAX_PAGE=5；MIN_ITEMS=200（驗收下限，非上限） |
| 抓取頻率 | 每日一次（台北時間 08:00，`snap_crypto.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-28 親驗 https://registry.smithery.ai/robots.txt：Content-Signal 格式，User-agent: * 未見 Disallow（一般語意為 Allow: /），僅具名爬蟲黑名單（ClaudeBot/GPTBot/CCBot 等 token）才會被排除；本 adapter 使用的 UA 字串不含這些具名 token |
| 實測值（2026-08-31 UTC） | 271 筆（官方回報總數約 11,103 筆，覆蓋率約 2.4%；端點硬性只能翻到第 5 頁，跨頁排序漂移，271 筆為去重後可得上限，非人為限量）；83,890 B（約 82 KB）；耗時 6.8s；已累積天數 4 天（2026-08-28～08-31） |

### `ofac_sanctions_crypto`

| 項目 | 值 |
|---|---|
| 中文名／內容 | OFAC SDN 制裁名單（美國財政部） |
| 程式內 DESC | OFAC SDN 制裁名單（美國財政部），含內嵌於 Remarks 的加密貨幣地址欄位 |
| 端點 | `https://www.treasury.gov/ofac/downloads/sdn.csv` |
| parser_version | 1 |
| MAX_ITEMS／等效上限 | 未記載 |
| 抓取頻率 | 每日一次（台北時間 08:00，`snap_crypto.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-28 親驗：www.treasury.gov/robots.txt 回 HTTP 200 但為一般 HTML 頁面（78,495B，非傳統 robots.txt 格式，無法解析出 Disallow 規則，依慣例視同無限制）；sanctionslistservice.ofac.treas.gov/robots.txt 回 404（無限制，備選端點未採用）；已另外實測確認 /ofac/downloads/sdn.csv 本身可直接 200 下載，不會被導向首頁 |

### `openrouter_models`

| 項目 | 值 |
|---|---|
| 中文名／內容 | OpenRouter 全模型清單與定價 |
| 程式內 DESC | OpenRouter 全模型清單與定價（id / pricing / context_length 等） |
| 端點 | `https://openrouter.ai/api/v1/models` |
| parser_version | 1 |
| MAX_ITEMS／等效上限 | 未記載 |
| 抓取頻率 | 每日一次（台北時間 08:00，`snap_crypto.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-28 親驗 https://openrouter.ai/robots.txt：HTTP 200，User-Agent: * / Allow: / / Disallow: /seo/ （只擋 /seo/，不影響 /api/v1/models） |

### `openrouter_providers`

| 項目 | 值 |
|---|---|
| 中文名／內容 | OpenRouter 供應商清單 |
| 程式內 DESC | OpenRouter 供應商清單（隱私政策 / 服務條款 / 資料中心地點等） |
| 端點 | `https://openrouter.ai/api/v1/providers` |
| parser_version | 1 |
| MAX_ITEMS／等效上限 | 未記載 |
| 抓取頻率 | 每日一次（台北時間 08:00，`snap_crypto.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-28 親驗 https://openrouter.ai/robots.txt：HTTP 200，User-Agent: * / Allow: / / Disallow: /seo/ （同 openrouter_models，同一主機） |

### `oracle_feed_directory`

| 項目 | 值 |
|---|---|
| 中文名／內容 | Chainlink／Pyth 價格餵送目錄 |
| 程式內 DESC | Chainlink／Pyth 價格餵送目錄（目前存在哪些餵送，供下游逐日比對集合差集） |
| 端點（共 2 個） | `https://reference-data-directory.vercel.app/feeds-mainnet.json`；`https://hermes.pyth.network/v2/price_feeds` |
| parser_version | 1 |
| MAX_ITEMS／等效上限 | 未記載 |
| 抓取頻率 | 每日一次（台北時間 08:00，`snap_crypto.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-28 沿用規格書重驗結論：兩個托管網域的 robots.txt 皆為 404（視為無限制），本輪皆正常回應 200（Chainlink 292 筆／Pyth 1,843 筆），本 adapter 實作時另行親驗 robots.txt。 |

### `payment_pricing_pages`

| 項目 | 值 |
|---|---|
| 中文名／內容 | Circle 官方開發者文件 Gateway 產品費率頁 |
| 程式內 DESC | Circle 官方開發者文件 Gateway 產品費率頁（跨鏈轉帳手續費率、各來源鏈 gas 費、轉發服務費） |
| 端點 | `https://developers.circle.com/gateway/references/fees` |
| parser_version | 1 |
| MAX_ITEMS／等效上限 | 未記載（本來源為單頁靜態文件，無分頁；驗收改用 `MIN_GAS_FEE_ROWS=5`／`MAX_GAS_FEE_ROWS=100`／`MIN_TEXT_LEN=1500` 三個結構性下限／上限防呆，非分頁上限） |
| 抓取頻率 | 每日一次（台北時間 08:00，`snap_crypto.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-09-02 親驗 https://www.circle.com/robots.txt：HTTP 200，User-agent: * 只有 Content-Signal: ai-train=no, search=yes, ai-input=yes，其餘為表單/policy-hub/search-results 等具體路徑的 Disallow，未見 /pricing 或本 adapter實際目標路徑被擋（但本輪發現 /pricing 本身已 301 導向 /contact/partner，非費率頁，故未採用）。2026-09-02 親驗 https://developers.circle.com/robots.txt（本 adapter 實際目標主機）：HTTP 200，全文為 'User-agent: * Content-Signal: ai-train=yes, search=yes, ai-input=yes Disallow: /cdn-cgi/ Allow: /_next/image Disallow: /_next/ Sitemap: https://developers.circle.com/sitemap.xml'，本 adapter 目標路徑 /gateway/references/fees 不在 /cdn-cgi/ 或 /_next/ 之下 → 允許。 |
| 實測值（2026-09-02 UTC，首次快照） | 812 B；耗時 0.1s；`attempts=1`；已累積天數 1 天。內容：`transfer_fee` 0.005%（0.5 basis points）、`gas_fees_by_source_chain` 12 條鏈（Arbitrum／Avalanche／Base／Ethereum／HyperEVM／OP／Polygon PoS／Sei／Solana／Sonic／Unichain／World Chain）、`forwarding_fee` $0.05／筆、`main_text_len` 3,253 字元。次日（2026-09-03 UTC）再次快照 809 B、耗時 0.3s，`gas_fees` 等欄位數字穩定 |
| 規格書原定目標網址 | `https://www.circle.com/pricing`（本輪親驗已 301 導向 `https://www.circle.com/contact/partner` 聯絡表單頁，不含任何費率數字，故改用上述 Circle 官方開發者文件頁；判斷過程詳見本節下方〈已排除的來源〉的 Circle 定價頁條目與 adapter 原始碼內註記） |
| 收錄範疇限制 | 僅收錄 Gateway 產品費率頁；Circle 另有 CCTP／Wallets／xReserve／StableFX 等產品各自獨立的費率文件頁，本輪未擴大收錄（adapter 內 `not_covered` 欄位如實標註） |

### `payment_protocol_repos`

| 項目 | 值 |
|---|---|
| 中文名／內容 | 支付協議規格版本 GitHub Repo 中繼資料 |
| 程式內 DESC | 支付協議規格版本 GitHub Repo 中繼資料（x402／AP2／L402，含併入的 B3） |
| 端點（共 3 個） | `https://api.github.com/repos/x402-foundation/x402`；`https://api.github.com/repos/google-agentic-commerce/AP2`；`https://api.github.com/repos/lightninglabs/L402` |
| parser_version | 1 |
| MAX_ITEMS／等效上限 | 未記載 |
| 抓取頻率 | 每日一次（台北時間 08:00，`snap_crypto.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-28 親驗 https://api.github.com/robots.txt：HTTP 404（無限制） |

### `project_tokenomics_docs`

| 項目 | 值 |
|---|---|
| 中文名／內容 | 專案官方 tokenomics 文件頁 |
| 程式內 DESC | 專案官方 tokenomics 文件頁（本輪僅收錄 Arbitrum Foundation 空投分配文件，見模組說明） |
| 端點 | `https://docs.arbitrum.foundation/airdrop-eligibility-distribution` |
| parser_version | 1 |
| MAX_ITEMS／等效上限 | 未記載 |
| 抓取頻率 | 每日一次（台北時間 08:00，`snap_crypto.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-28 親驗 https://docs.arbitrum.foundation/robots.txt：HTTP 404（該站沒有 robots.txt，視為無限制；根路徑本身可正常存取，非封鎖造成的 404） |

### `vast_gpu`

| 項目 | 值 |
|---|---|
| 中文名／內容 | Vast.ai GPU 租賃市場報價 |
| 程式內 DESC | Vast.ai GPU 租賃市場報價（on-demand bundles，依 dph_total 由低到高排序） |
| 端點 | `https://console.vast.ai/api/v0/bundles/` |
| parser_version | 1 |
| MAX_ITEMS／等效上限 | 未記載 |
| 抓取頻率 | 每日一次（台北時間 08:00，`snap_crypto.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-28 親驗 https://console.vast.ai/robots.txt：HTTP 200，User-agent: * / Allow: /（全站無 Disallow） |

### `x402_bazaar`

| 項目 | 值 |
|---|---|
| 中文名／內容 | x402 Bazaar 全量掛牌 |
| 程式內 DESC | x402 Bazaar 全量掛牌（Coinbase CDP x402 discovery API，分頁抓完） |
| 端點 | `https://api.cdp.coinbase.com/platform/v2/x402/discovery/resources` |
| parser_version | 1 |
| MAX_ITEMS／等效上限 | 未記載 |
| 抓取頻率 | 每日一次（台北時間 08:00，`snap_crypto.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-28 親驗 https://api.cdp.coinbase.com/robots.txt：HTTP 404（無 robots.txt，視為無限制；與既有 track-crypto/scripts/snap_crypto.py 沿用至今的抓取行為一致） |

### 已停抓

| 來源 | 停抓日期 | 理由 | 歷史資料處置 |
|---|---|---|---|
| `x402_index_thirdparty` | 2026-09-02 | 與軌一權威來源 `x402_bazaar` 高度重疊（同一 x402 生態系）：2026-09-02 UTC 直接讀取兩者當日快照原始碼實測，`x402_index_thirdparty` 當日 `total=1044`、`/server/` 前綴 `server_count=1000`，同日 `x402_bazaar` `total=14929`，`x402_index_thirdparty` 的 `/server/` 前綴筆數僅約為 `x402_bazaar` 掛牌數的 6.7%（即 `x402_bazaar` 約為其 14.9 倍）。且 `total=1044`／`server_count=1000` 這兩個數字在 2026-08-31 與 2026-09-02（相隔 3 天）逐位元組相同，`server_count` 恰好卡在 1,000 這個整數，指向第三方索引站 sitemap 本身有收錄／分頁上限，非本專案抓取邏輯漏抓。 | 2026-08-28～2026-09-02 共 6 天快照（`2026-08-28.json.gz` ~ `2026-09-02.json.gz`）完整保留於 `track-crypto/data/x402_index_thirdparty/`，不刪除、不覆寫；adapter 原始碼**移動**（非刪除）至 `track-crypto/retired_adapters/x402_index_thirdparty.py`，檔案內容未修改（`sha256` 搬移前後一致），只是不再被 `snap_crypto.py`／`healthcheck.py`／`daily_report.py` 的 `track-crypto/adapters/*.py` 自動探索機制掃到，故**不計入本次 24 個** |

`x402_index_thirdparty` 停抓前的端點與驗證細節（歷史記錄，供查證）：

| 項目 | 值 |
|---|---|
| 中文名／內容 | x402scan 第三方索引 sitemap URL 清單 |
| 程式內 DESC | x402scan 第三方索引 sitemap URL 清單（僅涵蓋約官方 x402 Bazaar 掛牌數的 6.8%，屬輔助視角非核心資料源） |
| 端點 | `https://www.x402scan.com/sitemap.xml` |
| parser_version | 1 |
| MAX_ITEMS／等效上限 | 未記載（adapter 內建驗收下限：總數 ≥500、`/server/` 前綴 ≥300） |
| 抓取頻率（停抓前） | 每日一次（台北時間 08:00，`snap_crypto.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-28 親驗 https://www.x402scan.com/robots.txt：Allow: /，Content-Signal: search=yes, ai-train=no, ai-input=yes |
| 最後一次實測值（2026-09-02 UTC，停抓當天） | 1,044 個 URL（`/server/` 前綴 1,000 個，約為同日 `x402_bazaar` 官方掛牌數 14,929 筆的 6.7%）；23,423 B（約 22.9 KB） |

（另見上方 `mcp_registry` 的停抓說明，是本專案第二個「停抓、歷史資料保留」案例。）

## track-gov（18 個來源）

抓取程式：`track-gov/scripts/snap_gov.py`（自動載入 `track-gov/adapters/*.py`）

每筆欄位：`id`、`url`、`title`、`date`、`body_text`、`body_sha256`（`fsc_clarification` 另保留 `dataserno`）。

### `cbc_press`

| 項目 | 值 |
|---|---|
| 機關與類別 | 中央銀行 新聞稿／新聞參考資料 |
| 程式內 DESC | 中央銀行新聞稿 |
| SOURCE_HOME（清單頁） | `https://www.cbc.gov.tw/tw/lp-302-1.html` |
| parser_version | 未記載 |
| MAX_ITEMS／等效上限 | MAX_ITEMS=100；MAX_PAGES=5 |
| 抓取頻率 | 每日一次（台北時間 09:30，`snap_gov.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-27 親驗 https://www.cbc.gov.tw/robots.txt：伺服器不提供 robots.txt，而是以 302 導向中文首頁 https://www.cbc.gov.tw/tw/mp-1.html 回傳 HTML，因此全站沒有任何 Disallow 規則 → 目標路徑 /tw/lp-302-*.html 與 /tw/cp-302-*.html 未被禁止 |

### `ey_press`

| 項目 | 值 |
|---|---|
| 機關與類別 | 行政院 本院新聞 |
| 程式內 DESC | 行政院本院新聞（新聞與公告） |
| SOURCE_HOME（清單頁） | `https://www.ey.gov.tw/Page/6485009ABEC1CB9C` |
| parser_version | 2 |
| MAX_ITEMS／等效上限 | MAX_ITEMS=100；MAX_PAGES=1 |
| 抓取頻率 | 每日一次（台北時間 09:30，`snap_gov.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-27 親驗 https://www.ey.gov.tw/robots.txt，全文為 'user-agent: *' / 'disallow: /Upload' / 'disallow:/Program/EY/Hope_decision.ascx' → 目標路徑 /Page/* 未被 Disallow（不抓 /Upload 下的附件） |

### `fda_clarify`

| 項目 | 值 |
|---|---|
| 機關與類別 | 衛生福利部食品藥物管理署（食藥署） 食藥闢謠專區 |
| 程式內 DESC | 食藥署 食藥闢謠專區 |
| SOURCE_HOME（清單頁） | `https://www.fda.gov.tw/TC/news.aspx?cid=5049` |
| parser_version | 1 |
| MAX_ITEMS／等效上限 | MAX_ITEMS=50 |
| 抓取頻率 | 每日一次（台北時間 09:30，`snap_gov.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-28 親驗 https://www.fda.gov.tw/robots.txt：User-agent: * 僅 Disallow /TC/personalized*.aspx /TC/pwd.aspx /TraceClick.aspx，目標 news.aspx / newsContent.aspx 不在其下 → 允許（另有 User-agent: ClaudeBot / GPTBot 具名 Disallow: /，本 adapter 使用自訂識別性 UA，非 ClaudeBot/GPTBot，不受此條款拘束） |
| 實測值（2026-08-31 UTC） | 33 筆（`truncated=true`，600 秒時間預算截斷，目標 MAX_ITEMS=50 未達成）；14,937 B（約 14.6 KB）；耗時 610.3s；已累積天數 4 天（2026-08-28～08-31） |

### `fsc_clarification`

| 項目 | 值 |
|---|---|
| 機關與類別 | 金融監督管理委員會（金管會） 即時新聞澄清 |
| 程式內 DESC | 金管會即時新聞澄清 |
| SOURCE_HOME（清單頁） | `https://www.fsc.gov.tw/ch/home.jsp?id=609&parentpath=0,7,478` |
| parser_version | 2 |
| MAX_ITEMS／等效上限 | MAX_PAGES=50 |
| 抓取頻率 | 每日一次（台北時間 09:30，`snap_gov.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-26 親驗 https://www.fsc.gov.tw/robots.txt：唯一 Disallow 為 /uploaddowndoc（附件下載），目標 home.jsp 不在其下 → 允許 |

### `fsc_lawnotice`

| 項目 | 值 |
|---|---|
| 機關與類別 | 金融監督管理委員會（金管會） 法規草案預告 |
| 程式內 DESC | 金管會法規草案預告 |
| SOURCE_HOME（清單頁） | `https://www.fsc.gov.tw/ch/home.jsp?id=133&parentpath=0,3` |
| parser_version | 1 |
| MAX_ITEMS／等效上限 | MAX_PAGES=8 |
| 抓取頻率 | 每日一次（台北時間 09:30，`snap_gov.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-28 親驗 https://www.fsc.gov.tw/robots.txt：User-agent: Googlebot / Disallow: /uploaddowndoc（附件下載目錄）。與 fsc_clarification 同網域，重新親驗結果一致：僅對 Googlebot 禁止 /uploaddowndoc，對 * 無限制，目標 home.jsp 不在其下 → 允許 |
| 實測值（2026-08-31 UTC） | 100 筆；25,281 B（約 24.7 KB）；耗時 244.4s；已累積天數 4 天（2026-08-28～08-31） |

### `fsc_penalty`

| 項目 | 值 |
|---|---|
| 機關與類別 | 金融監督管理委員會（金管會） 裁罰案件 |
| 程式內 DESC | 金管會裁罰案件 |
| SOURCE_HOME（清單頁） | `https://www.fsc.gov.tw/ch/home.jsp?id=131&parentpath=0,2` |
| parser_version | 1 |
| MAX_ITEMS／等效上限 | MAX_PAGES=8 |
| 抓取頻率 | 每日一次（台北時間 09:30，`snap_gov.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-28 親驗 https://www.fsc.gov.tw/robots.txt：User-agent: Googlebot / Disallow: /uploaddowndoc（附件下載目錄）。與 fsc_clarification 同網域，重新親驗結果一致：僅對 Googlebot 禁止 /uploaddowndoc，對 * 無限制，目標 home.jsp 不在其下 → 允許 |
| 實測值（2026-08-31 UTC） | 100 筆；140,021 B（約 136.7 KB）；耗時 300.7s；已累積天數 4 天（2026-08-28～08-31） |

### `ftc_decision`

| 項目 | 值 |
|---|---|
| 機關與類別 | 公平交易委員會 本會行政決定（處分書及不處分決議書） |
| 程式內 DESC | 公平交易委員會 本會行政決定（處分書及不處分決議書） |
| SOURCE_HOME（清單頁） | `https://www.ftc.gov.tw/internet/main/decision/decisionList.aspx?mid=11` |
| parser_version | 1 |
| MAX_ITEMS／等效上限 | MAX_PAGES=10 |
| 抓取頻率 | 每日一次（台北時間 09:30，`snap_gov.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-28 親驗 https://www.ftc.gov.tw/robots.txt：GET 回 200，但內容是首頁 HTML（與亂數不存在路徑 /this-path-should-not-exist-zzz 回應長度相同，屬 ASP.NET 對未匹配路徑的預設頁，非真正 robots.txt）→ 判定無真正 robots.txt，技術上無 Disallow 限制存在 |
| 實測值（2026-08-31 UTC） | 100 筆；17,478 B（約 17.1 KB）；耗時 187.3s；已累積天數 4 天（2026-08-28～08-31） |

### `moda_press`

| 項目 | 值 |
|---|---|
| 機關與類別 | 數位發展部 新聞發布 |
| 程式內 DESC | 數位發展部新聞發布 |
| SOURCE_HOME（清單頁） | `https://moda.gov.tw/press/press-releases/372` |
| parser_version | 2 |
| MAX_ITEMS／等效上限 | MAX_ITEMS=100；MAX_PAGES=1 |
| 抓取頻率 | 每日一次（台北時間 09:30，`snap_gov.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-27 親驗 https://moda.gov.tw/robots.txt 與 https://www.moda.gov.tw/robots.txt：兩者皆 HTTP 404 Not Found（全站無 robots.txt，即無任何 Disallow 規則）→ 目標路徑 /press/press-releases/* 未被 Disallow |

### `moe_clarify`

| 項目 | 值 |
|---|---|
| 機關與類別 | 教育部 即時新聞澄清 |
| 程式內 DESC | 教育部即時新聞澄清（對外界報導的官方澄清稿） |
| SOURCE_HOME（清單頁） | `https://www.edu.tw/News.aspx?n=FD56C961F1677400&sms=E6059C30DDBD5135` |
| parser_version | 未記載 |
| MAX_ITEMS／等效上限 | MAX_ITEMS=100；MAX_PAGES=2 |
| 抓取頻率 | 每日一次（台北時間 09:30，`snap_gov.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-27 親驗 https://www.edu.tw/robots.txt，全文僅 5 行：User-agent: * / Disallow: /WebResource.axd / Disallow: /src / Disallow: /Scripts/fu_Accessibility.js / Disallow: /search。本 adapter 只取 /News.aspx 與 /News_Content.aspx，兩者皆不在上述 4 條 Disallow 之下 → 目標路徑未被 Disallow。 |

### `moe_press`

| 項目 | 值 |
|---|---|
| 機關與類別 | 教育部 即時新聞 |
| 程式內 DESC | 教育部即時新聞（新聞稿） |
| SOURCE_HOME（清單頁） | `https://www.edu.tw/News.aspx?n=9E7AC85F1954DDA8&sms=169B8E91BB75571F` |
| parser_version | 未記載 |
| MAX_ITEMS／等效上限 | MAX_ITEMS=100；MAX_PAGES=2 |
| 抓取頻率 | 每日一次（台北時間 09:30，`snap_gov.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-27 親驗 https://www.edu.tw/robots.txt，全文僅 5 行：User-agent: * / Disallow: /WebResource.axd / Disallow: /src / Disallow: /Scripts/fu_Accessibility.js / Disallow: /search。本 adapter 只取 /News.aspx 與 /News_Content.aspx，兩者皆不在上述 4 條 Disallow 之下 → 目標路徑未被 Disallow。 |

### `moea_press`

| 項目 | 值 |
|---|---|
| 機關與類別 | 經濟部 本部新聞 |
| 程式內 DESC | 經濟部本部新聞（新聞稿） |
| SOURCE_HOME（清單頁） | `https://www.moea.gov.tw/MNS/populace/news/News.aspx?kind=1&menu_id=40` |
| parser_version | 1 |
| MAX_ITEMS／等效上限 | MAX_ITEMS=100；MAX_PAGES=10 |
| 抓取頻率 | 每日一次（台北時間 09:30，`snap_gov.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-28 親驗 https://www.moea.gov.tw/robots.txt（HTTP 200，64 bytes，last-modified 2023-09-25，快取穩定，非動態產生）。全文只有四行：\n  User-Agent:ZoomEye\n  Disallow:/\n  User-Agent:*\n  Disallow:/MNS_OLD/\n第一段只針對具名爬蟲 ZoomEye 全站封鎖，與本 adapter 的 UA 無關；第二段 'User-Agent:*' 對所有其他 UA（含本 adapter）只禁止 /MNS_OLD/ 這個舊站目錄。本 adapter 目標路徑 /MNS/populace/news/News.aspx 屬於 /MNS/（新站），不是 /MNS_OLD/，不落在任何 Disallow 之下 → 允許抓取。先前文件將第一段 ZoomEye 專屬的 'Disallow:/' 誤讀為全站封鎖，經本次重新親驗證實為誤讀；本次親驗結果與誤讀說法不同，以本次親驗為準。 |

### `mof_press`

| 項目 | 值 |
|---|---|
| 機關與類別 | 財政部 本部新聞 |
| 程式內 DESC | 財政部本部新聞（新聞稿） |
| SOURCE_HOME（清單頁） | `https://www.mof.gov.tw/multiplehtml/384fb3077bb349ea973e7fc6f13b6974` |
| parser_version | 未記載 |
| MAX_ITEMS／等效上限 | MAX_ITEMS=100；MAX_PAGES=10 |
| 抓取頻率 | 每日一次（台北時間 09:30，`snap_gov.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-27 親驗 https://www.mof.gov.tw/robots.txt：全文僅兩行 'User-agent: *' / 'Disallow: /download/'；本 adapter 只取 /multiplehtml/ 與 /singlehtml/，未落在 /download/ 之下 → 未被 Disallow |

### `mohw_press`

| 項目 | 值 |
|---|---|
| 機關與類別 | 衛生福利部 焦點新聞 |
| 程式內 DESC | 衛生福利部焦點新聞（新聞稿） |
| SOURCE_HOME（清單頁） | `https://www.mohw.gov.tw/lp-16-1.html` |
| parser_version | 未記載 |
| MAX_ITEMS／等效上限 | MAX_ITEMS=100；MAX_PAGES=5 |
| 抓取頻率 | 每日一次（台北時間 09:30，`snap_gov.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-27 親驗 https://www.mohw.gov.tw/robots.txt：全檔僅一行 'User-agent: *'，沒有任何 Disallow 行 → 目標路徑 /lp-16-*.html 與 /cp-16-*.html 未被 Disallow |

### `moi_press`

| 項目 | 值 |
|---|---|
| 機關與類別 | 內政部 新聞稿 |
| 程式內 DESC | 內政部新聞稿 |
| SOURCE_HOME（清單頁） | `https://www.moi.gov.tw/News.aspx?n=4&sms=9009` |
| parser_version | 2 |
| MAX_ITEMS／等效上限 | MAX_ITEMS=100；MAX_PAGES=1 |
| 抓取頻率 | 每日一次（台北時間 09:30，`snap_gov.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-27 親驗 https://www.moi.gov.tw/robots.txt：HTTP 404 Not Found（全站無 robots.txt，即無任何 Disallow 規則）→ 目標路徑 /News.aspx、/News_Content.aspx 未被 Disallow |

### `moj_press`

| 項目 | 值 |
|---|---|
| 機關與類別 | 法務部 新聞發布 |
| 程式內 DESC | 法務部新聞發布 |
| SOURCE_HOME（清單頁） | `https://www.moj.gov.tw/2204/2795/2796/Lpsimplelist` |
| parser_version | 未記載 |
| MAX_ITEMS／等效上限 | MAX_ITEMS=50；MAX_PAGES=5 |
| 抓取頻率 | 每日一次（台北時間 09:30，`snap_gov.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-27 親驗 https://www.moj.gov.tw/robots.txt（伺服器 301 導向 https://www.moj.gov.tw/robots）：全檔只有兩行空白與一行 'Sitemap: https://www.moj.gov.tw/sitemap?id=2204'，沒有任何 User-agent / Disallow 規則 → 目標路徑 /2204/2795/2796/** 未被 Disallow |

### `mol_press`

| 項目 | 值 |
|---|---|
| 機關與類別 | 勞動部 新聞稿 |
| 程式內 DESC | 勞動部新聞稿 |
| SOURCE_HOME（清單頁） | `https://www.mol.gov.tw/1607/1632/1633/lpsimplelist` |
| parser_version | 未記載 |
| MAX_ITEMS／等效上限 | MAX_ITEMS=100；MAX_PAGES=3 |
| 抓取頻率 | 每日一次（台北時間 09:30，`snap_gov.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-27 親驗 https://www.mol.gov.tw/robots.txt：全文為 'user-agent: *' + 'disallow: /bin/*'、'disallow: /App_Data/*'、'disallow: /App_Plugins/*'、'disallow: /Umbraco/*'；本 adapter 只取 /1607/1632/1633/ 之下的清單與內頁 → 未被 Disallow |

### `pres_news`

| 項目 | 值 |
|---|---|
| 機關與類別 | 總統府 本府新聞稿 |
| 程式內 DESC | 總統府新聞（本府新聞稿） |
| SOURCE_HOME（清單頁） | `https://www.president.gov.tw/Page/35` |
| parser_version | 2（2026-08-31 改真分頁；v1 僅取首頁 15 筆） |
| MAX_ITEMS／等效上限 | MAX_ITEMS=100、MAX_PAGES=7（每頁固定 15 筆） |
| 抓取頻率 | 每日一次（台北時間 09:30，`snap_gov.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-28 親驗 https://www.president.gov.tw/robots.txt：User-agent: * / Allow: / ，全站無任何 Disallow → 允許 |
| 實測值（2026-08-31 UTC） | 15 筆（v1 僅取清單首頁）；42,216 B（約 41.2 KB）；耗時 39.2s；已累積天數 4 天（2026-08-28～08-31）。**2026-08-31 反解官方分頁 API（POST /WebAPI/News/List），官方總筆數 29,393；v2 起每日取最新 100 筆，整合測試耗時 186.8s，實測值待 2026-09-01 排程後更新** |

### `tpe_clarify`

| 項目 | 值 |
|---|---|
| 機關與類別 | 台北市政府 即時新聞澄清 |
| 程式內 DESC | 台北市政府即時新聞澄清 |
| SOURCE_HOME（清單頁） | `https://www.gov.taipei/News.aspx?n=74806083EBDF5A03&sms=72544237BBE4C5F6` |
| parser_version | 1 |
| MAX_ITEMS／等效上限 | MAX_ITEMS=50；MAX_PAGES=8 |
| 抓取頻率 | 每日一次（台北時間 09:30，`snap_gov.py`） |
| robots.txt 結論（adapter 內 `ROBOTS_VERIFIED` 原文） | 2026-08-28 親驗 https://www.gov.taipei/robots.txt：HTTP 404 Not Found（全站無 robots.txt，即無任何 Disallow 規則）→ 目標路徑 /News.aspx、/News_Content.aspx 未被 Disallow |
| 實測值（2026-08-31 UTC） | 39 筆（`truncated=true`，600 秒時間預算截斷，目標 MAX_ITEMS=50 未達成）；27,850 B（約 27.2 KB）；耗時 603.6s；已累積天數 4 天（2026-08-28～08-31） |

### 個資揭露（2026-08-31 擴充稽核後補充，涵蓋全部 18 個機關）

本專案**照原文保存，不做遮蔽**。理由：存檔的意義在於保留機關當時實際發布的原貌，
任何遮蔽都會讓「內容是否被改寫」的比對失去基準。

已知情況，如實揭露：

- **`moea_press`（經濟部）** — **規模最大**：100 篇中 **89 篇**的新聞稿結尾聯絡資訊含
  **公務員個人行動電話**，涉及約 40–50 位不同人員。這是機關自行刊登於官網新聞稿內文的
  公務聯絡方式，本專案原樣保存。
- **`mof_press`（財政部）**：部分新聞稿的聯絡人簽名檔含**承辦人姓名與個人行動電話**，
  重複出現於 4 篇以上。
- **`tpe_clarify`（台北市政府澄清稿）**：**14 筆行動電話**（承辦人聯絡方式）、
  結尾聯絡人姓氏標記約 18 處。與經濟部/財政部型態相同，屬機關公開聯絡窗口，原樣保存。
- **`fsc_lawnotice`（金管會/證期局法規訓誡通知）**：**18 個 email**（皆為 `fsc.gov.tw`／
  `sfb.gov.tw` 機關公務信箱）、約 63 個機關辦公室市話號碼、84 處承辦人聯絡人姓氏標記、
  3 處機關辦公地址。信箱與地址經比對皆屬機關公務資訊，非私人。
- **`fsc_penalty`（金管會裁罰案）**：26 個不同的受處分公司登記地址（法人地址，非個人住家）、
  190 處「代表人／負責人 OO 先生」型態的姓氏去識別化揭露（機關官方文書慣例本就以「姓氏＋先生／小姐」
  發布，未揭露全名）。`fsc_penalty` 1 筆裁罰案內文含金融帳號片段（機關原文即已部分遮蔽，僅存末 4 碼）。
- 其他機關（`fda_clarify`、`ftc_decision`、`pres_news` 及舊 12 機關中的 10 個）抽驗結果：
  聯絡電話多為機關代表號或分機，無個人號碼；`ftc_decision` 案由未發現受處分自然人姓名，
  受處分對象皆為公司/公會等法人。
- 掃描範圍：**18 個機關**、涵蓋 2 個歷史日期（舊 12 機關）＋ 2026-08-31 最新一日（新 6 機關）、
  合計 2,254 筆（舊 12 機關）＋ 387 筆（新 6 機關）正文。
- 身分證字號：**18 個來源全數 0 命中**（1,127 筆結構化掃描 + 387 筆新機關掃描皆乾淨）。
- 政府新聞稿中的裁罰對象多為法人；自然人姓名官方多已遮罩（如「林00先生」）。

若當事人要求移除，請至 GitHub 開 issue。

## 人工封存來源（非每日 cron，manual_adapters）

### `mcp_pulsemcp`

程式在 `track-crypto/manual_adapters/mcp_pulsemcp.py`，**不在 `snap_crypto.py` 每日排程內**，
為人工手動執行的一次性/多次封存，端點 `https://api.pulsemcp.com/v0beta/servers`。
官方已公告 v0beta API 排程性棄用：2026-01 起 1% 請求隨機失敗、2026-04 起 10%、2026-06 起 50%，
**2026-09 全面停用（100% 失敗）**。2026-08-31 UTC 停用前加抓一次：官方回報 `total_count=21983` 筆，
本次人工執行完整分頁抓取（沿用官方 `next` 分頁連結，遇隨機 410 逐頁重試），
去重後實得 **21982 筆**（覆蓋率約 99.995%，`_meta.truncated=true`，差 1 筆記錄為分頁邊界筆數波動，
非請求失敗漏抓），存於 `track-crypto/data/mcp_pulsemcp/2026-08-31.json.gz`；
上一次封存為 2026-08-28（單頁 250 筆）。個資掃描結果（去識別化統計）：email 樣式命中 4 筆，
皆出現在 `EXPERIMENTAL_ai_generated_description`（AI 產生的服務描述文字）欄位內，屬開發者
自行於服務介紹頁公開揭露的聯絡方式，非結構化「聯絡人」欄位；電話樣式命中 8 筆，逐一核對後
全數為誤判（URL slug 或 `github_stars`／`package_download_count` 等數值欄位中的連續數字，
非真實電話號碼）；身分證字號等台灣特有 PII 未見（本來源為 MCP 伺服器全球性註冊表，非台灣
在地資料）。依專案「照原文保存、如實揭露、不做遮蔽」原則直接存入快照，未做遮蔽。

**2026-09-04 UTC 第二輪加抓實測（依 `specs/SPEC-pulsemcp-2.md`）**：加抓前先做端點可用性探測，分兩批共 **50 次**請求（每次間隔 1.5～2 秒），**全數回應 `HTTP 410 API_SUNSET`**（成功率 0/50＝0%）；回應標頭含 `x-runtime`（應用層計時）、`content-type: application/json`、`cf-cache-status: DYNAMIC`，確認是源站應用程式本身即時產生的回應，非邊緣層快取或速率限制假象。此結果符合官方錯誤訊息內建的公告時程「September 2026: Fully sunset (100%)」，判定：**端點已進入 2026-09 全面停用階段，本輪無法再抓取任何資料（0 筆）**。因此本輪**未新增快照**，覆蓋率、與 08-31 版差異比對、個資掃描三項在此情況下皆為「不適用」。額外查證：本輪順便重新檢視 `robots.txt`，發現除既有 Cloudflare 代管的 `Content-Signal` 區塊（`User-agent: * / Allow: /`）外，區塊之後另有一組獨立的 `User-agent: * / Disallow: /`；依 Cloudflare 官方文件，其代管區塊是**疊加於既有檔案之上**，故此 `Disallow: /` 較可能是站方原本既有設定，並非新增；依 RFC 9309 §2.2.1／§2.2.2，同一 `User-agent: *` 的多個群組須合併，路徑等長的 `Allow` 與 `Disallow` 相衝突時應以 `Allow` 為準——但因**端點本身在應用層已 100% 停用**，此 robots.txt 疑義對本輪結論沒有實質影響，僅作為紀錄。結論：`mcp_pulsemcp` 自此**固定停留在 2026-08-31 封存版本（21,982／21,983 筆，覆蓋率 99.995%）為最終版本**，應視為已停用來源，不會再有更新。完整探測記錄與 robots.txt 分析見`docs/pulsemcp-archive-2-report.md`。

## 已排除的來源

以下清單沿用既有 `docs/sources.md` 記載，本輪未重新驗證（唯讀規則，未連線這些網站覆核）：

| 來源 | 排除理由 |
|---|---|
| Binance | robots.txt 全站 `Disallow: /` |
| Smithery `/api/` | robots.txt `Disallow: /api/` |
| 環境部 | robots.txt 明文禁止 `/Page/`、`/page/`、`/News_Content.aspx`、`/*?page=*`；且全站 Cloudflare JS 挑戰 |
| Tasker | robots.txt 限制 |
| udn.com | robots.txt 禁止商業用途 |
| Circle 定價頁 | `circle.com/pricing` 已 301 導向行銷表單頁，無任何費率數字 |
| Jupiter／EigenLayer／Hyperliquid 相關頁 | 網域 DNS 已失效或 404 |

## 免責

本檔僅記錄公開端點／網頁在特定時間點的技術規格與 robots.txt 親驗結論，不對資料正確性作任何保證，
不構成任何投資建議、法律意見或分析觀點。
