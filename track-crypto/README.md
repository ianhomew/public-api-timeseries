# track-crypto — 加密貨幣與 AI 算力市場每日快照

回上層：[專案總覽](../README.md)

這是原始資料存檔，**不含任何分析、觀點或投資建議**。

每天對 24 個公開端點各取一次快照，一天一檔 `YYYY-MM-DD.json.gz`（日期為 **UTC**），**永不覆蓋**。

## 收錄來源（24 個）

2026-08-31（UTC）實測值（來源：`track-crypto/data/_manifest/2026-08-31.json`、`track-crypto/logs/cron.log`）。
24 個來源每日壓縮後合計約 **9.33 MB**（9,780,952 B），總耗時約 **736 秒**（約 12.3 分鐘；
其中 `agent_virtuals` 一項就佔 608.7 秒，因觸發 600 秒時間預算而截斷，見下方說明）。

### 交易所（6）
| 來源 | 內容 | 體積 | 耗時 |
|---|---|---|---|
| `cex_symbols` | 7 家交易對／幣種狀態（Bybit/OKX/Bitget/HTX/Gate/KuCoin/MEXC） | 396 KB（405,624 B） | 13.1s |
| `cex_symbols_ext` | 再 3 家（Kraken/Coinbase Exchange/Upbit） | 61.5 KB（62,967 B） | 5.1s |
| `cex_currency_status` | 幣種層級狀態旗標（Gate delisted／Coinbase status） | 285.5 KB（292,357 B） | 3.9s |
| `cex_withdrawal_limits` | KuCoin 提幣費與最低提幣額（含各鏈參數） | 138.8 KB（142,094 B） | 0.5s |
| `cex_announcements` | 交易所公告（只存標題／URL／時間／分類，不存全文） | 6.8 KB（7,000 B） | 15.6s |
| `cex_earn_apr` | 理財年化率（Bybit 活期／OKX 借貸） | 8.6 KB（8,804 B） | 2.0s |

### 鏈上與 DeFi（4）
| 來源 | 內容 | 體積 | 耗時 |
|---|---|---|---|
| `defi_yield_rates` | Lido／Rocket Pool／Ethena／Sky 質押與借貸利率 | 1.4 KB（1,484 B） | 3.4s |
| `eth_validator_queue` | 驗證者進出隊列**各狀態筆數**（不存個別公鑰） | 214 B | 4.3s |
| `oracle_feed_directory` | Chainlink／Pyth 價格餵送目錄（供逐日比對集合差集） | 162.8 KB（166,669 B） | 1.3s |
| `dao_proposal_snapshot` | Snapshot DAO 提案中繼資料（偵測提案被刪除，不存投票紀錄） | 386.3 KB（395,538 B） | 9.6s |

### 支付與 agent 生態（4）
| 來源 | 內容 | 體積 | 耗時 |
|---|---|---|---|
| `x402_bazaar` | x402 全量掛牌（CDP discovery API），今日 14,410 筆 | 5.70 MB（5,979,699 B） | 43.3s |
| `x402_index_thirdparty` | x402scan 第三方索引 sitemap URL 清單，**新來源** | 22.9 KB（23,431 B） | 1.5s |
| `payment_protocol_repos` | x402／AP2／L402 規格版本 repo 中繼資料 | 557 B | 0.7s |
| `crypto_project_liveness` | DefiLlama 駭客事件清單 | 32.6 KB（33,346 B） | 0.1s |

### MCP／agent 生態目錄（2，新，Batch 3）
| 來源 | 內容 | 體積 | 耗時 |
|---|---|---|---|
| `agent_virtuals` | Virtuals Protocol agent 清單（精簡欄位：id/status/tokenAddress 等） | 866.5 KB（887,296 B） | 608.7s |
| `mcp_smithery` | Smithery MCP 註冊表 | 81.9 KB（83,890 B） | 6.8s |

### AI 算力與定價（4）
| 來源 | 內容 | 體積 | 耗時 |
|---|---|---|---|
| `vast_gpu` | vast.ai GPU 租賃報價 | 171.3 KB（175,408 B） | 1.4s |
| `openrouter_models` | 全模型清單與定價 | 67.7 KB（69,345 B） | 0.1s |
| `openrouter_providers` | 供應商清單（隱私政策／服務條款／機房地點） | 3.6 KB（3,652 B） | 0.0s |
| `hf_trending_models` | HuggingFace trending 模型 | 102.1 KB（104,548 B） | 0.3s |

### 合規與文件頁（4）
| 來源 | 內容 | 體積 | 耗時 |
|---|---|---|---|
| `ofac_sanctions_crypto` | OFAC SDN 制裁名單（含 Remarks 內嵌的加密地址） | 912.8 KB（934,696 B） | 13.6s |
| `project_tokenomics_docs` | 專案官方 tokenomics 文件（目前僅 Arbitrum Foundation） | 753 B | 0.1s |
| `airdrop_claim_pages` | 空投資格規則頁（目前僅 Starknet Provisions） | 930 B | 0.7s |
| `audit_registry_certik` | CertiK 首頁「Recently Audited」清單（約 8 筆，非完整資料庫） | 650 B | 0.1s |

### 新增 3 個來源的重要限制（各 adapter DESC 已誠實標註）

- **`agent_virtuals`**：官方回報總數 82,317 筆，本輪僅取得 36,000 筆（第 72/165 頁時觸發
  `TIME_BUDGET_SECS=600` 秒總時間預算，`truncated=true`）。截斷情況下不套用 50,000 筆下限
  （下限僅用於偵測「非截斷情況」下的異常縮水；截斷是預期中的正常降級行為）。
- **`mcp_smithery`**：官方回報總數約 11,103 筆，本輪僅取得 271 筆（覆蓋率約 2.4%）。
  端點硬性只能翻到第 5 頁（`page=6` 恆回 0 筆），且跨頁排序會漂移造成大量重疊，
  271 筆是去重後可拿到的實際上限，**非人為限量**，也非分頁邏輯寫錯。驗收下限依實測值
  校準為 `MIN_ITEMS=200`（271 × 0.8 ≈ 216.8，取整數 200）。
- **`x402_index_thirdparty`**：僅涵蓋約 1,044 個 URL（`/server/` 前綴 1,000 個），約為
  `x402_bazaar` 官方掛牌數（今日 14,410 筆）的 6.9%，屬輔助視角、非核心交叉驗證資料源。

### 已停抓
| 來源 | 說明 |
|---|---|
| `mcp_registry` | 2026-08-27 起停抓（單日快照即含多版本、官方支援 `updated_since`、佔每日 93% 時間）。已抓資料保留，其 adapter 檔已不在 `track-crypto/adapters/` 目錄下，**不計入本次 24 個之內** |
| `mcp_pulsemcp` | 2026-09 起停用（DESC／模組 docstring 已誠實標註，本輪未再驗證細節） |

### 未收錄（實測後排除）
| 目標 | 原因 |
|---|---|
| Circle 定價頁 | `circle.com/pricing` 已 301 導向行銷表單頁，**無任何費率數字** |
| Binance | robots.txt 全站 `Disallow: /` |
| Jupiter／EigenLayer／Hyperliquid 相關頁 | 網域 DNS 已失效或 404 |

端點全文、欄位與已知限制 → [docs/sources.md](../docs/sources.md)

## 需要先知道的兩件事

1. **`vast_gpu` 的筆數受認證狀態影響**：未帶 API 金鑰時端點只回 64 筆。
   跨日比較前請先看快照中的 `_authenticated` 欄位。
2. **`cex_symbols` 有生存者偏誤**：bybit、okx、mexc 只回傳存活標的，下架後直接消失。
   只有 HTX 保留 `offline` 狀態。

## `data/cex_events/`

`scripts/cex_events.py` 逐日比對快照，把上架／下架事件累積寫入 `events.jsonl`（只追加）：

```json
{"date":"2026-08-27","exchange":"bybit","symbol":"XXXUSDT","event":"DELISTED","from":"Trading","to":null}
```

`event` 為 `LISTED` / `DELISTED` / `STATUS_CHANGED`。本檔只記錄事實，不含任何解讀、預測或建議。

## 架構

一個來源一支 adapter，放在 `adapters/<key>.py`，至少提供：

```python
KEY, DESC, SOURCE_HOME, ROBOTS_VERIFIED
PARSER_VERSION = 1                 # 解析邏輯版本號，變動時遞增，供 manifest 追蹤
def collect(fetch) -> dict/list:
    ...                            # fetch(url, headers=None, timeout=45) -> str（原始回應內文，未解析）
```

> **注意（本輪查核修正）**：軌一（track-crypto）的 adapter 介面**沒有** `clean` 參數，
> 也**不支援** `deadline` 參數；`collect(fetch, clean, deadline=None)` 是軌二（track-gov）
> 的介面（見 [track-gov/README.md](../track-gov/README.md)），兩軌介面不同，不可混用。
> 軌一目前唯一的逾時／截斷機制是 `agent_virtuals` adapter 自行在函式內實作的
> `TIME_BUDGET_SECS=600` 秒總時間預算（`truncated` 欄位寫入回傳的 `data` 內層，
> 不在 `_meta` 裡；其餘 23 個 adapter 沒有這個機制）。

快照本體格式固定為 `{"_meta": {"source","fetched_at","license"}, "data": <collect() 回傳值>}`，
`_meta` 只有這 3 個鍵（軌二的 `channels`／`desc`／`source_home`／`robots_verified`／`parser_version`
等擴充欄位一律不進快照本體，只進 manifest，避免破壞既有比對邏輯）。

`scripts/snap_crypto.py` 自動載入 `adapters/*.py`，統一計算 manifest（`bytes`／`secs`／`parser_version`）、
原子寫入。單一來源失敗時等待 120 秒重試一次（`MAX_ATTEMPTS=2`），manifest 記錄 `attempts` 與
`first_error`；本輪已執行超過 90 分鐘時跳過剩餘重試，避免拖垮 11:30 的 push 排程。

單獨執行一個來源：`python3 scripts/snap_crypto.py <key>`

## 目錄

```
data/<source>/YYYY-MM-DD.json.gz    {"_meta":{...},"data":{...}}
data/_manifest/YYYY-MM-DD.json      當日各來源成敗、大小、耗時、parser_version
data/cex_events/events.jsonl        上／下架事件流
adapters/<key>.py                   各來源抓取規則（一個來源一支）
scripts/snap_crypto.py              主程式，自動載入 adapters/
logs/cron.log                       執行日誌（不入 GitHub）
```

`data/**/*.json.gz` 目前不入 GitHub（見專案根目錄 `.gitignore`），原始資料保存於 VPS。

檔案結構與讀取範例 → [docs/data-format.md](../docs/data-format.md)
抓取原則與 robots.txt → [docs/methodology.md](../docs/methodology.md)

## 排程

每日台北時間 **08:00** 觸發（VPS `crontab -l`，2026-08-31 查核）。

## 授權

資料 **CC BY 4.0**（見 [LICENSE](../LICENSE)）／程式碼 **MIT**（見 [LICENSE-CODE](../LICENSE-CODE)）。

## 免責

本存檔僅記錄公開端點在特定時間點的回應內容，不對資料正確性作任何保證，
不構成任何投資建議或分析意見。使用者應自行驗證。
