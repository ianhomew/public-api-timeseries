# 每日資料蒐集報告

產生時間：2026-09-07 03:31:48 UTC（台北時間 2026-09-07 11:31:48 UTC+8）

## 一句話結論

有 1 項異常（與 ALERT.md 採同一套 healthcheck.py 判定邏輯，逐項一致），詳見下方各節。

（本輪自動探索到 42 個來源：軌一 24 個、軌二 18 個；新增來源不需再修改本程式。）

## 來源對照表

| 軌 | 來源 | 中文名 | 今日筆數 | 昨日筆數 | 增減 | 今日體積 | 體積增減% | 耗時 | 嘗試 | 截斷 | 解析失敗 | 備註 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 軌一 | agent_virtuals | Virtuals Protocol agent 清單 | — | — | — | 1,856,439 B | +0.1% | 1826.7s | 1 | 否 | — |  |
| 軌一 | airdrop_claim_pages | 空投資格規則頁 | — | — | — | 927 B | +0.0% | 0.3s | 1 | 否 | — |  |
| 軌一 | audit_registry_certik | CertiK Skynet 首頁「Recently Audited」最新審計清單 | — | — | — | 693 B | +0.0% | 0.2s | 1 | 否 | — |  |
| 軌一 | cex_announcements | 交易所公告 | — | — | — | 6,982 B | +0.6% | 15.8s | 1 | 否 | — |  |
| 軌一 | cex_currency_status | 交易所幣種層級狀態旗標 | — | — | — | 293,643 B | +0.0% | 5.3s | 1 | 否 | — |  |
| 軌一 | cex_earn_apr | CEX 理財年化率 | — | — | — | 9,298 B | +0.4% | 2.0s | 1 | 否 | — |  |
| 軌一 | cex_symbols | 7 家 CEX 交易對／幣種狀態 | 10,687 | 10,682 | +5 | 404,338 B | +0.0% | 14.1s | 1 | 否 | — |  |
| 軌一 | cex_symbols_ext | 新增 3 家交易所 | — | — | — | 63,358 B | +0.0% | 5.4s | 1 | 否 | — |  |
| 軌一 | cex_withdrawal_limits | KuCoin 幣種提幣費與最低提幣額 | — | — | — | 142,187 B | -0.0% | 0.7s | 1 | 否 | — |  |
| 軌一 | crypto_project_liveness | DefiLlama 駭客事件清單 | — | — | — | 33,648 B | +0.0% | 0.1s | 1 | 否 | — |  |
| 軌一 | dao_proposal_snapshot | Snapshot DAO 提案中繼資料快照 | — | — | — | 396,762 B | +0.0% | 9.3s | 1 | 否 | — |  |
| 軌一 | defi_yield_rates | LST/LRT 質押與 DeFi 借貸利率 | — | — | — | 1,494 B | +0.3% | 3.4s | 1 | 否 | — |  |
| 軌一 | eth_validator_queue | 以太坊驗證者進出隊列各狀態筆數 | — | — | — | 215 B | +0.0% | 49.4s | 1 | 否 | — |  |
| 軌一 | hf_trending_models | HuggingFace trending 模型清單 | — | — | — | 107,931 B | +1.0% | 0.4s | 1 | 否 | — |  |
| 軌一 | mcp_smithery | MCP Smithery 註冊表 | — | — | — | 83,357 B | -0.0% | 7.0s | 1 | 是 | — | 今日截斷（truncated=true，未跑滿目標筆數） |
| 軌一 | ofac_sanctions_crypto | OFAC SDN 制裁名單 | — | — | — | 935,231 B | +0.0% | 12.6s | 1 | 否 | — |  |
| 軌一 | openrouter_models | OpenRouter 全模型清單與定價 | — | — | — | 71,242 B | -0.4% | 0.2s | 1 | 否 | — |  |
| 軌一 | openrouter_providers | OpenRouter 供應商清單 | — | — | — | 3,688 B | +0.1% | 0.0s | 1 | 否 | — |  |
| 軌一 | oracle_feed_directory | Chainlink／Pyth 價格餵送目錄 | — | — | — | 167,278 B | -0.0% | 1.4s | 1 | 否 | — |  |
| 軌一 | payment_pricing_pages | Circle 官方開發者文件 Gateway 產品費率頁 | — | — | — | 808 B | +0.0% | 0.1s | 1 | 否 | — |  |
| 軌一 | payment_protocol_repos | 支付協議規格版本 GitHub Repo 中繼資料 | — | — | — | 556 B | +0.2% | 0.7s | 1 | 否 | — |  |
| 軌一 | project_tokenomics_docs | 專案官方 tokenomics 文件頁 | — | — | — | 751 B | -0.1% | 0.1s | 1 | 否 | — |  |
| 軌一 | vast_gpu | Vast.ai GPU 租賃市場報價 | 512 | 512 | +0 | 174,618 B | -0.4% | 2.0s | 1 | 否 | — |  |
| 軌一 | x402_bazaar | x402 Bazaar 全量掛牌 | 15,581 | 16,592 | -1011 | 6,872,534 B | -0.2% | 57.5s | 1 | 否 | — |  |
| 軌二 | cbc_press | 中央銀行新聞稿 | 99 | 99 | +0 | 46,799 B | +0.0% | 258.7s | 1 | 否 | 否 |  |
| 軌二 | ey_press | 行政院本院新聞 | 99 | 99 | +0 | 174,552 B | +0.0% | 268.1s | 1 | 否 | 否 |  |
| 軌二 | fda_clarify | 食藥署 食藥闢謠專區 | 50 | 50 | +0 | 21,087 B | +0.0% | 189.0s | 1 | 否 | 否 |  |
| 軌二 | fsc_clarification | 金管會即時新聞澄清 | 50 | 50 | +0 | 38,428 B | +0.0% | 100.0s | 1 | 否 | 否 |  |
| 軌二 | fsc_lawnotice | 金管會法規草案預告 | 100 | 100 | +0 | 25,287 B | +0.0% | 181.3s | 1 | 否 | 否 |  |
| 軌二 | fsc_penalty | 金管會裁罰案件 | 100 | 100 | +0 | 140,030 B | +0.0% | 183.8s | 1 | 否 | 否 |  |
| 軌二 | ftc_decision | 公平交易委員會 本會行政決定 | 100 | 100 | +0 | 17,345 B | +0.0% | 53.1s | 1 | 否 | 否 |  |
| 軌二 | moda_press | 數位發展部新聞發布 | 100 | 100 | +0 | 98,057 B | +0.0% | 107.4s | 1 | 否 | 否 |  |
| 軌二 | moe_clarify | 教育部即時新聞澄清 | 81 | 81 | +0 | 73,832 B | +0.0% | 283.9s | 1 | 否 | 否 |  |
| 軌二 | moe_press | 教育部即時新聞 | 100 | 100 | +0 | 122,727 B | +0.0% | 335.0s | 1 | 否 | 否 |  |
| 軌二 | moea_press | 經濟部本部新聞 | 100 | 100 | +0 | 125,041 B | +0.0% | 218.6s | 1 | 否 | 否 |  |
| 軌二 | mof_press | 財政部本部新聞 | 100 | 100 | +0 | 86,169 B | -0.1% | 260.8s | 1 | 否 | 否 |  |
| 軌二 | mohw_press | 衛生福利部焦點新聞 | 100 | 100 | +0 | 125,873 B | -0.0% | 212.8s | 1 | 否 | 否 |  |
| 軌二 | moi_press | 內政部新聞稿 | 100 | 100 | +0 | 98,983 B | +0.0% | 321.4s | 1 | 否 | 否 |  |
| 軌二 | moj_press | 法務部新聞發布 | 50 | 50 | +0 | 56,400 B | +0.0% | 115.4s | 1 | 否 | 否 |  |
| 軌二 | mol_press | 勞動部新聞稿 | 100 | 100 | +0 | 130,160 B | +0.0% | 242.8s | 1 | 否 | 否 |  |
| 軌二 | pres_news | 總統府新聞 | 100 | 100 | +0 | 179,505 B | -0.3% | 186.3s | 1 | 否 | 否 |  |
| 軌二 | tpe_clarify | 台北市政府即時新聞澄清 | 50 | 50 | +0 | 35,472 B | +0.0% | 107.6s | 1 | 否 | 否 |  |

註：本表「截斷」「解析失敗」欄位標記的來源屬於資料品質提示；官方異常總數以下方〈異常摘要〉為準，避免同一件事重複計數。

## 變動偵測

最近一輪變動偵測：

| 來源 | 區間 | 改寫 | 下架 | 新增 | 滾動移出 |
|---|---|---|---|---|---|
| cbc_press | 2026-09-06→2026-09-07 | 0 | 0 | 0 | 0 |
| ey_press | 2026-09-06→2026-09-07 | 0 | 0 | 0 | 0 |
| fda_clarify | 2026-09-06→2026-09-07 | 0 | 0 | 0 | 0 |
| fsc_clarification | 2026-09-06→2026-09-07 | 0 | 0 | 0 | 0 |
| fsc_lawnotice | 2026-09-06→2026-09-07 | 0 | 0 | 0 | 0 |
| fsc_penalty | 2026-09-06→2026-09-07 | 0 | 0 | 0 | 0 |
| ftc_decision | 2026-09-06→2026-09-07 | 0 | 0 | 0 | 0 |
| moda_press | 2026-09-06→2026-09-07 | 0 | 0 | 0 | 0 |
| moe_clarify | 2026-09-06→2026-09-07 | 0 | 0 | 0 | 0 |
| moe_press | 2026-09-06→2026-09-07 | 0 | 0 | 0 | 0 |
| moea_press | 2026-09-06→2026-09-07 | 0 | 0 | 0 | 0 |
| mof_press | 2026-09-06→2026-09-07 | 0 | 0 | 2 | 2 |
| mohw_press | 2026-09-06→2026-09-07 | 0 | 0 | 0 | 0 |
| moi_press | 2026-09-06→2026-09-07 | 0 | 0 | 0 | 0 |
| moj_press | 2026-09-06→2026-09-07 | 0 | 0 | 0 | 0 |
| mol_press | 2026-09-06→2026-09-07 | 0 | 0 | 0 | 0 |
| pres_news | 2026-09-06→2026-09-07 | 0 | 0 | 3 | 3 |
| tpe_clarify | 2026-09-06→2026-09-07 | 0 | 0 | 0 | 0 |
| **總計** |  | 0 | 0 | 5 | 5 |

本輪彙總：changed=0，removed=0。

`changes/` 目錄下有 14 個來源目錄記錄改寫內容：
- agent_virtuals
- cex_currency_status
- cex_earn_apr
- cex_symbols_ext
- cex_withdrawal_limits
- crypto_project_liveness
- moea_press
- mof_press
- mohw_press
- ofac_sanctions_crypto
- openrouter_models
- openrouter_providers
- oracle_feed_directory
- x402_bazaar

`CHANGES.md` 存在，內容請參閱該檔案。

## 交易所事件流

今日（2026-09-07）共 25 筆事件，依交易所與事件類型分組：

- gateio / LISTED：1 筆
  - 哈基米_USDT：None → tradable
- mexc / DELISTED：10 筆
  - ALONUSD1：1 → None
  - ALONUSDT：1 → None
  - MARSCOIN1USD1：1 → None
  - MARSCOIN1USDT：1 → None
  - PACKUSD1：1 → None
- mexc / LISTED：12 筆
  - BLOBUSDT：None → 2
  - PAIRUSD1：None → 1
  - PAIRUSDT：None → 1
  - ROBINUSD1：None → 1
  - ROBINUSDT：None → 1
- okx / LISTED：2 筆
  - XSNDK-USDC：None → preopen
  - XSPY-USDC：None → preopen

## 排程執行狀況

**軌一（track-crypto）**（自動探索到 24 個來源）：
- 今日已執行（依 manifest `fetched_at`=2026-09-07 判斷），manifest 記錄 24 個來源。
- manifest 由 1 次執行合併寫入（`runs` 陣列）。
- cron.log 最近一次摘要（僅供耗時／歷史參考）：24/24 成功
- 近 7 次執行成功率（cron.log 歷史）：24/24、24/24、24/24、24/24、24/24、24/24、24/24
**軌二（track-gov）**（自動探索到 18 個來源）：
- 今日已執行（依 manifest `fetched_at`=2026-09-07 判斷），manifest 記錄 18 個來源。
- manifest 由 1 次執行合併寫入（`runs` 陣列）。
- cron.log 最近一次摘要（僅供耗時／歷史參考）：18/18 成功
- 近 7 次執行成功率（cron.log 歷史）：18/18、18/18、18/18、18/18、18/18、18/18、18/18

## 時間戳

- SHA256SUMS-2026-08-27.txt：有 對應 `.ots`
- SHA256SUMS-2026-08-28.txt：有 對應 `.ots`
- SHA256SUMS-2026-08-29.txt：有 對應 `.ots`
- SHA256SUMS-2026-08-30.txt：有 對應 `.ots`
- SHA256SUMS-2026-08-31.txt：有 對應 `.ots`
- SHA256SUMS-2026-09-01.txt：有 對應 `.ots`
- SHA256SUMS-2026-09-02.txt：有 對應 `.ots`
- SHA256SUMS-2026-09-03.txt：有 對應 `.ots`
- SHA256SUMS-2026-09-04.txt：有 對應 `.ots`
- SHA256SUMS-2026-09-05.txt：有 對應 `.ots`
- SHA256SUMS-2026-09-06.txt：有 對應 `.ots`
- SHA256SUMS-2026-09-07.txt：有 對應 `.ots`

## 累積統計

- 資料起訖日期：2026-08-26 ～ 2026-09-07（共 13 天，實際有紀錄 13 天）
- track-crypto 累積體積：138,838,392 B（13 天有 manifest）
  - 依現速率推算：1 年約 3.6 GB，5 年約 18.2 GB
- track-gov 累積體積：18,014,203 B（12 天有 manifest）
  - 依現速率推算：1 年約 522.5 MB，5 年約 2.6 GB

## 異常摘要

以下 1 項為官方異常清單，判定邏輯直接呼叫 `healthcheck.py` 的 `check_timestamps`／`check_manifest`／`check_truncation_streak`／`check_source`（唯讀，本檔不寫入 ALERT.md），與當日 ALERT.md 逐項一致：

| 來源 | 問題（與 healthcheck.py / ALERT.md 同一套判定） |
|---|---|
| `track-crypto/mcp_smithery` | 連續 4 天截斷（truncated=true，達門檻 2 天）：2026-09-04 實際 273 筆／耗時 6.9s；2026-09-05 實際 272 筆／耗時 6.9s；2026-09-06 實際 272 筆／耗時 6.8s；2026-09-07 實際 272 筆／耗時 7.0s；目標（近期未截斷）約 未知（近期無未截斷紀錄可比對） |

以下為 ALERT.md 等檔案的原始內容（供交叉核對）：

**ALERT.md**（存在）：
> # 🔴 每日自我檢查發現異常
> 
> 檢查時間（UTC）：2026-09-07T03:31:47+00:00
> 檢查時間（台北）：2026-09-07T11:31:47+08:00
> 檢查基準日（UTC）：2026-09-07
> 
> | 來源 | 問題 |
> |---|---|
> | `track-crypto/mcp_smithery` | 連續 4 天截斷（truncated=true，達門檻 2 天）：2026-09-04 實際 273 筆／耗時 6.9s；2026-09-05 實際 272 筆／耗時 6.9s；2026-09-06 實際 272 筆／耗時 6.8s；2026-09-07 實際 272 筆／耗時 7.0s；目標（近期未截斷）約 未知（近期無未截斷紀錄可比對） |
> 

- ALERT-DETECT.md：不存在
- ALERT-HEALTH.md：不存在
**ALERT-DELIST.md**（存在）：
> # 🔴 track-crypto x402_bazaar 自清單消失規模異常警報（熔斷）
> 
> 本檔案由 `track-crypto/scripts/detect_delistings.py` 獨佔寫入，不與任何其他程式共用
> （另見 `ALERT.md` 是 `scripts/healthcheck.py` 的獨立輸出，兩者互不相干）。
> 
> 本檔案記錄「removed 率超過熔斷門檻」這個事實（見下方各則區塊的數字），**不代表這些
> resource 已永久下架**：本程式對「自清單消失」與「永久下架」不畫等號（詳見
> `track-crypto/scripts/detect_delistings.py` 檔頭「事件型別語意定義」小節與本機
> `docs/detect-phase1-report.md` §5、§9——同一資料源實測約 5%～17%（依觀察窗長短）的
> 「自清單消失」案例會在數天內重新出現）。熔斷只代表移除比例超出日常區間（1.8%~3.7%），

- ALERT-BACKUP.md：不存在
- ALERT-CEXGATE.md：不存在
- ALERT-DELISTGATE.md：不存在

## 暫不判定／基準重建中（資訊，非異常，不計入異常數，不寫入 ALERT.md）

以下來源的 `parser_version` 在體積比較視窗（最近 7 天）內發生變更，`healthcheck.py` 的 `check_source()`（與 `ALERT.md` 同一套判定函式，見上方〈異常摘要〉呼叫的 `build_health_issues()`）依既有原則（比照 `detect_changes.py`）暫時跳過本次體積判定，等視窗內全部天數都變成新版本後自動恢復判定，不需人工介入、不留白名單。**這是資訊性狀態，不是異常**：不計入本報告與 `ALERT.md` 的異常總數，也不會寫入 `ALERT.md`。下表直接解析自 `check_source()` 本次執行時印出的 NOTICE 訊息，與〈異常摘要〉同一次呼叫、非本檔另行計算。

| 來源 | parser_version 變化 | 進度（第幾天／共幾天） |
|---|---|---|
| `track-gov/pres_news` | 1 → 2 | 第 5／7 天 |


---
本報告僅陳述資料蒐集流程的技術事實（筆數、體積、耗時、排程狀態），不構成任何投資建議或市場判斷。
