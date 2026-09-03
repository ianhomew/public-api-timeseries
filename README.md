# public-api-timeseries

保存那些「官方不留歷史」的公開數字。

每天對一組公開端點各取一次快照，永久保存。這個 repo 只存原始回應，**不做任何分析、解讀或建議**。

- 資料授權：**CC BY 4.0**（見 [LICENSE](LICENSE)）
- 程式碼授權：**MIT**（見 [LICENSE-CODE](LICENSE-CODE)）
- 資料起始日：**2026-08-26（UTC）**

## 為什麼

這些端點只回傳「現在」的值。今天變了，明天就查不到昨天的值。官方沒有歷史 API，
Internet Archive 的擷取頻率不足以還原時間序列，公開資料集平台上也沒有現成副本。

每個來源納入前都要通過三步驗證。判準與逐一查證結果見 [docs/why.md](docs/why.md)。

## 目前收錄（共 42 個來源，另有 1 個已停抓、歷史資料保留）

### `track-crypto/` — 加密貨幣與 AI 算力市場（24 個來源，另有 1 個已停抓）

既有文件（2026-08-28 UTC 實測）記載的 21 個來源仍有效，另有 **3 個新來源**
（`agent_virtuals`／`mcp_smithery`／`x402_index_thirdparty`）本輪盤點中發現已存在於 VPS，
但先前**未出現在任何既有文件**。本輪已補齊實測數字（唯讀，讀取既有 manifest／logs，未執行新抓取）：

| 來源 | 今日筆數（2026-08-31 UTC） | 今日體積 | 耗時 | 已累積天數 |
|---|---|---|---|---|
| `agent_virtuals` | 36,000 筆（官方回報總數 82,317 筆；600 秒時間預算截斷於第 72/165 頁，`truncated=true`，此為預期降級，非異常） | 887,296 B（約 867 KB） | 608.7s | 4 天（2026-08-28～08-31） |
| `mcp_smithery` | 271 筆（官方回報總數約 11,103 筆，覆蓋率約 2.4%；API 硬性只能翻到第 5 頁且跨頁排序漂移，271 筆為去重後可得上限，非人為限量） | 83,890 B（約 82 KB） | 6.8s | 4 天（2026-08-28～08-31） |
| `x402_index_thirdparty` | 1,044 個 URL（其中 `/server/` 前綴 1,000 個，約為軌一 `x402_bazaar` 官方掛牌數 14,410 筆的 6.9%） | 23,431 B（約 23 KB） | 1.5s | 4 天（2026-08-28～08-31） |

來源：VPS `track-crypto/data/_manifest/2026-08-31.json`、`track-crypto/logs/cron.log`、
`ls track-crypto/data/<source>/ | wc -l`（本輪唯讀查核，未修改任何 VPS 檔案）。

> **更新（2026-09-02）**：`x402_index_thirdparty` 已停抓，上表數字是停抓前最後一次完整實測
> 的歷史記錄，並非目前仍在每日更新的數字。停抓日期、理由、歷史資料保留細節見下方
> 來源狀態表下方的〈已停抓〉說明。

> **新增（2026-09-02）**：同日新增 `payment_pricing_pages`（Circle 官方開發者文件 Gateway 產品費率頁，
> `https://developers.circle.com/gateway/references/fees`）。首次快照（2026-09-02 UTC）812 B、
> 耗時 0.1 秒，`parser_version=1`；次日（2026-09-03 UTC）再次快照 809 B、耗時 0.3 秒，數字穩定。
> 端點、robots.txt 親驗結論、擷取欄位等細節見 [docs/sources.md](docs/sources.md)。

| 來源 | 內容 | 狀態 |
|---|---|---|
| `agent_virtuals` | Virtuals Protocol agent 清單 | **新來源，文件未記載** |
| `airdrop_claim_pages` | 空投資格規則頁（Starknet Provisions） | 每日抓取 |
| `audit_registry_certik` | CertiK Skynet 首頁「Recently Audited」清單 | 每日抓取 |
| `cex_announcements` | 交易所公告（標題／URL／時間／分類） | 每日抓取 |
| `cex_currency_status` | 交易所幣種層級狀態旗標 | 每日抓取 |
| `cex_earn_apr` | CEX 理財年化率 | 每日抓取 |
| `cex_symbols` | 7 家 CEX 交易對／幣種狀態 | 每日抓取 |
| `cex_symbols_ext` | 再 3 家 CEX 交易對清單（Kraken／Coinbase Exchange／Upbit） | 每日抓取 |
| `cex_withdrawal_limits` | KuCoin 幣種提幣費與最低提幣額 | 每日抓取 |
| `crypto_project_liveness` | DefiLlama 駭客事件清單 | 每日抓取 |
| `dao_proposal_snapshot` | Snapshot DAO 提案中繼資料 | 每日抓取 |
| `defi_yield_rates` | LST/LRT 質押與 DeFi 借貸利率 | 每日抓取 |
| `eth_validator_queue` | 以太坊驗證者進出隊列各狀態筆數 | 每日抓取 |
| `hf_trending_models` | HuggingFace trending 模型清單 | 每日抓取 |
| `mcp_smithery` | Smithery MCP 註冊表 | **新來源，文件未記載** |
| `ofac_sanctions_crypto` | OFAC SDN 制裁名單（美國財政部） | 每日抓取 |
| `openrouter_models` | OpenRouter 全模型清單與定價 | 每日抓取 |
| `openrouter_providers` | OpenRouter 供應商清單 | 每日抓取 |
| `oracle_feed_directory` | Chainlink／Pyth 價格餵送目錄 | 每日抓取 |
| `payment_pricing_pages` | Circle 官方開發者文件 Gateway 產品費率頁（跨鏈轉帳手續費率、各來源鏈 gas 費、轉發服務費） | 每日抓取 |
| `payment_protocol_repos` | 支付協議規格版本 GitHub Repo 中繼資料 | 每日抓取 |
| `project_tokenomics_docs` | 專案官方 tokenomics 文件頁 | 每日抓取 |
| `vast_gpu` | Vast.ai GPU 租賃市場報價 | 每日抓取 |
| `x402_bazaar` | x402 Bazaar 全量掛牌 | 每日抓取 |

> `mcp_registry` 已於 2026-08-27 起停止抓取（已抓資料保留），其 adapter 檔已不在
> `track-crypto/adapters/` 目錄下，故不計入本次 24 個之內（沿用既有文件記載，本輪未重新驗證）。
>
> `x402_index_thirdparty` 已於 **2026-09-02** 起停止抓取（已抓資料保留，2026-08-28～09-02
> 共 6 天快照不刪除、不覆寫），故同樣**不計入本次 24 個之內**。理由：與軌一權威來源
> `x402_bazaar` 高度重疊（同一 x402 生態系；2026-09-02 UTC 實測 `total=1044`／
> `server_count=1000`，同日 `x402_bazaar` `total=14929`，覆蓋率約 6.7%，且 `server_count`
> 連續多日卡在整數 1,000，判斷為第三方索引站 sitemap 本身的收錄上限）。adapter 原始碼已
> **搬移**（非刪除、內容未改）至 `track-crypto/retired_adapters/x402_index_thirdparty.py`，
> 不再被 `track-crypto/adapters/*.py` 自動探索機制掃到。端點細節見
> [docs/sources.md](docs/sources.md)。
>
> `mcp_pulsemcp` 為**人工封存**（`track-crypto/manual_adapters/`），不在每日排程內、
> 同樣不計入本次 24 個之內；`payment_pricing_pages` 已於 **2026-09-02** 新增並計入本次
> 24 個之內（見上方「新增（2026-09-02）」說明）。狀態定義見上方〈來源狀態：活躍／已停抓／人工封存〉。

舊 21 個來源 2026-08-31 UTC 實測合計每日壓縮後約 **8.38 MB**（8,786,335 B）；
加計新 3 個來源後，24 個來源合計約 **9.33 MB**（9,780,952 B，2026-08-31 UTC 實測，
來源：`track-crypto/data/_manifest/2026-08-31.json` 逐來源 `bytes` 加總）。
扣除已於 2026-09-02 停抓的 `x402_index_thirdparty`（23,431 B）後，**現行 23 個來源合計約
9.31 MB（9,757,521 B）**（同一份 2026-08-31 manifest 重新加總，非新一輪實測）。
再加計 2026-09-02 新增的 `payment_pricing_pages`（812 B，來源：`track-crypto/data/_manifest/2026-09-02.json`）後，**現行 24 個來源合計約 9.31 MB（9,758,333 B）**（2026-08-31 舊 23 個來源 manifest 加總 ＋ 2026-09-02 `payment_pricing_pages` 首次快照，非單一日期的完整新一輪實測；加總後 MB 概數與扣除前相同，因新增體積僅 812 B，四捨五入無感）。

### `track-gov/` — 台灣政府公告（可問責性存檔）（18 個來源）

每日抓各機關新聞稿／澄清稿全文，用來偵測**發布後被靜默改寫或下架**。

既有文件記載 12 個機關，本輪盤點確認 VPS 上實際已有 **18 個來源**，新增 6 個：
`fda_clarify`（食藥署）／`fsc_lawnotice`（金管會法規草案預告）／`fsc_penalty`（金管會裁罰案件）／
`ftc_decision`（公平會行政決定）／`pres_news`（總統府）／`tpe_clarify`（台北市政府）。
本輪已補齊新 6 個來源的實測數字（唯讀，讀取既有 manifest／logs，未執行新抓取）：

| 來源 | 今日筆數（2026-08-31 UTC） | 今日體積 | 耗時 | 已累積天數 |
|---|---|---|---|---|
| `fda_clarify` | 33 筆（`truncated=true`，600 秒時間預算截斷，目標 MAX_ITEMS=50 未達成） | 14,937 B（約 14.6 KB） | 610.3s | 4 天（2026-08-28～08-31） |
| `fsc_lawnotice` | 100 筆 | 25,281 B（約 24.7 KB） | 244.4s | 4 天（2026-08-28～08-31） |
| `fsc_penalty` | 100 筆 | 140,021 B（約 136.7 KB） | 300.7s | 4 天（2026-08-28～08-31） |
| `ftc_decision` | 100 筆 | 17,478 B（約 17.1 KB） | 187.3s | 4 天（2026-08-28～08-31） |
| `pres_news` | 15 筆（官方清單本身只有 15 筆可取，非截斷，DESC 已誠實標註） | 42,216 B（約 41.2 KB） | 39.2s | 4 天（2026-08-28～08-31） |
| `tpe_clarify` | 39 筆（`truncated=true`，600 秒時間預算截斷，目標 MAX_ITEMS=50 未達成） | 27,850 B（約 27.2 KB） | 603.6s | 4 天（2026-08-28～08-31） |

新 6 個來源 2026-08-31 UTC 實測合計每日壓縮後約 **262 KB**（267,783 B）。
來源：VPS `track-gov/data/_manifest/2026-08-31.json`、`track-gov/logs/cron.log`、
`ls track-gov/data/<source>/ | wc -l`（本輪唯讀查核，未修改任何 VPS 檔案）。

| 來源 | 機關與類別 | 狀態 |
|---|---|---|
| `cbc_press` | 中央銀行 新聞稿／新聞參考資料 | 每日抓取 |
| `ey_press` | 行政院 本院新聞 | 每日抓取 |
| `fda_clarify` | 衛生福利部食品藥物管理署（食藥署） 食藥闢謠專區 | **新來源，文件未記載** |
| `fsc_clarification` | 金融監督管理委員會（金管會） 即時新聞澄清 | 每日抓取 |
| `fsc_lawnotice` | 金融監督管理委員會（金管會） 法規草案預告 | **新來源，文件未記載** |
| `fsc_penalty` | 金融監督管理委員會（金管會） 裁罰案件 | **新來源，文件未記載** |
| `ftc_decision` | 公平交易委員會 本會行政決定（處分書及不處分決議書） | **新來源，文件未記載** |
| `moda_press` | 數位發展部 新聞發布 | 每日抓取 |
| `moe_clarify` | 教育部 即時新聞澄清 | 每日抓取 |
| `moe_press` | 教育部 即時新聞 | 每日抓取 |
| `moea_press` | 經濟部 本部新聞 | 每日抓取 |
| `mof_press` | 財政部 本部新聞 | 每日抓取 |
| `mohw_press` | 衛生福利部 焦點新聞 | 每日抓取 |
| `moi_press` | 內政部 新聞稿 | 每日抓取 |
| `moj_press` | 法務部 新聞發布 | 每日抓取 |
| `mol_press` | 勞動部 新聞稿 | 每日抓取 |
| `pres_news` | 總統府 本府新聞稿 | **新來源，文件未記載** |
| `tpe_clarify` | 台北市政府 即時新聞澄清 | **新來源，文件未記載** |

舊 12 個來源 2026-08-31 UTC 實測合計每日壓縮後約 **1.13 MB**（1,152,708 B，與 2026-08-27 舊實測
約 1.19 MB 為同一量級的正常日常波動）；加計新 6 個來源後，18 個來源合計約 **1.35 MB**
（1,420,491 B，2026-08-31 UTC 實測，來源：`track-gov/data/_manifest/2026-08-31.json` 逐來源 `bytes` 加總）。

**未收錄**：環境部（robots.txt 明文禁止新聞稿路徑 `/Page/`、`/News_Content.aspx`，
且全站 Cloudflare JS 挑戰）。理由與親驗紀錄見 [docs/sources.md](docs/sources.md)。

各來源的端點、分頁方式、已知限制見 [docs/sources.md](docs/sources.md)。

## 來源狀態：活躍／已停抓／人工封存

`track-crypto/` 的來源依所在目錄分三種狀態：

| 狀態 | 目錄 | 說明 | 計入每日排程／自動探索 |
|---|---|---|---|
| **活躍** | `adapters/` | 每日 cron 排程抓取，`snap_crypto.py`／`healthcheck.py`／`daily_report.py` 皆自動探索此目錄 | 是 |
| **已停抓** | `retired_adapters/` | 曾每日抓取，因故停止（如與既有來源高度重疊）；adapter 原始碼**搬移保留**（非刪除）供查證，已抓歷史資料保留、不刪除、不覆寫 | 否 |
| **人工封存** | `manual_adapters/` | 不在每日排程內，由人工不定期手動執行（如官方即將停用前搶救性加抓） | 否（人工觸發） |

目前：`retired_adapters/` 僅 `x402_index_thirdparty` 1 個（2026-09-02 起）；`manual_adapters/` 僅 `mcp_pulsemcp` 1 個。`track-gov/` 目前沒有 `retired_adapters/` 或 `manual_adapters/` 目錄，尚無此類案例。

完整定義、例外情況（`mcp_registry` 停抓時 `retired_adapters/` 慣例尚未建立，原始碼已直接刪除、僅歷史資料保留）與現況清單見 [docs/sources.md](docs/sources.md)。

## 資料長什麼樣

```
<track>/data/<source>/YYYY-MM-DD.json.gz    一天一檔，永不覆蓋
<track>/data/_manifest/YYYY-MM-DD.json      當日各來源成敗、大小、耗時
timestamps/SHA256SUMS-YYYY-MM-DD.txt(.ots)  OpenTimestamps 時間戳
```

檔名日期一律為 **UTC**。檔案結構、欄位、可執行的讀取範例見
[docs/data-format.md](docs/data-format.md)。

## 怎麼下載

```bash
git clone https://github.com/ianhomew/public-api-timeseries.git
```

注意：`track-crypto/data/**/*.json.gz` 目前**不入 GitHub**（體積考量，見 `.gitignore`）。
GitHub 上可取得的是 `_manifest`、`track-gov` 資料、時間戳與程式碼。
`track-crypto` 原始資料保存於 VPS，累積後再發布到資料集平台，時程見
[docs/operations.md](docs/operations.md)。

檢視已存檔的快照：

```bash
python3 scripts/explore.py                              # 總覽
python3 scripts/explore.py x402_bazaar 2026-08-27       # 預覽某日快照
python3 scripts/explore.py --diff fsc_clarification 2026-08-27 2026-08-28
```

## 抓取方式

每個來源每日僅抓取一輪，請求間隔 1 秒，附帶可識別的 User-Agent。
施工前逐一查驗 robots.txt，明確禁止者一律排除。
原子寫入、絕不覆蓋既有檔案。完整原則見 [docs/methodology.md](docs/methodology.md)。

## 變動偵測

`track-gov` 每筆含 `body_sha256`。比對相同 `id` 在**不同日期**的 hash，
即可發現內容被改寫或下架。有變動時才留下紀錄：

```
CHANGES.md                              累積索引
changes/<source>/YYYY-MM-DD.md           當日 unified diff
```

`track-crypto/data/cex_events/events.jsonl` 記錄交易所上架／下架事件流，
需累積兩份以上快照才會產生。細節見 [docs/operations.md](docs/operations.md)。

### 首次偵測到的改寫紀錄（2026-08-29）

2026-08-29，`mof_press`（財政部本部新聞）一篇既有公告的正文中，有一行聯絡資訊
被刪除，機關未另行公告此項變更。變動紀錄與逐字 diff 見
`changes/mof_press/2026-08-29.md`（已隨當日資料一併 push，commit `9122f81`）。
本存檔僅如實記載「該行被刪除、未公告」此一事實，不評論刪除原因或動機。

## 目前狀態

| 項目 | 值（2026-09-02 UTC 本輪唯讀查核，沿用既有 2026-08-31 實測值並補上當日新增/停抓變動） |
|---|---|
| 收錄來源總數 | **42**（track-crypto 24 ＋ track-gov 18；另有 1 個已停抓 `x402_index_thirdparty`，歷史資料保留、不計入 42） |
| 每日排程 | 08:00（track-crypto）／09:30（track-gov）／11:30（push）（**台北時間**，VPS `crontab -l` 查核） |
| 自我檢查 | `ALERT.md` 存在時代表偵測到異常 |
| 每日壓縮後合計體積 | 約 **10.66 MB**（11,178,824 B；track-crypto 9.31 MB〔24 個來源：2026-08-31 UTC 舊 23 個來源 manifest 加總 ＋ 2026-09-02 `payment_pricing_pages` 首次快照 812 B〕＋ track-gov 1.35 MB〔18 個來源，2026-08-31 UTC 實測，未受本輪異動影響〕；非單一日期的完整新一輪實測，方法見上方 track-crypto 段落） |
| 新 9 個來源實測數字 | 已補齊，見上方 track-crypto／track-gov 各表（2026-08-31 UTC，來源：manifest、cron.log、`ls` 累積天數） |
| 首次改寫偵測 | 2026-08-29，`mof_press` 1 起（見上方「首次偵測到的改寫紀錄」） |

## 這個專案不做什麼

- 不做網站、API 或儀表板
- 不做即時警報或推播
- 不做任何分析、解讀或評論

## 文件索引

| 文件 | 內容 |
|---|---|
| [docs/why.md](docs/why.md) | 收錄判準與三步驗證結果 |
| [docs/sources.md](docs/sources.md) | 每個來源的端點、欄位、已知限制 |
| [docs/data-format.md](docs/data-format.md) | 檔名規則、JSON 結構、讀取範例 |
| [docs/methodology.md](docs/methodology.md) | 抓取原則、robots.txt、原子寫入、時間戳 |
| [docs/revisions.md](docs/revisions.md) | 經複核被推翻或收斂的宣稱 |
| [docs/operations.md](docs/operations.md) | 排程、自我檢查、里程碑 |
| [track-crypto/README.md](track-crypto/README.md) | 軌一速覽 |
| [track-gov/README.md](track-gov/README.md) | 軌二速覽 |

## 免責

本存檔僅記錄公開端點在特定時間點的回應內容，不對資料正確性作任何保證，
不構成任何投資建議、法律意見或分析觀點。使用者應自行向原始來源查證。