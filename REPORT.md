# 每日資料蒐集報告

產生時間：2026-09-05 03:32:21 UTC（台北時間 2026-09-05 11:32:21 UTC+8）

## 一句話結論

有 1 項異常（與 ALERT.md 採同一套 healthcheck.py 判定邏輯，逐項一致），詳見下方各節。

（本輪自動探索到 42 個來源：軌一 24 個、軌二 18 個；新增來源不需再修改本程式。）

## 來源對照表

| 軌 | 來源 | 中文名 | 今日筆數 | 昨日筆數 | 增減 | 今日體積 | 體積增減% | 耗時 | 嘗試 | 截斷 | 解析失敗 | 備註 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 軌一 | agent_virtuals | Virtuals Protocol agent 清單 | — | — | — | 1,851,682 B | +0.1% | 2076.5s | 1 | 否 | — |  |
| 軌一 | airdrop_claim_pages | 空投資格規則頁 | — | — | — | 928 B | +0.1% | 0.2s | 1 | 否 | — |  |
| 軌一 | audit_registry_certik | CertiK Skynet 首頁「Recently Audited」最新審計清單 | — | — | — | 690 B | +0.0% | 0.1s | 1 | 否 | — |  |
| 軌一 | cex_announcements | 交易所公告 | — | — | — | 6,943 B | -0.5% | 15.8s | 1 | 否 | — |  |
| 軌一 | cex_currency_status | 交易所幣種層級狀態旗標 | — | — | — | 293,331 B | +0.0% | 4.1s | 1 | 否 | — |  |
| 軌一 | cex_earn_apr | CEX 理財年化率 | — | — | — | 9,290 B | +0.7% | 2.2s | 1 | 否 | — |  |
| 軌一 | cex_symbols | 7 家 CEX 交易對／幣種狀態 | 10,689 | 10,697 | -8 | 404,108 B | -0.3% | 12.8s | 1 | 否 | — |  |
| 軌一 | cex_symbols_ext | 新增 3 家交易所 | — | — | — | 63,371 B | -0.1% | 5.1s | 1 | 否 | — |  |
| 軌一 | cex_withdrawal_limits | KuCoin 幣種提幣費與最低提幣額 | — | — | — | 142,117 B | +0.0% | 0.7s | 1 | 否 | — |  |
| 軌一 | crypto_project_liveness | DefiLlama 駭客事件清單 | — | — | — | 33,590 B | +0.1% | 0.1s | 1 | 否 | — |  |
| 軌一 | dao_proposal_snapshot | Snapshot DAO 提案中繼資料快照 | — | — | — | 396,722 B | +0.1% | 9.2s | 1 | 否 | — |  |
| 軌一 | defi_yield_rates | LST/LRT 質押與 DeFi 借貸利率 | — | — | — | 1,491 B | -0.1% | 3.4s | 1 | 否 | — |  |
| 軌一 | eth_validator_queue | 以太坊驗證者進出隊列各狀態筆數 | — | — | — | 215 B | +0.5% | 4.3s | 1 | 否 | — |  |
| 軌一 | hf_trending_models | HuggingFace trending 模型清單 | — | — | — | 106,580 B | +0.5% | 0.3s | 1 | 否 | — |  |
| 軌一 | mcp_smithery | MCP Smithery 註冊表 | — | — | — | 83,236 B | -0.8% | 6.9s | 1 | 是 | — | 今日截斷（truncated=true，未跑滿目標筆數） |
| 軌一 | ofac_sanctions_crypto | OFAC SDN 制裁名單 | — | — | — | 935,231 B | +0.0% | 14.0s | 1 | 否 | — |  |
| 軌一 | openrouter_models | OpenRouter 全模型清單與定價 | — | — | — | 71,525 B | +0.1% | 0.1s | 1 | 否 | — |  |
| 軌一 | openrouter_providers | OpenRouter 供應商清單 | — | — | — | 3,683 B | -0.0% | 0.0s | 1 | 否 | — |  |
| 軌一 | oracle_feed_directory | Chainlink／Pyth 價格餵送目錄 | — | — | — | 167,280 B | -0.5% | 1.3s | 1 | 否 | — |  |
| 軌一 | payment_pricing_pages | Circle 官方開發者文件 Gateway 產品費率頁 | — | — | — | 809 B | +0.1% | 0.2s | 1 | 否 | — |  |
| 軌一 | payment_protocol_repos | 支付協議規格版本 GitHub Repo 中繼資料 | — | — | — | 555 B | +0.9% | 1.0s | 1 | 否 | — |  |
| 軌一 | project_tokenomics_docs | 專案官方 tokenomics 文件頁 | — | — | — | 748 B | -0.5% | 0.1s | 1 | 否 | — |  |
| 軌一 | vast_gpu | Vast.ai GPU 租賃市場報價 | 512 | 512 | +0 | 173,627 B | -1.7% | 2.8s | 1 | 否 | — |  |
| 軌一 | x402_bazaar | x402 Bazaar 全量掛牌 | 16,172 | 16,200 | -28 | 6,822,992 B | +0.5% | 48.5s | 1 | 否 | — |  |
| 軌二 | cbc_press | 中央銀行新聞稿 | 99 | 99 | +0 | 46,799 B | -0.4% | 190.3s | 1 | 否 | 否 |  |
| 軌二 | ey_press | 行政院本院新聞 | 99 | 100 | -1 | 175,159 B | +0.1% | 250.7s | 1 | 否 | 否 |  |
| 軌二 | fda_clarify | 食藥署 食藥闢謠專區 | 50 | 50 | +0 | 21,087 B | +0.0% | 149.9s | 1 | 否 | 否 |  |
| 軌二 | fsc_clarification | 金管會即時新聞澄清 | 50 | 50 | +0 | 38,428 B | +0.0% | 98.7s | 1 | 否 | 否 |  |
| 軌二 | fsc_lawnotice | 金管會法規草案預告 | 100 | 100 | +0 | 25,288 B | +0.0% | 182.1s | 1 | 否 | 否 |  |
| 軌二 | fsc_penalty | 金管會裁罰案件 | 100 | 100 | +0 | 140,029 B | -0.0% | 184.8s | 1 | 否 | 否 |  |
| 軌二 | ftc_decision | 公平交易委員會 本會行政決定 | 100 | 100 | +0 | 17,344 B | +0.0% | 116.5s | 1 | 否 | 否 |  |
| 軌二 | moda_press | 數位發展部新聞發布 | 100 | 100 | +0 | 98,057 B | +0.0% | 106.1s | 1 | 否 | 否 |  |
| 軌二 | moe_clarify | 教育部即時新聞澄清 | 81 | 80 | +1 | 73,832 B | +1.1% | 275.5s | 1 | 否 | 否 |  |
| 軌二 | moe_press | 教育部即時新聞 | 100 | 100 | +0 | 123,206 B | -0.5% | 340.2s | 1 | 否 | 否 |  |
| 軌二 | moea_press | 經濟部本部新聞 | 100 | 100 | +0 | 125,300 B | +1.0% | 219.6s | 1 | 否 | 否 |  |
| 軌二 | mof_press | 財政部本部新聞 | 100 | 100 | +0 | 86,271 B | +0.2% | 329.0s | 1 | 否 | 否 |  |
| 軌二 | mohw_press | 衛生福利部焦點新聞 | 100 | 100 | +0 | 126,730 B | +1.0% | 200.2s | 1 | 否 | 否 |  |
| 軌二 | moi_press | 內政部新聞稿 | 100 | 100 | +0 | 97,945 B | -3.2% | 225.8s | 1 | 否 | 否 |  |
| 軌二 | moj_press | 法務部新聞發布 | 50 | 50 | +0 | 56,400 B | +0.0% | 104.6s | 1 | 否 | 否 |  |
| 軌二 | mol_press | 勞動部新聞稿 | 100 | 100 | +0 | 130,160 B | -1.1% | 301.0s | 1 | 否 | 否 |  |
| 軌二 | pres_news | 總統府新聞 | 100 | 100 | +0 | 180,903 B | +0.3% | 187.4s | 1 | 否 | 否 |  |
| 軌二 | tpe_clarify | 台北市政府即時新聞澄清 | 50 | 50 | +0 | 35,472 B | +0.0% | 108.5s | 1 | 否 | 否 |  |

註：本表「截斷」「解析失敗」欄位標記的來源屬於資料品質提示；官方異常總數以下方〈異常摘要〉為準，避免同一件事重複計數。

## 變動偵測

最近一輪變動偵測：

| 來源 | 區間 | 改寫 | 下架 | 新增 | 滾動移出 |
|---|---|---|---|---|---|
| cbc_press | 2026-09-04→2026-09-05 | 0 | 0 | 1 | 1 |
| ey_press | 2026-09-04→2026-09-05 | 0 | 0 | 2 | 3 |
| fda_clarify | 2026-09-04→2026-09-05 | 0 | 0 | 0 | 0 |
| fsc_clarification | 2026-09-04→2026-09-05 | 0 | 0 | 0 | 0 |
| fsc_lawnotice | 2026-09-04→2026-09-05 | 0 | 0 | 0 | 0 |
| fsc_penalty | 2026-09-04→2026-09-05 | 0 | 0 | 0 | 0 |
| ftc_decision | 2026-09-04→2026-09-05 | 0 | 0 | 0 | 0 |
| moda_press | 2026-09-04→2026-09-05 | 0 | 0 | 0 | 0 |
| moe_clarify | 2026-09-04→2026-09-05 | 0 | 0 | 1 | 0 |
| moe_press | 2026-09-04→2026-09-05 | 0 | 0 | 6 | 6 |
| moea_press | 2026-09-04→2026-09-05 | 0 | 0 | 5 | 5 |
| mof_press | 2026-09-04→2026-09-05 | 0 | 0 | 8 | 8 |
| mohw_press | 2026-09-04→2026-09-05 | 0 | 0 | 1 | 1 |
| moi_press | 2026-09-04→2026-09-05 | 0 | 0 | 5 | 5 |
| moj_press | 2026-09-04→2026-09-05 | 0 | 0 | 0 | 0 |
| mol_press | 2026-09-04→2026-09-05 | 0 | 0 | 2 | 2 |
| pres_news | 2026-09-04→2026-09-05 | 0 | 0 | 2 | 2 |
| tpe_clarify | 2026-09-04→2026-09-05 | 0 | 0 | 0 | 0 |
| **總計** |  | 0 | 0 | 33 | 33 |

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

今日（2026-09-05）共 26 筆事件，依交易所與事件類型分組：

- bitget / DELISTED：4 筆
  - DOODUSDT：online → None
  - IKAUSDT：online → None
  - MEZOUSDT：online → None
  - STORJUSDT：online → None
- bybit / DELISTED：3 筆
  - GODSUSDT：Trading → None
  - HFTUSDC：Trading → None
  - SCRTUSDT：Trading → None
- htx / LISTED：1 筆
  - marscoinusdt：None → online
- mexc / DELISTED：10 筆
  - ASPUSDT：1 → None
  - CZUSD1：1 → None
  - CZUSDT：1 → None
  - KINSUSD1：1 → None
  - KINSUSDT：1 → None
- mexc / LISTED：8 筆
  - FATCOINUSD1：None → 1
  - FATCOINUSDT：None → 1
  - MEMEROBINHOODUSD1：None → 1
  - MEMEROBINHOODUSDT：None → 1
  - ROBINCATUSD1：None → 1

## 排程執行狀況

**軌一（track-crypto）**（自動探索到 24 個來源）：
- 今日已執行（依 manifest `fetched_at`=2026-09-05 判斷），manifest 記錄 24 個來源。
- manifest 由 1 次執行合併寫入（`runs` 陣列）。
- cron.log 最近一次摘要（僅供耗時／歷史參考）：24/24 成功
- 近 7 次執行成功率（cron.log 歷史）：24/24、24/24、24/24、24/24、24/24、24/24、24/24
**軌二（track-gov）**（自動探索到 18 個來源）：
- 今日已執行（依 manifest `fetched_at`=2026-09-05 判斷），manifest 記錄 18 個來源。
- manifest 由 1 次執行合併寫入（`runs` 陣列）。
- cron.log 最近一次摘要（僅供耗時／歷史參考）：18/18 成功
- 近 7 次執行成功率（cron.log 歷史）：17/18、18/18、18/18、18/18、18/18、18/18、18/18

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

## 累積統計

- 資料起訖日期：2026-08-26 ～ 2026-09-05（共 11 天，實際有紀錄 11 天）
- track-crypto 累積體積：115,571,189 B（11 天有 manifest）
  - 依現速率推算：1 年約 3.6 GB，5 年約 17.9 GB
- track-gov 累積體積：14,822,027 B（10 天有 manifest）
  - 依現速率推算：1 年約 515.9 MB，5 年約 2.5 GB

## 異常摘要

以下 1 項為官方異常清單，判定邏輯直接呼叫 `healthcheck.py` 的 `check_timestamps`／`check_manifest`／`check_truncation_streak`／`check_source`（唯讀，本檔不寫入 ALERT.md），與當日 ALERT.md 逐項一致：

| 來源 | 問題（與 healthcheck.py / ALERT.md 同一套判定） |
|---|---|
| `track-crypto/mcp_smithery` | 連續 2 天截斷（truncated=true，達門檻 2 天）：2026-09-04 實際 273 筆／耗時 6.9s；2026-09-05 實際 272 筆／耗時 6.9s；目標（近期未截斷）約 未知（近期無未截斷紀錄可比對） |

以下為 ALERT.md 等檔案的原始內容（供交叉核對）：

**ALERT.md**（存在）：
> # 🔴 每日自我檢查發現異常
> 
> 檢查時間（UTC）：2026-09-05T03:32:20+00:00
> 檢查時間（台北）：2026-09-05T11:32:20+08:00
> 檢查基準日（UTC）：2026-09-05
> 
> | 來源 | 問題 |
> |---|---|
> | `track-crypto/mcp_smithery` | 連續 2 天截斷（truncated=true，達門檻 2 天）：2026-09-04 實際 273 筆／耗時 6.9s；2026-09-05 實際 272 筆／耗時 6.9s；目標（近期未截斷）約 未知（近期無未截斷紀錄可比對） |
> 

- ALERT-DETECT.md：不存在
- ALERT-HEALTH.md：不存在
- ALERT-DELIST.md：不存在
- ALERT-BACKUP.md：不存在
- ALERT-CEXGATE.md：不存在
- ALERT-DELISTGATE.md：不存在

## 暫不判定／基準重建中（資訊，非異常，不計入異常數，不寫入 ALERT.md）

以下來源的 `parser_version` 在體積比較視窗（最近 7 天）內發生變更，`healthcheck.py` 的 `check_source()`（與 `ALERT.md` 同一套判定函式，見上方〈異常摘要〉呼叫的 `build_health_issues()`）依既有原則（比照 `detect_changes.py`）暫時跳過本次體積判定，等視窗內全部天數都變成新版本後自動恢復判定，不需人工介入、不留白名單。**這是資訊性狀態，不是異常**：不計入本報告與 `ALERT.md` 的異常總數，也不會寫入 `ALERT.md`。下表直接解析自 `check_source()` 本次執行時印出的 NOTICE 訊息，與〈異常摘要〉同一次呼叫、非本檔另行計算。

| 來源 | parser_version 變化 | 進度（第幾天／共幾天） |
|---|---|---|
| `track-gov/moi_press` | 1 → 2 | 第 5／7 天 |
| `track-gov/pres_news` | 1 → 2 | 第 3／7 天 |


---
本報告僅陳述資料蒐集流程的技術事實（筆數、體積、耗時、排程狀態），不構成任何投資建議或市場判斷。
