# 每日資料蒐集報告

產生時間：2026-09-02 03:30:57 UTC（台北時間 2026-09-02 11:30:57 UTC+8）

## 一句話結論

有 3 項異常（與 ALERT.md 採同一套 healthcheck.py 判定邏輯，逐項一致），詳見下方各節。

（本輪自動探索到 42 個來源：軌一 24 個、軌二 18 個；新增來源不需再修改本程式。）

## 來源對照表

| 軌 | 來源 | 中文名 | 今日筆數 | 昨日筆數 | 增減 | 今日體積 | 體積增減% | 耗時 | 嘗試 | 截斷 | 解析失敗 | 備註 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 軌一 | agent_virtuals | Virtuals Protocol agent 清單 | — | — | — | 1,842,068 B | +0.1% | 1403.6s | 1 | — | — |  |
| 軌一 | airdrop_claim_pages | 空投資格規則頁 | — | — | — | 927 B | +0.0% | 0.3s | 1 | — | — |  |
| 軌一 | audit_registry_certik | CertiK Skynet 首頁「Recently Audited」最新審計清單 | — | — | — | 670 B | +3.2% | 0.2s | 1 | — | — |  |
| 軌一 | cex_announcements | 交易所公告 | — | — | — | 7,183 B | +3.1% | 16.4s | 1 | — | — |  |
| 軌一 | cex_currency_status | 交易所幣種層級狀態旗標 | — | — | — | 292,776 B | +0.1% | 6.4s | 1 | — | — |  |
| 軌一 | cex_earn_apr | CEX 理財年化率 | — | — | — | 9,033 B | -0.1% | 2.1s | 1 | — | — |  |
| 軌一 | cex_symbols | 7 家 CEX 交易對／幣種狀態 | 10,716 | 10,697 | +19 | 406,527 B | +0.1% | 14.3s | 1 | — | — |  |
| 軌一 | cex_symbols_ext | 新增 3 家交易所 | — | — | — | 63,094 B | +0.2% | 5.1s | 1 | — | — |  |
| 軌一 | cex_withdrawal_limits | KuCoin 幣種提幣費與最低提幣額 | — | — | — | 142,106 B | +0.0% | 0.5s | 1 | — | — |  |
| 軌一 | crypto_project_liveness | DefiLlama 駭客事件清單 | — | — | — | 33,538 B | +0.1% | 0.1s | 1 | — | — |  |
| 軌一 | dao_proposal_snapshot | Snapshot DAO 提案中繼資料快照 | — | — | — | 396,128 B | +0.0% | 9.8s | 1 | — | — |  |
| 軌一 | defi_yield_rates | LST/LRT 質押與 DeFi 借貸利率 | — | — | — | 1,489 B | +0.7% | 3.4s | 1 | — | — |  |
| 軌一 | eth_validator_queue | 以太坊驗證者進出隊列各狀態筆數 | — | — | — | 214 B | +0.0% | 4.3s | 1 | — | — |  |
| 軌一 | hf_trending_models | HuggingFace trending 模型清單 | — | — | — | 106,158 B | +1.6% | 0.5s | 1 | — | — |  |
| 軌一 | mcp_smithery | MCP Smithery 註冊表 | — | — | — | 82,921 B | -1.2% | 6.8s | 1 | — | — |  |
| 軌一 | ofac_sanctions_crypto | OFAC SDN 制裁名單 | — | — | — | 934,695 B | +0.0% | 12.6s | 1 | — | — |  |
| 軌一 | openrouter_models | OpenRouter 全模型清單與定價 | — | — | — | 70,811 B | -0.6% | 0.1s | 1 | — | — |  |
| 軌一 | openrouter_providers | OpenRouter 供應商清單 | — | — | — | 3,662 B | +0.1% | 0.0s | 1 | — | — |  |
| 軌一 | oracle_feed_directory | Chainlink／Pyth 價格餵送目錄 | — | — | — | 167,654 B | +0.3% | 1.5s | 1 | — | — |  |
| 軌一 | payment_protocol_repos | 支付協議規格版本 GitHub Repo 中繼資料 | — | — | — | 556 B | -0.4% | 0.7s | 1 | — | — |  |
| 軌一 | project_tokenomics_docs | 專案官方 tokenomics 文件頁 | — | — | — | 751 B | +0.0% | 0.1s | 1 | — | — |  |
| 軌一 | vast_gpu | Vast.ai GPU 租賃市場報價 | 512 | 512 | +0 | 173,964 B | -0.9% | 1.6s | 1 | — | — |  |
| 軌一 | x402_bazaar | x402 Bazaar 全量掛牌 | 14,929 | 14,674 | +255 | 6,423,926 B | +3.0% | 48.4s | 1 | — | — |  |
| 軌一 | x402_index_thirdparty | x402scan 第三方索引 sitemap URL 清單 | — | — | — | 23,423 B | -0.0% | 1.3s | 1 | — | — |  |
| 軌二 | cbc_press | 中央銀行新聞稿 | 99 | 99 | +0 | 47,762 B | +0.0% | 209.8s | 1 | 否 | 否 |  |
| 軌二 | ey_press | 行政院本院新聞 | 100 | 100 | +0 | 175,749 B | +0.0% | 257.1s | 1 | 否 | 否 |  |
| 軌二 | fda_clarify | 食藥署 食藥闢謠專區 | 50 | 50 | +0 | 21,087 B | +0.0% | 202.8s | 1 | 否 | 否 |  |
| 軌二 | fsc_clarification | 金管會即時新聞澄清 | 50 | 50 | +0 | 38,428 B | +0.0% | 104.6s | 1 | 否 | 否 |  |
| 軌二 | fsc_lawnotice | 金管會法規草案預告 | 100 | 100 | +0 | 25,287 B | +0.0% | 187.6s | 1 | 否 | 否 |  |
| 軌二 | fsc_penalty | 金管會裁罰案件 | 100 | 100 | +0 | 140,030 B | +0.0% | 187.0s | 1 | 否 | 否 |  |
| 軌二 | ftc_decision | 公平交易委員會 本會行政決定 | 100 | 100 | +0 | 17,369 B | +0.0% | 54.7s | 1 | 否 | 否 |  |
| 軌二 | moda_press | 數位發展部新聞發布 | 100 | 100 | +0 | 98,057 B | -0.0% | 108.4s | 1 | 否 | 否 |  |
| 軌二 | moe_clarify | 教育部即時新聞澄清 | 80 | 80 | +0 | 72,999 B | +0.0% | 254.1s | 1 | 否 | 否 |  |
| 軌二 | moe_press | 教育部即時新聞 | 100 | 100 | +0 | 122,091 B | +0.5% | 370.3s | 1 | 否 | 否 |  |
| 軌二 | moea_press | 經濟部本部新聞 | 100 | 100 | +0 | 120,219 B | -0.2% | 216.2s | 1 | 否 | 否 |  |
| 軌二 | mof_press | 財政部本部新聞 | 99 | 99 | +0 | 84,131 B | -0.2% | 255.9s | 1 | 否 | 否 |  |
| 軌二 | mohw_press | 衛生福利部焦點新聞 | 100 | 100 | +0 | 123,070 B | +2.8% | 203.3s | 1 | 否 | 否 |  |
| 軌二 | moi_press | 內政部新聞稿 | 100 | 100 | +0 | 99,884 B | +0.1% | 211.3s | 1 | 否 | 否 |  |
| 軌二 | moj_press | 法務部新聞發布 | 50 | 50 | +0 | 56,670 B | +0.0% | 111.7s | 1 | 否 | 否 |  |
| 軌二 | mol_press | 勞動部新聞稿 | 100 | 100 | +0 | 131,647 B | -0.5% | 287.7s | 1 | 否 | 否 |  |
| 軌二 | pres_news | 總統府新聞 | 100 | 15 | +85 | 181,537 B | +428.9% | 190.8s | 1 | 否 | 否 |  |
| 軌二 | tpe_clarify | 台北市政府即時新聞澄清 | 50 | 50 | +0 | 35,472 B | +0.0% | 127.0s | 1 | 否 | 否 |  |

註：本表「截斷」「解析失敗」欄位標記的來源屬於資料品質提示；官方異常總數以下方〈異常摘要〉為準，避免同一件事重複計數。

## 變動偵測

最近一輪變動偵測：

| 來源 | 區間 | 改寫 | 下架 | 新增 | 滾動移出 |
|---|---|---|---|---|---|
| cbc_press | 2026-09-01→2026-09-02 | 0 | 0 | 1 | 1 |
| ey_press | 2026-09-01→2026-09-02 | 0 | 0 | 1 | 1 |
| fda_clarify | 2026-09-01→2026-09-02 | 0 | 0 | 0 | 0 |
| fsc_clarification | 2026-09-01→2026-09-02 | 0 | 0 | 0 | 0 |
| fsc_lawnotice | 2026-09-01→2026-09-02 | 0 | 0 | 0 | 0 |
| fsc_penalty | 2026-09-01→2026-09-02 | 0 | 0 | 0 | 0 |
| ftc_decision | 2026-09-01→2026-09-02 | 0 | 0 | 0 | 0 |
| moda_press | 2026-09-01→2026-09-02 | 0 | 0 | 1 | 1 |
| moe_clarify | 2026-09-01→2026-09-02 | 0 | 0 | 0 | 0 |
| moe_press | 2026-09-01→2026-09-02 | 0 | 0 | 2 | 2 |
| moea_press | 2026-09-01→2026-09-02 | 0 | 0 | 5 | 5 |
| mof_press | 2026-09-01→2026-09-02 | 0 | 0 | 6 | 6 |
| mohw_press | 2026-09-01→2026-09-02 | 0 | 0 | 5 | 5 |
| moi_press | 2026-09-01→2026-09-02 | 0 | 0 | 2 | 2 |
| moj_press | 2026-09-01→2026-09-02 | 0 | 0 | 0 | 0 |
| mol_press | 2026-09-01→2026-09-02 | 0 | 0 | 1 | 1 |
| tpe_clarify | 2026-09-01→2026-09-02 | 0 | 0 | 0 | 0 |
| **總計** |  | 0 | 0 | 24 | 24 |

因解析器改版跳過本次比對（非內容改寫，非異常）：pres_news（v1→v2）

本輪彙總：changed=0，removed=0。

`changes/` 目錄下有 2 個來源目錄記錄改寫內容：
- mof_press
- x402_bazaar

`CHANGES.md` 存在，內容請參閱該檔案。

## 交易所事件流

今日（2026-09-02）共 36 筆事件，依交易所與事件類型分組：

- gateio / DELISTED：1 筆
  - XAR_USDT：untradable → None
- gateio / LISTED：14 筆
  - ARKM_USD：None → tradable
  - BMNR3L_USDT：None → tradable
  - BMNR3S_USDT：None → tradable
  - BONK_USD：None → tradable
  - CP_USDT：None → sellable
- kucoin / DELISTED：1 筆
  - XRD-USDT：True → None
- mexc / DELISTED：6 筆
  - GPUUSDT：1 → None
  - GRMUSDT：1 → None
  - KUVIUSDT：1 → None
  - RAZORUSDT：1 → None
  - SCRTUSDT：1 → None
- mexc / LISTED：11 筆
  - AUUSD1：None → 1
  - AUUSDT：None → 1
  - CPUSDT：None → 2
  - MOOUSD1：None → 1
  - MOOUSDT：None → 1
- mexc / STATUS_CHANGED：1 筆
  - PBALLUSDT：2 → 1
- okx / LISTED：2 筆
  - CP-TRY：None → preopen
  - CP-USDT：None → preopen

## 排程執行狀況

**軌一（track-crypto）**（自動探索到 24 個來源）：
- 今日已執行（依 manifest `fetched_at`=2026-09-02 判斷），manifest 記錄 24 個來源。
- manifest 由 1 次執行合併寫入（`runs` 陣列）。
- cron.log 最近一次摘要（僅供耗時／歷史參考）：24/24 成功
- 近 7 次執行成功率（cron.log 歷史）：3/3、3/3、24/24、24/24、24/24、24/24、24/24
**軌二（track-gov）**（自動探索到 18 個來源）：
- 今日已執行（依 manifest `fetched_at`=2026-09-02 判斷），manifest 記錄 18 個來源。
- manifest 由 1 次執行合併寫入（`runs` 陣列）。
- cron.log 最近一次摘要（僅供耗時／歷史參考）：18/18 成功
- 近 6 次執行成功率（cron.log 歷史）：11/11、17/18、17/18、18/18、18/18、18/18

## 時間戳

- SHA256SUMS-2026-08-27.txt：有 對應 `.ots`
- SHA256SUMS-2026-08-28.txt：有 對應 `.ots`
- SHA256SUMS-2026-08-29.txt：有 對應 `.ots`
- SHA256SUMS-2026-08-30.txt：有 對應 `.ots`
- SHA256SUMS-2026-08-31.txt：有 對應 `.ots`
- SHA256SUMS-2026-09-01.txt：有 對應 `.ots`
- SHA256SUMS-2026-09-02.txt：有 對應 `.ots`

## 累積統計

- 資料起訖日期：2026-08-26 ～ 2026-09-02（共 8 天，實際有紀錄 8 天）
- track-crypto 累積體積：81,089,653 B（8 天有 manifest）
  - 依現速率推算：1 年約 3.4 GB，5 年約 17.2 GB
- track-gov 累積體積：10,027,549 B（7 天有 manifest）
  - 依現速率推算：1 年約 498.6 MB，5 年約 2.4 GB

## 異常摘要

以下 3 項為官方異常清單，判定邏輯直接呼叫 `healthcheck.py` 的 `check_timestamps`／`check_manifest`／`check_truncation_streak`／`check_source`（唯讀，本檔不寫入 ALERT.md），與當日 ALERT.md 逐項一致：

| 來源 | 問題（與 healthcheck.py / ALERT.md 同一套判定） |
|---|---|
| `track-gov/fda_clarify` | 體積異常：今日 21,087 B，前 5 日中位數 46,775 B（0.45×，容許 0.5–3.0×） |
| `track-gov/pres_news` | 體積異常：今日 181,537 B，前 5 日中位數 42,039 B（4.32×，容許 0.5–3.0×） |
| `track-gov/tpe_clarify` | 體積異常：今日 35,472 B，前 5 日中位數 73,302 B（0.48×，容許 0.5–3.0×） |

以下為 ALERT.md 等檔案的原始內容（供交叉核對）：

**ALERT.md**（存在）：
> # 🔴 每日自我檢查發現異常
> 
> 檢查時間（UTC）：2026-09-02T03:30:57+00:00
> 檢查時間（台北）：2026-09-02T11:30:57+08:00
> 檢查基準日（UTC）：2026-09-02
> 
> | 來源 | 問題 |
> |---|---|
> | `track-gov/fda_clarify` | 體積異常：今日 21,087 B，前 5 日中位數 46,775 B（0.45×，容許 0.5–3.0×） |
> | `track-gov/pres_news` | 體積異常：今日 181,537 B，前 5 日中位數 42,039 B（4.32×，容許 0.5–3.0×） |

- ALERT-DETECT.md：不存在
- ALERT-HEALTH.md：不存在
- ALERT-DELIST.md：不存在


---
本報告僅陳述資料蒐集流程的技術事實（筆數、體積、耗時、排程狀態），不構成任何投資建議或市場判斷。
