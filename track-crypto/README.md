# track-crypto — 加密貨幣與 AI 算力市場每日快照

回上層：[專案總覽](../README.md)

這是原始資料存檔，**不含任何分析、觀點或投資建議**。

每天對 21 個公開端點各取一次快照，一天一檔 `YYYY-MM-DD.json.gz`（日期為 **UTC**），**永不覆蓋**。

## 收錄來源（21 個）

2026-08-28（UTC）實測值。每日壓縮後合計約 **8.8 MB**，總耗時約 **130 秒**。

### 交易所（6）
| 來源 | 內容 | 體積 | 耗時 |
|---|---|---|---|
| `cex_symbols` | 7 家交易對／幣種狀態（Bybit/OKX/Bitget/HTX/Gate/KuCoin/MEXC） | 408 KB | 15.5s |
| `cex_symbols_ext` | 再 3 家（Kraken/Coinbase Exchange/Upbit） | 63 KB | 5.6s |
| `cex_currency_status` | 幣種層級狀態旗標（Gate delisted／Coinbase status） | 292 KB | 6.2s |
| `cex_withdrawal_limits` | KuCoin 提幣費與最低提幣額（含各鏈參數） | 142 KB | 1.4s |
| `cex_announcements` | 交易所公告（只存標題／URL／時間／分類，不存全文） | 7 KB | 15.6s |
| `cex_earn_apr` | 理財年化率（Bybit 活期／OKX 借貸） | 9 KB | 2.5s |

### 鏈上與 DeFi（4）
| 來源 | 內容 | 體積 | 耗時 |
|---|---|---|---|
| `defi_yield_rates` | Lido／Rocket Pool／Ethena／Sky 質押與借貸利率 | 1.5 KB | 3.7s |
| `eth_validator_queue` | 驗證者進出隊列**各狀態筆數**（不存個別公鑰） | 218 B | 4.8s |
| `oracle_feed_directory` | Chainlink／Pyth 價格餵送目錄（供逐日比對集合差集） | 166 KB | 1.6s |
| `dao_proposal_snapshot` | Snapshot DAO 提案中繼資料（偵測提案被刪除，不存投票紀錄） | 395 KB | 8.3s |

### 支付與 agent 生態（3）
| 來源 | 內容 | 體積 | 耗時 |
|---|---|---|---|
| `x402_bazaar` | x402 全量掛牌（CDP discovery API） | 6.07 MB | 45.7s |
| `payment_protocol_repos` | x402／AP2／L402 規格版本 repo 中繼資料 | 551 B | 0.9s |
| `crypto_project_liveness` | DefiLlama 駭客事件清單 | 33 KB | 0.4s |

### AI 算力與定價（4）
| 來源 | 內容 | 體積 | 耗時 |
|---|---|---|---|
| `vast_gpu` | vast.ai GPU 租賃報價 | 173 KB | 2.1s |
| `openrouter_models` | 全模型清單與定價 | 69 KB | 0.4s |
| `openrouter_providers` | 供應商清單（隱私政策／服務條款／機房地點） | 3.6 KB | 0.1s |
| `hf_trending_models` | HuggingFace trending 模型 | 104 KB | 1.0s |

### 合規與文件頁（4）
| 來源 | 內容 | 體積 | 耗時 |
|---|---|---|---|
| `ofac_sanctions_crypto` | OFAC SDN 制裁名單（含 Remarks 內嵌的加密地址） | 935 KB | 13.3s |
| `project_tokenomics_docs` | 專案官方 tokenomics 文件（目前僅 Arbitrum Foundation） | 753 B | 0.1s |
| `airdrop_claim_pages` | 空投資格規則頁（目前僅 Starknet Provisions） | 931 B | 0.3s |
| `audit_registry_certik` | CertiK 首頁「Recently Audited」清單（約 8 筆，非完整資料庫） | 662 B | 0.1s |

### 已停抓
| 來源 | 說明 |
|---|---|
| `mcp_registry` | 2026-08-27 起停抓（單日快照即含多版本、官方支援 `updated_since`、佔每日 93% 時間）。已抓資料保留 |

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
adapters/<key>.py                   各來源抓取規則（一個來源一支）
scripts/snap_crypto.py              主程式，自動載入 adapters/
logs/cron.log                       執行日誌（不入 GitHub）
```

`data/**/*.json.gz` 目前不入 GitHub（見專案根目錄 `.gitignore`），原始資料保存於 VPS。

檔案結構與讀取範例 → [docs/data-format.md](../docs/data-format.md)
抓取原則與 robots.txt → [docs/methodology.md](../docs/methodology.md)

## 授權

資料 **CC BY 4.0**（見 [LICENSE](../LICENSE)）／程式碼 **MIT**（見 [LICENSE-CODE](../LICENSE-CODE)）。

## 免責

本存檔僅記錄公開端點在特定時間點的回應內容，不對資料正確性作任何保證，
不構成任何投資建議或分析意見。使用者應自行驗證。
