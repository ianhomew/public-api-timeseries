#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""track-crypto/scripts/detect_delistings.py — 軌一下架偵測（第一階段：僅 x402_bazaar）

本版修正紀錄（第二輪，接續 §1～§3 回放驗證完成後處理已知風險）：
  異常告警管道由「共用 ALERT.md」改為「獨立 ALERT-DELIST.md」。原因、取捨與重跑驗證
  結果見下方「異常告警改用獨立檔案」小節與本機 docs/detect-phase1-report.md 第 4 節。
  本次修正只影響 write_alert_block() 與相關文字說明，四道閘門、事件流、changes/、
  CHANGES.md 的邏輯與輸出格式完全不變（§1～§3 的回放驗證結論不受影響）。

本版修正紀錄（第三輪，本輪，接續 §4～§8 完成後處理 §5 誠實揭露的「重新出現」風險；
父代理裁示「採方案 1＋3，不採方案 2」，見本機 docs/detect-phase1-report.md §9、
specs/SPEC-reappeared.md）：
  1. 人類可讀輸出（changes/<source>/YYYY-MM-DD.md 由本程式產生的部分、ALERT-DELIST.md）
     的措辭全面把「下架」改為「自清單消失」這類只描述觀察事實的用詞，不使用「下架」
     「delisted」這種帶有永久性推論的字眼。CHANGES.md 共用表頭刻意不改，理由見下方
     「事件型別語意定義（本輪新增）」小節末段。
  2. 新增 REAPPEARED 事件型別：某 resource 若過去任何時間點曾有 DELISTED 紀錄，
     這次比對又出現在「新增」集合裡時，在原本就會寫的 LISTED 事件之外，額外補寫
     一筆 REAPPEARED，讓紀錄自我更正。事件型別名稱 LISTED／DELISTED 本身不變
     （保護已公開介面），compare_pair()／judge() 兩個判定核心函式本輪完全不動。
  3. 在下方新增「事件型別語意定義（本輪新增）」小節，明確定義三種事件型別的語意，
     回應 SPEC 要求「在檔頭註解與報告中明確定義三種事件型別的語意」。
  回放驗證（08-26～09-01 全區間重跑）證明：既有 DELISTED／LISTED 事件集合逐行比對
  完全不變、139 筆已知重新出現案例全數且僅有這些產生 REAPPEARED、同區間重跑不產生
  重複事件（含 REAPPEARED），完整過程與結果見 docs/detect-phase1-report.md §9。
  本次修正只影響 render_report()／write_alert_block()／process_pair()／main()，
  compare_pair()／judge()／snapshots()／completeness()／dedup()／update_index() 五個
  判定與索引核心函式本輪原封不動。

依據：
  - /home/agentops/.../docs 對應本機 SPEC-detect-phase1.md（派工規格）
  - crypto-detect-design.md（父代理已核准的架構決定）

為什麼另寫一支，不擴充 scripts/detect_changes.py：
  detect_changes.py 的來源清單是自動掃描 track-gov/adapters/ 得到的（預設 opt-out，
  新增來源自動被納入）。公開 repo 的下架稽核紀錄必須預設 deny：新增來源必須明確加入
  本檔案的 SOURCES 白名單才會被偵測。兩者資料形狀也不同（track-gov 是單一 items 清單
  + body_text/body_sha256 全文欄位；track-crypto 逐來源結構不同，x402_bazaar 主鍵是
  resource，沒有全文可比對），共用一支程式只會讓 gov 端的穩定邏輯承擔軌一的風險。

第一階段範圍（僅此一項，白名單寫死，禁止自動探索）：
  x402_bazaar —— 唯一一個不必等 manifest 改版就能自我驗證完整性的來源
  （data.total 與 len(data.items) 逐日相符，見設計文件附錄 A.1／本程式 SOURCES 設定）。

四道閘門（依重要性）：
  1. 白名單：來源必須出現在 SOURCES，且 window == "full"（全量清單，不套用滾動視窗語意）。
  2. 完整性守門：data.total 缺失或不等於 len(items)（去重前）→ 該側快照判定失敗。
     比對用的前一日／當日兩份快照都必須通過，任一側失敗 → 本日「不判定」
     （不寫 DELISTED，也不寫 LISTED —— 見下方「與 detect_changes.py 的刻意差異」）。
  3. （抓取成功）快照存在即代表 snap_crypto.py 當天沒有整批失敗；沒有快照的來源在
     snapshots() 階段就不會被納入比對，等同天然涵蓋這一道閘門。
  4. 異常規模熔斷：removed 率 > SOURCES[source]["breaker_pct"]（x402_bazaar 專屬 5%，
     父代理已裁示；日常實測 1.8%～3.7%）→ 不寫 DELISTED，改寫 `ALERT-DELIST.md` 警報，等人工確認。

與 scripts/detect_changes.py 的刻意差異（決策記錄，供稽核）：
  detect_changes.py 在快照截斷時仍照常輸出「新增」（只跳過「下架」）。本程式在完整性守門
  或熔斷觸發時，「新增」也一併不輸出。理由：x402_bazaar 沒有 gov 端那種「單篇公文」的獨立
  真實性（一篇公文即使當日快照不完整，其他文章的新增判定互不相干）；而 x402_bazaar 的「新增」
  是靠「今天有、昨天的（可能不完整的）記錄裡沒有」推出來的 —— 如果昨天那份快照本身就不完整，
  昨天「其實有但沒抓到」的項目，今天會被誤判成「新增」。這是比 gov 端更保守的選擇，
  目前 08-26～09-01 的真實資料完整性守門從未觸發過，這個差異只影響本程式自建的故障注入測試，
  不影響回放驗證的實際輸出。

零觀點鐵律：事件紀錄只寫事實（哪個 resource 在哪天消失／出現），不寫原因推測。

輸出（走既有管道，設計文件第 6 點；異常告警管道已於本輪修正，理由見下方說明）：
  - 事件流（主產物，只追加）：track-crypto/data/<source>/events.jsonl
      {"date","source","group","key","event","from","to"}
      event: LISTED / DELISTED / REAPPEARED（REAPPEARED 為本輪新增；第一階段不含
      STATUS_CHANGED，x402_bazaar 無原生狀態欄位）。三種事件型別的精確語意定義，
      見下方「事件型別語意定義（本輪新增）」小節，不在此重複。
  - 人類可讀日報：changes/<source>/YYYY-MM-DD.md（與軌二共用同一個 changes/ 目錄）
  - 索引：CHANGES.md（共用；本程式產生的列一律在來源欄加 `track-crypto/` 前綴，
      「改寫」欄固定填 `—`，因為軌一沒有全文可比對）
  - 異常告警：ALERT-DELIST.md（獨立檔案，只有本程式讀寫，見下方「異常告警改用獨立檔案」說明）

事件型別語意定義（本輪新增；父代理裁示「採方案 1＋3，不採方案 2」，
見本機 docs/detect-phase1-report.md §5、§9 與 specs/SPEC-reappeared.md）：

  背景：回放 08-26～09-01 發現 139/2570（5.4%；依觀察窗長短不同，08-27 那批觀察窗
  最長，達 16.7%，見報告 §5.2）筆 DELISTED 的 resource 之後又重新出現，且與「前一日
  quality.l30DaysTotalCalls（前 30 天呼叫次數）」高度相關：呼叫次數=1 的子群組重現率
  18.1%，呼叫次數>1 的子群組重現率 0.0%（見報告 §5.3）。這是 x402_bazaar 這個資料源
  本身「大量低流量端點存活狀態不穩定」的真實現象，已用原始 gzip 逐筆核對，不是本程式
  的判定錯誤或「假下架」；但「下架」一詞在中文語境容易被讀者理解成「永久性移除」，
  這個推論在本資料源不成立，需要修正措辭與補充事件型別來避免誤導。

  事件型別名稱（LISTED／DELISTED／REAPPEARED）本身維持不變，不重新命名既有兩種型別，
  也不變更 compare_pair()／judge() 的判定邏輯——events.jsonl 是已有既存資料、可能已被
  其他程式或人工流程讀取的介面，重新命名或砍掉既有型別是破壞性變更，超出本輪「修正
  措辭＋新增事件」的授權範圍。本輪只用「新增型別」與「調整人類可讀措辭」處理已知的
  誤導風險。

    - LISTED：某 resource 在「當日快照」存在、但在「前一份可比對快照」不存在。
      只描述這一個事實（當日自清單出現），不代表這是全新誕生的服務。如果這個
      resource 過去曾有 DELISTED 紀錄，這次會**額外多寫一筆 REAPPEARED**（不取代
      LISTED，兩筆事件同一天、同時存在，見下）。

    - DELISTED：某 resource 在「當日快照」不存在、但在「前一份可比對快照」存在。
      只描述這一個事實（當日自清單消失），**不代表永久下架**：見上方背景說明，
      本資料源有相當比例（依觀察窗長短，5.4%～16.7%）的 DELISTED 案例會在數天內
      重新出現。完整性守門（total == len(items)）驗證的是「這次抓取有沒有抓完整」，
      跟「消失的項目之後會不會回來」是兩個不同層次的問題，兩者不能混為一談
      （詳見報告 §5.4）。

    - REAPPEARED（本輪新增）：某 resource 過去任何時間點曾有 DELISTED 紀錄，這次
      比對又出現在「新增」集合裡時，在原本就會寫的 LISTED 事件之外，額外補寫的
      一筆事件。欄位沿用既有 7 欄結構："from" 放「上一次被記為消失的日期」
      （字串，格式與 "date" 欄相同），"to" 放這次出現時的簡短描述（與 LISTED 的
      "to" 同一定義，見 short_desc()）。讓單一事件行就能還原「消失又出現、間隔
      幾天」，不必額外去比對其他行——這就是 SPEC 講的「讓紀錄自我更正」。純粹
      陳述「先前記為消失、現在又出現」這個事實，不推測原因（可能是探測暫時失敗、
      也可能是先下架後來恢復，本程式不對此下定論，零觀點鐵律）。判定與寫入時機：
      只在 judged == "NORMAL" 時計算與寫入，與既有 LISTED／DELISTED 的閘門條件
      完全一致（GATE_FAIL／BREAKER 當天原本就不寫 LISTED／DELISTED，REAPPEARED
      也比照不寫）。

  人類可讀輸出的措辭調整範圍：changes/<source>/YYYY-MM-DD.md（本程式產生的部分）
  與 ALERT-DELIST.md，全面把「下架」改為「自清單消失」這類只描述觀察事實的用詞。
  CHANGES.md 的表頭與前言文字**刻意不改**：它與 scripts/detect_changes.py 的
  update_index() 逐字共用同一份 head 列表（含「下架」欄名，已於本輪核對兩份原始碼
  逐字相同），本程式不被授權修改 detect_changes.py（正式檔案，本輪硬性限制唯讀），
  若只改自己這一份 head，兩支程式往後不論哪一支最後執行，都會讓 CHANGES.md 的表頭
  文字隨執行順序忽而顯示這個用詞、忽而顯示那個用詞——這比維持現狀更不可預期、更容易
  誤導人，因此保留原樣（沿用 detect_changes.py 現有的「下架」欄名），只在本程式產生
  的**列內容**（例如新增欄附註重新出現筆數）與**連結進去的日報**裡呈現新措辭與
  REAPPEARED 統計。這是本輪唯一未能逐字落實父代理裁示（「changes/*.md、CHANGES.md、
  ALERT-DELIST.md 一律改用」）的地方，已記錄於報告 §9，留供父代理決定是否要另外
  派工同時修改 detect_changes.py（那份檔案超出本任務授權範圍，本輪未觸碰）。

異常告警改用獨立檔案 ALERT-DELIST.md（本輪修正，取代先前假設共用 ALERT.md 的草稿）：
  設計文件 2.6 原本建議熔斷警報寫共用 ALERT.md（理由：對外只該有一種「有事要處理」的
  位置）。本輪用 /tmp 複本重跑驗證後推翻此設計，原因是實測發現 scripts/healthcheck.py
  把 ALERT.md 當成自己獨佔的輸出，不是共用資源：issues 為空時 os.remove(OUT)，非空時
  open(OUT, "w") 整檔覆寫（healthcheck.py 第 253~257、283 行），兩種情況都不會先讀取
  既有內容再合併。這代表不論 detect_delistings.py 掛在 push.sh 的哪個位置，只要
  healthcheck.py 在下一輪執行（每日一次），本程式寫入的熔斷區塊必定會在最多一個排程
  週期內被整檔洗掉，而且會不會被洗掉，只取決於「healthcheck.py 那天自己有沒有查到
  異常」，跟熔斷警報有沒有被人看到、確認過完全無關——調整掛載順序至多只能延後被洗掉
  的時間，不能解決問題本身。

  改用本程式獨佔的 ALERT-DELIST.md 後，這個檔案所有權衝突從根本上消失，
  不必修改 healthcheck.py，也不必依賴掛載順序（第 6 節「掛載步驟建議」因此可以把
  這一支程式掛在設計文件原本建議的位置，即 cex_events.py 旁邊，不必刻意排到
  healthcheck.py 之後）。這個做法延續本專案既有慣例，不是新發明：scripts/push.sh
  第 46、74 行已經有 ALERT-DETECT.md（detect_changes.py 失敗時）、ALERT-HEALTH.md
  （healthcheck.py 自己掛掉時）這兩個先例，一律是「各自獨立檔案、由 push.sh 第 120
  行用檔案是否存在 OR 起來決定要不要對外回報失敗」；scripts/daily_report.py 的
  build_alert_section()（第 879 行）也已經是用一個檔名清單逐一檢查。新增
  ALERT-DELIST.md 這個檔名到 push.sh 第 120 行與 daily_report.py 的 alert_files
  清單，是掛載本程式時需要一併做的兩處小改動（各一行），但那兩處都是正式檔案，
  本輪硬性限制不能修改，已列入報告第 6 節「掛載步驟建議」與第 7 節風險，不影響
  本程式自身現在的正確性：本程式對 ALERT-DELIST.md 的寫入，在任何掛載順序下都
  正確、不會被沖掉，差別只在於「沖掉前既有的通知鏈（daily_report／push.sh 失敗
  回報）暫時還看不到這個新檔案」，是純粹的擴大通知範圍問題，不是資料正確性問題。

  是否曾考慮改成「讓 healthcheck.py 自己納入下架熔斷判定」（父代理提出的另一個選項）：
  考慮過，但不採用。理由與本設計文件 2.1 節「detect_changes.py 該不該擴充」用的是
  同一套論證，只是換了方向：healthcheck.py 是通用的「缺檔／體積異常／manifest 失敗」
  基礎設施監控，跟 x402_bazaar 下架判定是完全不同的關注點；硬把後者的設定表、完整性
  守門、熔斷邏輯塞進 healthcheck.py，會讓一支面向全部來源的基礎設施監控程式去耦合
  單一來源的業務邏輯，任何一邊的臭蟲都可能波及另一邊（例如熔斷計算拋例外，可能連帶
  讓 healthcheck.py 連缺檔／體積異常這種更基本的檢查都失敗）。獨立檔案不需要這種
  耦合，只是換了一個「共用哪個檔案」的答案，不是換了「該不該共用程式邏輯」的答案。

本輪限制（硬性）：本檔案本身不寫入任何檔案系統路徑以外的東西；正式部署位置為
track-crypto/scripts/detect_delistings.py，執行時的實際輸出路徑一律用 __file__ 動態推算
（不寫死機器路徑），因此在 /tmp 的鏡像目錄下執行時天然不會碰到正式目錄。

============================================================================
第二階段（本輪，2026-09-02，接續上面第一階段～第三輪修正完成後）：
把甲組其餘 8 個來源（cex_currency_status／cex_earn_apr／cex_symbols_ext／
cex_withdrawal_limits／ofac_sanctions_crypto／openrouter_models／
openrouter_providers／payment_protocol_repos）納入白名單，依 SPEC-detect-phase2.md。
cex_symbols 已由既有 scripts/cex_events.py 處理，依 SPEC 指示不重複納入。

本輪只在檔案下半部新增 GROUP_SOURCES 設定表與 10 個新函式（path_get／
extract_group_items／completeness_group／short_desc_generic／compare_group／
status_changes_for_group／build_group_events／render_group_source_report／
write_alert_block_group／process_group_source_pair），並在 main() 新增一個
獨立的第二迴圈。上面第一階段的 SOURCES／completeness()／dedup()／
compare_pair()／judge()／render_report()／process_pair()／write_alert_block()
八個函式與設定表**一個字元都沒有修改**，dedup()／judge() 是既有通用工具，
本階段直接原樣重用（只是被新函式以不同引數呼叫，呼叫點是全新程式碼，
不影響 x402_bazaar 原本的呼叫路徑）。write_alert_block() 因檔頭文字寫死
「x402_bazaar」字樣不適合直接重用，另外新增 write_alert_block_group()
（檔頭文字改為不寫死來源名稱，因 ALERT-DELIST.md 現在是多來源共用檔案），
兩函式互不呼叫、各自獨立判斷檔案是否已存在。

事件型別新增 STATUS_CHANGED（第一階段只有 LISTED/DELISTED/REAPPEARED，
因為 x402_bazaar 沒有原生狀態欄位）：對於原生帶狀態旗標的子集合（例如
cex_currency_status.gate 的 delisted／trade_disabled／withdraw_disabled、
coinbase 的 status、openrouter_models 的 expiration_date），除了既有的
集合差（LISTED/DELISTED）外，額外偵測「主鍵仍在清單中、但欄位值變了」
的情況。本輪實測發現這件事很關鍵：cex_currency_status.gate 有 41.7%、
cex_symbols_ext.coinbase 有 37.6%、cex_currency_status.coinbase 有 16.9%
的項目旗標已是「已下架」狀態，但主鍵從未離開清單——只做集合差會嚴重
低估這些來源的下架語意，這是設計文件 §2.3「原生旗標優先於集合差」建議
的具體實測驗證。

完整性守門新增 range_check 方式（第一階段只有 total_match，因為
x402_bazaar 有 data.total 自報欄位）：本輪 8 個來源中有 4 個
（cex_currency_status／cex_earn_apr／cex_symbols_ext／cex_withdrawal_limits）
沒有任何自報總數欄位，改用「08-28~09-02 六天實測 min/max 各加 10% 安全
邊界」訂出固定合理區間，原始筆數落在區間外視為不完整。此為本輪工程判斷
（推論），非官方欄位保證，區間應隨資料持續累積重新校準。

熔斷門檻逐來源／逐子集合依實測資料訂定（不是全部沿用 x402_bazaar 的 5%），
公式與既有 scripts/cex_events.py 的 max(CB_MIN_ABS, len(pa)*CB_PCT) 同構。
本輪 8 個來源中 7 個子集合實測「5 組相鄰日 removed_pct 全為 0%」，門檻落在
1.0% 底線（遠比 x402_bazaar 的 5% 嚴格）；openrouter_models 實測有一組
1.8824% 的真實移除事件（經雙自報欄位確認非截斷），門檻另訂 3.0%；
payment_protocol_repos（n=3）改用「過半即熔斷」規則（breaker_pct=60%、
abs_floor=1），因為 n=3 時共通公式的 abs_floor=5 會讓熔斷永遠無法觸發。

完整推導過程、逐來源實測數字、四項驗收（零假消失／故障注入／冪等性 3 次／
不影響第一階段）的完整輸出，見本機
docs/detect-phase2-report.md（不隨程式碼進 repo，只在派工方本機保存）。

本輪同樣硬性限制：只在 VPS /tmp/detect-phase2/ 驗證，正式目錄一個字元都
沒有改，未 git commit、未安裝套件。
============================================================================

第三階段（本輪，2026-09-04，接續第一、二階段完成後，依 specs/SPEC-gate-dedup.md）：
GATE_FAIL（完整性守門不通過）先前只落地 changes/<source>/YYYY-MM-DD.md 與
CHANGES.md 索引列，沒有接任何告警——只有 BREAKER（熔斷）會寫 ALERT-DELIST.md
（gate-alert 子代理 2026-09-04 稽核 SPEC-gate-alert.md 時發現的額外缺口，
與同一輪發現的 gate_skips.jsonl 缺去重是姊妹缺口，兩者本輪一併修）。

本輪只新增 GATE_FAIL_LOG／GATE_FAIL_LOG_SIZE_HINT_LINES 兩個模組層級常數、
load_gate_fail_seen()／record_gate_fail() 兩個新函式，並在 process_pair()／
process_group_source_pair() 各自的既有 BREAKER 判斷式之前，各新增一段對稱的
「if judged == GATE_FAIL: 呼叫 record_gate_fail()」（純加法，不改動任一函式
既有的判定或輸出邏輯）；process_pair()／process_group_source_pair() 的函式簽名
各自多一個有預設值（None）的 gate_fail_seen 關鍵字引數，未傳入時函式行為與
本輪之前完全相同（自行讀檔判斷），所有既有呼叫端（含 scripts/selftest.py
既有 66 條檢查目前的呼叫方式）不必修改也不受影響。

record_gate_fail() 把 GATE_FAIL 事實寫進新的 track-crypto/data/_gate_fail/
gate_skips.jsonl（去重鍵 (date,source,group,reason)，設計與寫入時機的完整理由見
該函式 docstring 與本機 docs/gate-dedup-report.md），供 scripts/healthcheck.py
新增的 check_delist_gate_fail() 讀取後決定要不要產生／移除 ALERT-DELISTGATE.md
（獨立新檔案，理由見 healthcheck.py 該函式模組層級註解——ALERT-DELIST.md 檔頭
明文宣告「本檔案由 detect_delistings.py 獨佔寫入，不與任何其他程式共用」，
GATE_FAIL 需要的「異常排除後自動消失」語意也與 ALERT-DELIST.md「一旦觸發永久
留存」的設計初衷相反，比照 cex_events.py 的 gate_skips.jsonl／ALERT-CEXGATE.md
既有先例，不去打破這兩個既有的設計不變量）。

本輪不修改：compare_pair()／compare_group()／judge()／build_group_events()／
render_report()／render_group_source_report()／write_alert_block()／
write_alert_block_group()／dedup()／completeness()／completeness_group() 這些
既有判定與輸出核心函式一個字元都沒有改，ALERT-DELIST.md／events.jsonl／
changes/*.md／CHANGES.md 四個既有輸出管道的邏輯與格式完全不變（已用「對真實
歷史資料重跑、events.jsonl 逐位元組不變」驗證，見本機 docs/gate-dedup-report.md）。

本輪同樣硬性限制：只在 VPS /tmp/gate-dedup/ 驗證，正式目錄一個字元都沒有改，
未 git commit、未安裝套件。

本輪修正紀錄（第三階段，本輪，接續第二階段與 gate-dedup，依 specs/SPEC-detect-phase3.md）：
  把乙組 3 個來源實測後納入 2 個（agent_virtuals／crypto_project_liveness），
  第 3 個來源（oracle_feed_directory）只納入其中 1 個子集合（pyth；chainlink
  因 8 天實測零異動、range_check 缺乏真實變動範圍可校準，判定證據不足不納入，
  依 SPEC 指示「不足就不要納入，寧可少做」處理，完整理由見下方 GROUP_SOURCES
  第三階段新增區塊第 3 點與本機 docs/detect-phase3-report.md §4.3）。
  本輪新增兩處泛化機制，皆為純加法、不修改任何既有分支：
    1. completeness_group() 新增第三種完整性檢查方式 tolerant_total_match
       （agent_virtuals 專用：自報總數與原始筆數容許實測校準的相對誤差，
       且要求來源自帶的 truncated 旗標明確為 False）。
    2. dedup() 新增 key_field 為 tuple 時的複合鍵支援（crypto_project_liveness
       專用：(name, date) 複合鍵，字串成分正規化小寫以避免大小寫修正造成的
       假消失，見報告 §2.2 的 Saturn／SATURN 實測案例）。
  本輪不修改：compare_pair()／compare_group()／judge()／build_group_events()／
  render_report()／render_group_source_report()／write_alert_block()／
  write_alert_block_group()／process_pair()／process_group_source_pair()／
  record_gate_fail()／completeness()／completeness_group() 既有兩個分支
  （total_match／range_check）／dedup() 既有單一欄位分支這些既有判定與輸出
  核心邏輯一個字元都沒有改；events.jsonl／changes/*.md／CHANGES.md／
  ALERT-DELIST.md／gate_skips.jsonl 五個既有輸出管道的邏輯與格式完全不變
  （已用「對真實歷史資料重跑、既有 9 個來源 events.jsonl 逐位元組不變」驗證，
  見本機 docs/detect-phase3-report.md 驗收 4）。

  本輪同樣硬性限制：只在 VPS /tmp/detect-phase3/ 驗證，正式目錄一個字元都沒有改，
  未 git commit、未安裝套件。
============================================================================

第四階段（本輪，2026-09-07，任務 C「統一兩支程式的熔斷語意」，
依 docs/0907-events-audit-0904-0907.md §6.1 揭露的資料缺口）：

  問題（實測，不是推論）：
    1. 同一個「熔斷」概念，本檔案與 scripts/cex_events.py 兩種行為——
       cex_events.py 是「標記但不否決」（事件照寫，加註 note:"anomalous_scale"），
       本檔案是「否決整組」（judged=="BREAKER" 時完全不寫事件）。
    2. 「否決整組」造成不可逆的資料遺失：x402_bazaar 2026-09-06→09-07 熔斷
       （removed 率 8.43%，門檻 5%）讓 1,399 筆 DELISTED、387 筆 LISTED、
       21 筆 REAPPEARED 完全沒有寫入。其中 REAPPEARED 尤其補不回來——那 21 個
       key 在 09-07 快照裡已經回到清單，之後任何一次 09-07→09-08 比對都不會再把
       它們放進 added_keys，判定機會永久消失。
    3. 「否決整組」還有第二層副作用：judged!="NORMAL" 時 last_delisted 不更新，
       那 1,399 個 key 之後若重新出現，也不會被判為 REAPPEARED（會被記成單純的
       LISTED），污染範圍不只熔斷當天。

  本輪統一後的語意（兩支程式共用同一條規則、同一組欄位名、同一個門檻常數語意）：
    - 完整性守門（GATE_FAIL）：**唯一**會讓事件不進 events.jsonl 的「資料不可信」判定。
    - 異常規模熔斷（BREAKER）：**標記但不否決**——事件照常寫入 events.jsonl，
      每一筆額外帶 note:"anomalous_scale"（沿用 cex_events.py 既有欄位）、
      breaker_tripped:true、removed_pct、breaker_threshold 四個欄位，
      並照舊寫 ALERT-DELIST.md 永久告警要求人工複核。
    - 例外（本輪新增的第五道閘門）：熔斷成立時先跑「分頁截斷指紋」檢查
      （removal_tail_metrics() + breaker_release_check()）。指紋成立 → 不寫入
      events.jsonl，改寫入 **隔離檔** data/<source>/events_quarantine.jsonl。
      「隔離」不是「丟棄」：事實仍然完整落地、可被人工複核後以
      tools/promote_quarantine.py 之類的程序提升，**不再有不可逆遺失**。
    - GATE_FAIL 也一併改寫隔離檔（同一機制、同一格式，多 4 行程式碼）：
      agent_virtuals 2026-08-29～09-01 四天 GATE_FAIL 造成的事件遺失
      （見 track-crypto/data/_gate_fail/gate_skips.jsonl）屬於同一類問題，
      本輪一併止血。events.jsonl 的內容與格式不受影響（GATE_FAIL 本來就不寫）。

  為什麼「標記」優於「否決」（不對稱性論證，這是本輪的核心理由）：
    否決造成的遺失**不可逆**（REAPPEARED 判定機會永久消失，沒有任何後續程序補得回來）；
    標記造成的污染**可逆**（每筆都帶標記，下游可過濾，也可用 scripts/apply_correction.py
    更正）。兩種錯誤的代價不對稱，所以預設值應該倒向「保留資料」。

  為什麼還是保留一道「截斷指紋 → 隔離」的閘門（反面風險，SPEC 明文要求評估）：
    若熔斷真的是抓取截斷造成的，「標記不否決」會寫入大量假 DELISTED。
    **注意：規格書建議的「只有 complete=true 才標記不否決」在本檔案是空條件**——
    compare_pair()/compare_group() 的 breaker 一開始就寫成
    `breaker = gate_ok and ...`，judge() 又先回傳 GATE_FAIL，所以 BREAKER 本來就
    蘊含 gate_ok==True，加這個條件等於沒加。真正的破口是
    **x402_bazaar 的 total_match 守門是恆真式**：
    track-crypto/adapters/x402_bazaar.py 的 collect() 最後一行寫
    `return {..., "total": len(items), "items": items}`，自報欄位與被檢查對象是
    同一個數字，對分頁截斷零防護力（docs/0907-events-audit-0904-0907.md §8.1 已獨立
    證實）。manifest 的 truncated 欄位對這個來源同樣無效：
    track-crypto/scripts/snap_crypto.py 的 _find_truncated_flag() 讀不到旗標時一律
    預設 False，而 x402_bazaar 的 data 只有 x402Version/total/items 三個鍵。
    因此本輪改用**與快照內容無關的結構性指紋**：分頁截斷會砍掉「連續尾端區塊」，
    真實下架不會。實測校準見 BREAKER_TAIL_COVER_MAX 常數註解。

  誠實揭露（本輪未解決的殘餘風險）：截斷指紋對「排序不穩定的來源發生中度截斷」無效。
  實測：把 2026-09-07 的 x402_bazaar 快照截到前 15 頁（移除率 11.9%，遠超 5% 門檻），
  tail_cover 仍是 0.0，指紋不會觸發，事件會被標記後寫入。根本解法是修 adapter 保存
  API 自報的 pagination.total（本輪未做，屬 adapter 變更、會動到 PARSER_VERSION，
  超出本任務授權範圍），已列入報告待辦。在那之前，這類事件仍然是「有標記、有永久告警、
  可更正」，比「靜默遺失」好。

  本輪修改範圍（供整合代理合併用，逐一列出）：
    新增常數 QUARANTINE_BASENAME／BREAKER_TAIL_COVER_MAX；
    新增函式 removal_tail_metrics()／_manifest_entry()／breaker_release_check()／
    load_quarantine_seen()／write_quarantine()／breaker_marks()（一整段連續新增）；
    修改 compare_pair()（新增 2 個回傳欄位）、compare_group()（新增 2 個回傳欄位）、
    build_group_events()（允許 BREAKER 建事件並標記）、
    process_pair()／process_group_source_pair()（事件落地去向分流、告警措辭）、
    main()（summary 多印隔離筆數）。
    **未修改**：judge()（仍然只回傳 NORMAL／GATE_FAIL／BREAKER 三個值，公開介面不變）、
    completeness()／completeness_group()／dedup()／snapshots()／load()／
    status_changes_for_group()／render_report()／render_group_source_report()／
    write_alert_block()／write_alert_block_group()／record_gate_fail()／
    load_gate_fail_seen()／update_index()／load_seen()／write_events()。

第四階段修正（本輪，2026-09-07，任務 B「上游改名被誤判成下架」，
依 docs/0907-events-audit-0904-0907.md §5.5 的實測證據）：

  問題：crypto_project_liveness 於 2026-09-06 產生 2 筆假 DELISTED
  （`stake dao\x1f1773273600`／`stake dao\x1f1779840000`）與 2 筆對應的假 LISTED
  （`stake dao yield\x1f...`）。實測逐欄位比對確認：DefiLlama 端把同兩筆歷史事件的
  name 從 "Stake DAO" 改成 "Stake DAO Yield"，date／classification／technique／amount／
  chain／bridgeHack／targetType／language 與 defillamaId（兩天都是 "249"）**逐一相同**。
  第三階段已對 (name, date) 複合鍵做大小寫正規化，但「實質改名」（多一個單字）不在
  該修法的防護範圍內。

  本輪修法（混合式辨識，hybrid identity）：**主鍵字串本身不動**（仍是 (name, date)
  複合鍵，見 dedup()），改在集合差算完之後多一道「穩定 id 對位」抵銷層：
  若同一組相鄰快照裡，某個「消失」的項目與某個「新增」的項目擁有**相同的穩定識別**
  （gcfg["stable_id_fields"]，crypto_project_liveness 為 ("defillamaId", "date")），
  就判定為「同一個東西被上游改名」，兩者同時從 removed_keys／added_keys 移除，
  不寫入 DELISTED／LISTED，只在人類可讀日報與 CHANGES.md 索引列記錄改名事實。

  為什麼不直接把主鍵換成「有 defillamaId 就用它、沒有才退回 (name,date)」的混合主鍵
  （本輪實測後否決，數字見本機 docs/0907-B-rename-key-report.md §3）：
    1. 該做法**修不好問題本身**，只是把假事件換一批。實測 11 天全歷史重放：
       純混合主鍵確實消掉 09-05→09-06 的 2 筆假消失，但同時**新製造 2 筆假消失**——
       2026-08-28→08-29 的 Saturn（defillamaId 由 "7646" 變 null）與
       2026-09-02→09-03 的 Ankr（defillamaId 由 null 變 "278"）。上游的
       defillamaId 本身會出現與消失（實測 58.4% 缺失、且逐日會變動），
       「有值用 id、沒值用 name」等於讓主鍵跟著這個不穩定欄位一起跳動。
    2. 該做法會讓 crypto_project_liveness 已公開的 events.jsonl 主鍵語意斷成兩段
       （同一個歷史事件在舊資料是 name 鍵、新資料是 id 鍵），而 main() 每次執行都會
       重放全部相鄰快照配對、以 (date,source,group,key,event) 做冪等判斷——換主鍵會
       讓既有 22 筆歷史事件的 key 全部對不上 seen，導致一次性大量重複事件被追加。
    3. 本輪採用的抵銷層對主鍵零改動，因此上述兩個風險都不存在（實測：除了
       09-05→09-06 那 2 組改名被抵銷之外，其餘 9 組相鄰配對的 removed／added
       集合逐筆完全相同）。

  本輪只動 4 處（其餘一律未修改）：
    1. GROUP_SOURCES["crypto_project_liveness"]["groups"]["_hacks"] 新增
       stable_id_fields 設定（其他來源沒有這個鍵，行為完全不變）。
    2. 新增 stable_identity()／build_stable_id_index()／reconcile_renames()
       三個純函式（新程式碼，不被既有路徑呼叫）。
    3. compare_group() 在回傳前呼叫 reconcile_renames()，並在回傳 dict 多一個
       renamed_pairs 欄位（未設定 stable_id_fields 的子集合恆為空 list，
       removed_keys／added_keys 一個位元都不變）。
    4. render_group_source_report()／process_group_source_pair() 各新增一段
       「只有 renamed_pairs 非空時才會產生輸出」的分支。

  本輪不修改：dedup()／judge()／build_group_events()／status_changes_for_group()／
  completeness()／completeness_group()／extract_group_items()／compare_pair()／
  process_pair()／render_report()／write_events()／load_seen()／update_index()／
  record_gate_fail()／write_alert_block()／write_alert_block_group()／main()
  一個字元都沒有改；events.jsonl 的 schema 與事件型別集合
  （LISTED／DELISTED／REAPPEARED／STATUS_CHANGED）完全不變，本輪**沒有**新增
  第 5 種事件型別（是否要新增 RENAMED，列為待裁示事項，見報告 §7）。

  本輪同樣硬性限制：只在 VPS /tmp/0907-B-rename-key/ 驗證，正式目錄一個字元都沒有改，
  未 git commit、未安裝套件。

第四階段修正（本輪，2026-09-07）：修掉 x402_bazaar 的「恆真式」完整性守門。
完整推導、上游親驗證據、沙盒驗證輸出見本機 docs/0907-D-x402-gate-report.md。

【被修正的既有錯誤敘述】上方第二階段區塊寫「完整性守門新增 range_check 方式
（第一階段只有 total_match，**因為 x402_bazaar 有 data.total 自報欄位**）」——
這句話的括號內容**是錯的**，本輪推翻：data.total 不是來源自報欄位，是
track-crypto/adapters/x402_bazaar.py 自己寫的 len(items)。因此舊 completeness()
的 `total != n` 判斷式恆為假，守門恆為真，對分頁截斷零防護力
（實證：13 份歷史快照全部 total == len(items)，見 docs/0907-events-audit-0904-0907.md §8.1；
本機 docs/gate-alert-and-reaudit.md §4.6.1 的同一錯誤敘述已一併更正）。
上方第二階段區塊的歷史敘述保留原樣不改寫（那是當時的紀錄），以本段為準。

【本輪查證】2026-09-07 親打上游 Coinbase CDP API：回應頂層確實有
pagination:{limit,offset,total}，total 是真正的上游自報目錄總數。原 adapter 讀了
它只當迴圈終止條件、沒有保存。已改為保存成 data.reported_total 並加上
data.truncated 自報旗標（adapter PARSER_VERSION 1 -> 2）。

【本輪修改範圍】只動三處，且都在 x402_bazaar（SOURCES）這條路徑上：
  1. SOURCES["x402_bazaar"]：刪除 total_field，新增 completeness／
     reported_total_field／truncated_field／tolerance_pct／tolerance_abs_floor／
     legacy_range 六個鍵。
  2. completeness()：整支改寫（新增 reported_total_match 與舊快照相容的
     legacy_range_check 兩條路徑），舊的 "total_match" reason 字串一併移除。
  3. compare_pair() 回傳字典新增 ok_old／ok_new 兩個鍵（純加法），
     render_report()／write_alert_block() 內原本用
     `reason == "total_match"` 字串字面值回推守門結果的 4 處改讀這兩個布林值
     （不改任何判定邏輯，只修正一個會在 reason 措辭改變後誤印的顯示瑕疵）。

【本輪不修改】completeness_group()／compare_group()／compare_pair() 的判定邏輯／
judge()／dedup()／build_group_events()／render_group_source_report()／
write_alert_block_group()／process_pair()／process_group_source_pair()／
record_gate_fail()／load_gate_fail_seen()／snapshots()／load()／update_index()／
write_events()／main() 一個字元都沒有改；GROUP_SOURCES 全部 22 個子集合的設定
一個字元都沒有改（本輪只動 SOURCES 這一個表）。

【相容性】2026-09-07 之前的 13 份既有快照沒有 reported_total 欄位，會走
legacy_range_check 分支並全部通過（實測 len(items) 落在 [14255,16592]，區間為
[12829,18252]），events.jsonl 對歷史資料重放後**逐位元組不變**（沙盒實測，
見報告 §7）。changes/x402_bazaar/*.md 的「完整性守門」兩列文字會改變
（reason 字串換了），這是預期中的顯示差異，不影響任何事件判定。

第五階段（2026-09-08，任務 0908-1）：新增第 5 種事件型別 RENAMED。
完整推導與驗證輸出見本機 docs/0908-1-renamed-event-report.md。

【被本輪推翻的既有敘述】上方第四階段任務 B 區塊寫「本輪**沒有**新增第 5 種事件型別
（是否要新增 RENAMED，列為待裁示事項）」——該待裁示事項已由使用者於 2026-09-08
裁示「**要看到改名**」。那段歷史敘述保留原樣不改寫（那是當時的紀錄），以本段為準。

【為什麼要加】任務 B 的抵銷層讓改名不再被誤判成 DELISTED＋LISTED，但代價是
events.jsonl 對這件事**完全沉默**：只讀事件流的下游會看到一個主鍵無聲消失、
另一個主鍵無聲出現，必須改去讀人類可讀日報才知道發生了改名
（docs/0907-B-rename-key-report.md §9.4 第 1 項自陳的壞處）。本輪把改名升格為
正式事件，讓事件流自己講得清楚。

【事件型別集合的變更】events.jsonl 的 event 欄位由 4 值封閉集合
  {LISTED, DELISTED, REAPPEARED, STATUS_CHANGED}
擴充為 5 值：
  {LISTED, DELISTED, REAPPEARED, STATUS_CHANGED, RENAMED}
這是**已公開介面（CC BY 4.0）的變更**，屬於「只增不減」的相容擴充：既有 4 種型別的
語意、欄位、產生條件一個字元都沒有改，既有事件行一行都沒有動。只按 event 值過濾的
下游不會壞（拿不到 RENAMED 就等於維持 B 的行為）；把 event 當封閉列舉、對未知值
丟例外的下游會需要更新——這一點已在 track-crypto/README.md 與 docs/operations.md
的 schema 說明中明文公告。

【RENAMED 的欄位】除既有 7 個核心欄位外另有 4 個具名欄位，設計目標是讓一筆事件
就能回答「什麼東西／從什麼名字改成什麼名字／依據哪個穩定 id 判定／哪一天」：
  date              判定發生日（＝當日快照日期，與其他事件型別一致）
  source / group    來源與子集合（與其他事件型別一致）
  key               **舊主鍵**（從當日快照消失的那一個），與 from_key 恆等
  event             固定字串 "RENAMED"
  from              舊項目的人類可讀描述（desc_field，本來源即改名前的 name）
  to                新項目的人類可讀描述（＝改名後的 name）
  from_key          舊主鍵（與 key 相同，具名冗餘，見 build_group_events() 內註解）
  to_key            新主鍵（改名後的那一個）
  stable_id         判定依據的穩定識別字串（例如 "249\x1f1773273600"）
  stable_id_fields  組成該穩定識別的欄位名稱清單（例如 ["defillamaId", "date"]）

  key 取舊主鍵而不是新主鍵的理由見 build_group_events() 內的長註解（摘要：舊主鍵
  才是「消失」的那一個，追蹤它的下游若查不到事件就會誤判為靜默遺失）。

【本輪只動 6 處（其餘一律未修改）】
  1. build_group_events()：在 last_delisted 更新之後、STATUS_CHANGED 區塊之前，
     新增一個「逐筆把 renamed_pairs 轉成 RENAMED 事件」的迴圈（純加法；
     renamed_pairs 為空的 12 個子集合迴圈一次都不會跑）。
  2. render_group_source_report()：表格那一列與「🔄 上游改名」小節的措辭由
     「未寫入事件流」改為「事件型別 RENAMED」（只改文字，不改判定）。
  3. render_group_source_report() 檔尾那一句事實聲明補上「被上游改名」。
  4. process_group_source_pair()：索引列的 total_renamed 統計口徑由
     judged=="NORMAL" 對齊成 to_events（與同一段其他 4 個 total_* 一致）。
  5. 本檔頭這段說明。
  6. （配套，另一個檔案）scripts/selftest.py 新增 4 條檢查與 4 個 mutation。

【本輪不修改】reconcile_renames()／stable_identity()／build_stable_id_index()／
compare_group()／dedup()／judge()／status_changes_for_group()／status_filter_hit()／
completeness()／completeness_group()／extract_group_items()／compare_pair()／
process_pair()／render_report()／write_events()／load_seen()／update_index()／
annotate_flaps()／flap_marks()／record_gate_fail()／record_status_filtered()／
write_alert_block()／write_alert_block_group()／write_quarantine()／main()
一個字元都沒有改。改名的**判定邏輯**（誰跟誰是同一個東西）完全沿用任務 B，
本輪只負責把已經判定出來的結果落地成事件。

【冪等性】RENAMED 沿用既有的 write_events() 去重鍵 (date, source, group, key, event)，
同一組改名重跑不會重複寫入。annotate_flaps() 只改寫 event=="STATUS_CHANGED" 的行，
RENAMED 的行走「原樣保留」路徑，一個位元組都不會被動到。
部署後**第一次**執行會為 2026-09-06 的 Stake DAO 改名補寫 2 筆 RENAMED
（這是預期中的一次性追加），第二次起 events.jsonl 逐位元組不變。

──────────────────────────────────────────────────────────────────────────
第五階段（2026-09-08）：修掉 GROUP_SOURCES 剩下的 3 個「恆真式」完整性守門
本機規格／報告：docs/0908-4-tautological-gates-report.md（任務 0908-4）
──────────────────────────────────────────────────────────────────────────
【緣由】任務 D（第四階段）修掉 SOURCES["x402_bazaar"] 的恆真式守門時，附帶掃描
發現宣告 total_match 的 6 個來源中還有 3 個是同一個毛病——自報欄位就是 adapter
自己算的 len(...)，判斷式恆為假、守門恆為真。本輪逐一親打上游確認「到底有沒有
真總數」後修掉：

  來源                        上游有真總數嗎（本輪親驗）              本輪修法
  ofac_sanctions_crypto      **有**。OFAC 另外發布的 SDN.XML 檔頭    改 reported_total_match
                             有 <publshInformation><Record_Count>，  （adapter 保存上游
                             2026-09-08 實測 Record_Count(19329)     Record_Count；容忍度
                             ＝ sdn.csv 資料列數(19329)＝ XML        取 0＝嚴格相等，
                             sdnEntry 數(19329)，uid 集合差集皆 0    理由見該來源設定註解）
  openrouter_providers       **沒有**。回應頂層只有 data 一個鍵，    改 range_check
                             limit/offset/page/per_page 全被忽略      [92, 117]
  crypto_project_liveness    **沒有**。回傳裸 JSON 陣列，無任何       改 range_check
                             中繼欄位；官方文件也寫 "Returns:         [1115, 1383]
                             array of {...}"

【本輪只動 4 處】
  1. GROUP_SOURCES 三個子集合的完整性設定（ofac_sanctions_crypto._items／
     openrouter_providers._providers／crypto_project_liveness._hacks），
     **一律刪掉 total_fields**，不留假的保護感。
  2. completeness_group() 新增 reported_total_match 分支（純加法，
     既有 total_match／range_check／tolerant_total_match 三個分支
     一個字元都沒有改）。
  3. 同函式 docstring 補上新方法的說明。
  4. 本說明區塊。

【本輪不修改】compare_group()／compare_pair()／completeness()／judge()／dedup()／
extract_group_items()／build_group_events()／status_changes_for_group()／
reconcile_renames()（第四階段任務 B 新增）／render_group_source_report()／
write_alert_block_group()／process_pair()／process_group_source_pair()／
record_gate_fail()／snapshots()／load()／update_index()／write_events()／
breaker_release_check()／main() 一個字元都沒有改；SOURCES（x402_bazaar）整張表
沒有動；GROUP_SOURCES 其餘 19 個子集合的設定沒有動。

【相容性】三個來源既有的 12 份快照（2026-08-28～09-08）全部通過新守門：
  - ofac：沒有 reported_total 欄位 -> 走 legacy_range_check[17387,21262]，
    實測 n 落在 19319～19329，全部通過（adapter PARSER_VERSION 1→2 之後
    才會開始有 reported_total）。
  - openrouter_providers：n 落在 103～106，區間 [92,117] 全部通過。
  - crypto_project_liveness：n 落在 1239～1257，區間 [1115,1383] 全部通過。
歷史重放 events.jsonl 逐位元組不變（沙盒實測，見報告 §5）。
changes/<source>/*.md 內「完整性守門」列的 reason 文字會改變（total_match ->
range_check[...]／legacy_range_check[...]），屬預期中的顯示差異。

【誠實揭露】range_check 是**弱守門**：它擋得住「整批塌陷／結構改變」，擋不住
「少了幾十筆」。這兩個來源都是「單次請求取回整份清單、沒有分頁迴圈」，本來就
沒有分頁截斷這個失效模式（HTTP 讀取中斷會直接拋例外、記為抓取失敗，不會產生
半份快照），真正的主力防線是熔斷（breaker_pct=1.0%）。換掉恆真式的價值在於
**不再宣稱一個不存在的保護**，而不是換到一個同樣強的保護。
"""
import os
import sys
import gzip
import json
import glob
from datetime import datetime, timezone

# --------------------------------------------------------------------------
# 路徑：一律用 __file__ 動態推算，不寫死。
#   HERE          = .../track-crypto/scripts   （本檔案所在目錄）
#   TRACK_CRYPTO  = .../track-crypto            （來源資料與 events.jsonl 在這裡）
#   REPO          = REPO 根目錄                  （changes/、CHANGES.md 在這裡，與軌二共用；ALERT-DELIST.md 也在這裡但只有本程式讀寫）
# --------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
TRACK_CRYPTO = os.path.dirname(HERE)
REPO = os.path.dirname(TRACK_CRYPTO)

CHANGES = os.path.join(REPO, "changes")
INDEX = os.path.join(REPO, "CHANGES.md")
ALERT_DELIST = os.path.join(REPO, "ALERT-DELIST.md")

# GATE_FAIL 事實紀錄檔（2026-09-04 新增，specs/SPEC-gate-dedup.md，設計理由見本機
# docs/gate-dedup-report.md）：完整性守門不通過時，除了現有的 changes/<source>/
# YYYY-MM-DD.md 人類可讀紀錄與 CHANGES.md 索引列之外，另外寫一筆結構化事實到這裡，
# 供 scripts/healthcheck.py 的 check_delist_gate_fail() 讀取後決定要不要產生
# ALERT-DELISTGATE.md（比照 scripts/cex_events.py 的 gate_skips.jsonl／
# scripts/healthcheck.py 的 check_cex_gate_skips() 同構設計，見 record_gate_fail()
# docstring）。放在 track-crypto/data/_gate_fail/ 而不是 REPO 根目錄：本檔案涵蓋
# SOURCES／GROUP_SOURCES 全部來源（跨來源共用，不屬於任何單一 <source> 自己的
# data/<source>/ 目錄），比照 track-crypto/data/_manifest/（snap_crypto.py 寫的
# 跨來源完整性資料）已有的「底線開頭＝非單一來源專屬」命名慣例；檔名沿用
# gate_skips.jsonl，與 cex_events.py 那份保持一致，方便日後維護者辨識用途。
GATE_FAIL_LOG = os.path.join(TRACK_CRYPTO, "data", "_gate_fail", "gate_skips.jsonl")
# 檔案大小防護的提示門檻（比照 scripts/cex_events.py 的 GATE_LOG_SIZE_HINT_LINES，
# 同一設計理由：go-forward 去重已把成長速度限制在「每個 (date,source,group,reason)
# 最多一行」，正常運作下極罕見觸發）。
GATE_FAIL_LOG_SIZE_HINT_LINES = 500

# --------------------------------------------------------------------------
# 第四階段（2026-09-07，熔斷語意統一）新增的兩個模組層級常數。
# --------------------------------------------------------------------------
# 隔離檔檔名（與 events.jsonl 同目錄，逐來源一份）。語意：「這一組轉換算出來的事件
# 事實，因為資料可信度不足（GATE_FAIL）或疑似分頁截斷（BREAKER 且截斷指紋成立）
# 而不進 events.jsonl，但**完整保留**，供人工複核後決定是否提升」。
# 只追加、不覆寫、不刪減，去重鍵與 events.jsonl 相同的五元組
# (date, source, group, key, event)，見 write_quarantine()。
QUARANTINE_BASENAME = "events_quarantine.jsonl"

# 分頁截斷指紋門檻：removal_tail_metrics() 算出的 tail_cover
# （＝「前一日清單順序中，結尾連續且全部被移除的區塊長度」÷「本次移除總筆數」）
# 大於等於本值時，判定為「疑似分頁截斷」，該組轉換的事件改寫入隔離檔而不進 events.jsonl。
#
# 實測校準（2026-09-07，全部是本機真實歷史快照重算，非估計；完整輸出見本機
# docs/0907-C-breaker-semantics-report.md §4.2）：
#   正類（真實截斷）agent_virtuals 兩個已知的時間預算截斷日：
#       2026-08-28→08-29 移除 4500/37500，tail_cover = 1.0000
#       2026-08-30→08-31 移除 5978/41978，tail_cover = 1.0000
#   負類（真實變動）x402_bazaar 全部 12 組相鄰日轉換：tail_cover 介於 0.0000～0.0114
#       （含本次要處理的 09-06→09-07 熔斷日，tail_cover = 0.0000）
#   合成正類 x402_bazaar 把 09-07 快照截到前 1／2 頁：0.7366／0.7867
# 門檻取 0.50，落在實測正類最小值（0.7366）與負類最大值（0.0114）中間，
# 兩側各留一個數量級以上的餘裕。樣本數少（正類 2 真實 + 2 合成），
# 應隨資料累積重新校準，沿用 cex_events.py 熔斷門檻註解的同一立場。
#
# 已知盲點（誠實揭露，不是設計目標）：本指紋只抓得到「移除項目確實排在前一日清單尾端」
# 的截斷。x402_bazaar 的 API 排序逐日不穩定，把 09-07 快照截到前 15 頁
# （移除率 11.9%）時 tail_cover 仍是 0.0，指紋不會觸發。見檔頭第四階段「誠實揭露」。
BREAKER_TAIL_COVER_MAX = 0.50

# GATE_FAIL（完整性守門不通過）要不要也寫進隔離檔。**預設 False（不寫）**。
#
# 為什麼預設關閉（實測數字，不是推論）：2026-09-07 對全部歷史快照重放，若開啟這個
# 選項，光是 agent_virtuals 2026-08-29～09-01 那 4 個已知的時間預算截斷日就會產生
# **65,788 筆**隔離紀錄（08-29 DELISTED 4,500／08-30 LISTED 8,978／08-31 DELISTED
# 5,978／09-01 LISTED 46,332），約 13 MB，而且會進 git（agent_virtuals 不在
# .gitignore 排除的 4 個大型來源之列）。
#
# 為什麼這些紀錄的價值低（語意論證）：完整性守門不通過＝**這份快照本身已知不可信**
# （agent_virtuals 那 4 天的 truncated 旗標明確是 True），由它推出來的「消失／新增」
# 幾乎必然是截斷假象，不是待複核的事實。相對地，熔斷放行檢查沒過的情況是
# 「守門通過（資料可信）但規模可疑」，那才是真正需要保留待複核的灰色地帶。
# 兩者不同性質，所以預設值不同：BREAKER 一律隔離保存，GATE_FAIL 預設只留
# _gate_fail/gate_skips.jsonl 的守門紀錄（既有行為，未改變）。
#
# 需要時把這個值改成 True 即可，程式路徑完全相同、冪等、可重跑。
QUARANTINE_GATE_FAIL = False

EMDASH = "\u2014"  # 「改寫」欄固定值，SPEC 指定用 em dash，不是連字號

# --------------------------------------------------------------------------
# 白名單（預設 deny）：新增來源必須明確加入這個表才會被偵測。
# window="full"：全量掛牌，不套用滾動視窗語意（依設計文件 2.3；x402_bazaar 是
#                分頁抓完的全量清單，不是「最新 N 筆」的排行榜／滾動視窗）。
# breaker_pct   ：熔斷門檻（removed 率，百分比）。x402_bazaar 專屬 5%（父代理已裁示）。
#                 不套用其餘來源「max(20, 前一日筆數 × 2%)」的絕對筆數下限，因為
#                 第一階段只有這一個來源，且其規模（萬筆級）遠大於 20，加上下限
#                 對行為沒有任何實際影響，SPEC 也只要求單純的百分比門檻。
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# 2026-09-07 修正（恆真式守門，見本機 docs/0907-D-x402-gate-report.md）：
# 原設定 "total_field": "total" 搭配 completeness() 的 total_match，被
# docs/0907-events-audit-0904-0907.md §8.1 查出是**恆真式**——adapter 直接寫
# "total": len(items)，自報欄位與被檢查對象是同一個數字，對分頁截斷零防護力。
# 本輪親打上游 API 確認回應含 pagination.total（真正的自報總數），adapter 已改為
# 保存為 data.reported_total 並自報 data.truncated，本表改為指向這兩個新欄位，
# **並刪除 total_field**（不留一個假的保護感）。
#   completeness ： "reported_total_match"（見 completeness() 新實作）
#   tolerance_pct／tolerance_abs_floor：容忍度門檻 = max(abs_floor, pct% × reported_total)。
#     為什麼需要容忍度而不是嚴格相等：上游目錄是活的，一次全量分頁約 45 秒，
#     期間清單本身會變動。2026-09-07 兩次全量實測：第一次 reported_total=14698、
#     len(items)=14698（差 0）；第二次 reported_total=14699、len(items)=14698（差 1）。
#     **嚴格相等在第二次就會誤判 GATE_FAIL**，所以必須留容忍度。
#     pct=0.1%（現行規模 n≈15,000 時約 15 筆）的推導：
#       上界（不可誤殺）：實測最大落差 1 筆 -> 約 15 倍安全邊界；
#         另以歷史最劇烈單日異動量推估理論上界（09-06→09-07 移除 1399＋新增 387
#         ＝1786 筆/日，換算 60 秒視窗約 1.24 筆）-> 約 12 倍安全邊界。
#       下界（要抓得到）：單一分頁遺漏 = LIMIT = 1000 筆 = 現行規模的 6.8%，
#         是門檻的 68 倍，兩者相差近兩個數量級，不是精確調校依賴症。
#       對照：5% 熔斷門檻比本門檻鬆 50 倍，所以真的發生截斷時本守門會先攔下來。
#     abs_floor=5：比照本檔 GROUP_SOURCES 既有的 max(abs_floor, pct×n) 房規，
#       避免 n 極小時百分比門檻退化成 0。
#     樣本數揭露：容忍度目前只有 **2 次**全量實測可校準（本輪親抓），樣本很薄；
#       reported_total 隨每日快照累積後應重新校準（沿用第二階段 range_check
#       註解的同一立場）。
#   legacy_range：2026-09-07 之前的既有快照沒有 reported_total 欄位（adapter 當時
#     沒保存），若直接判 fail 會讓全部歷史相鄰配對變成 GATE_FAIL、等於毀掉重放。
#     舊快照改走 range_check（本檔 GROUP_SOURCES 既有方法論：實測 min／max 各加
#     10% 邊界）。13 份既有快照 len(items) 實測 min=14255（2026-08-30）、
#     max=16592（2026-09-06），floor(14255×0.9)=12829、ceil(16592×1.1)=18252。
#     **誠實揭露**：range_check 對本來源的鑑別力比 reported_total_match 弱得多
#     （單一分頁遺漏 1000 筆後 n 仍落在區間內），它只是「比恆真式好」的舊資料
#     相容分支，不是等價替代；go-forward 的真正防線是 reported_total_match。
# --------------------------------------------------------------------------
SOURCES = {
    "x402_bazaar": {
        "label": "x402 Bazaar 全量掛牌（Coinbase CDP x402 discovery API）",
        "key_field": "resource",
        "completeness": "reported_total_match",
        "reported_total_field": "reported_total",
        "truncated_field": "truncated",
        "tolerance_pct": 0.1,
        "tolerance_abs_floor": 5,
        "legacy_range": (12829, 18252),
        "window": "full",
        "breaker_pct": 5.0,
    },
}


# ============================================================================
# 第二階段新增（2026-09-02，接續第一階段 x402_bazaar，見 SPEC-detect-phase2.md）：
# 甲組其餘 8 個來源 —— cex_currency_status／cex_earn_apr／cex_symbols_ext／
# cex_withdrawal_limits／ofac_sanctions_crypto／openrouter_models／
# openrouter_providers／payment_protocol_repos。
# （cex_symbols 已由既有 scripts/cex_events.py 處理，依 SPEC 指示不重複納入本白名單，
#  本輪未修改、未併入、未令 cex_events.py 退役，超出本次派工範圍。）
#
# 設計原則（完整理由、逐來源實測數字、四項驗收見本機
# docs/detect-phase2-report.md，本檔案只放程式碼與必要的簡短依據）：
#   1. 【對第一階段零風險】完全不修改上面第一階段的 SOURCES／completeness()／
#      dedup()／compare_pair()／judge()／render_report()／process_pair()／
#      write_alert_block() 八個函式與設定表一個字元。dedup()、judge() 是既有的
#      通用工具函式（不含 x402_bazaar 專屬邏輯），本階段直接原樣重用；
#      write_alert_block() 因檔頭文字寫死「x402_bazaar」字樣，不適合直接重用在
#      其他來源的告警（會產生誤導性檔頭），故另外新增 write_alert_block_group()，
#      與 write_alert_block() 各自獨立、互不呼叫，x402_bazaar 的呼叫路徑完全不變。
#      main() 對兩組來源分成兩個獨立迴圈依序處理，第一階段迴圈原封不動放在最前面。
#   2. 【預設 deny】GROUP_SOURCES 是獨立白名單，比照 SOURCES：未列入的來源一律不判定。
#   3. 【資料形狀一般化】第一階段假設「單一來源＝單一清單」；本階段來源多半是
#      「一個來源、多個子集合」（例如 cex_currency_status 有 gate／coinbase 兩個
#      子集合，各自獨立的清單路徑、主鍵、完整性、熔斷門檻）。子集合對應
#      events.jsonl 既有的 "group" 欄位（與 cex_events.py 的用法一致），
#      "source" 欄位固定是 GROUP_SOURCES 的 key（例如 "cex_currency_status"），
#      "group" 欄位是子集合名稱（例如 "gate"）；只有一個子集合的來源，
#      子集合名稱以底線開頭（例如 "_items"），語意是「這個來源沒有再分組，
#      _items 只是佔位」，不對外呈現在人類可讀報告的子集合標題（見
#      render_group_source_report()）。
#   4. 【完整性檢查兩種方式，都在 completeness_group() 實作】
#      （第三階段追加 tolerant_total_match、第五階段追加 reported_total_match，
#        故現行共四種；本段落保留原文，以現行 completeness_group() docstring 為準）
#      - total_match：來源自報 count／total_count 等欄位，逐一比對
#        欄位值 == 該子集合原始筆數（去重前），全部存在且相符才算通過；
#        可選 require_empty（例如 payment_protocol_repos 的 errors 欄位）
#        額外要求指定欄位為空，否則視為部分抓取失敗（見該來源 GROUP_SOURCES 設定
#        的註解說明，此為讀 adapter 原始碼 MIN_SUCCESS=2 後新增的防線）。
#      - range_check：沒有自報總數欄位時的替代方案（SPEC 明文允許），
#        用 08-28～09-02 六天實測 min/max 各加 10% 安全邊界訂出固定區間，
#        原始筆數落在區間外視為不完整。標示為本輪工程判斷（推論），非官方保證，
#        區間應隨資料持續累積重新校準（沿用 cex_events.py 熔斷門檻註解的同一立場）。
#   5. 【熔斷公式與 cex_events.py 同構】
#      breaker = removed_count > max(abs_floor, breaker_pct/100 × 前日去重後筆數)，
#      逐來源／逐子集合的 breaker_pct、abs_floor 依實測資料訂定（非全部沿用
#      x402_bazaar 的 5%），推導方法與具體數字見 docs/detect-phase2-report.md §2。
#   6. 【旗標優先，新增 STATUS_CHANGED 事件型別】對於原生帶狀態旗標的子集合
#      （例如 gate 的 delisted／trade_disabled／withdraw_disabled，coinbase 的
#      status，openrouter_models 的 expiration_date），只做集合差會嚴重低估
#      下架語意（本輪實測：cex_currency_status.gate 41.7%、
#      cex_symbols_ext.coinbase 37.6%、cex_currency_status.coinbase 16.9%
#      的項目旗標已是「已下架」但主鍵從未離開清單），故一併記錄旗標變化。
#      STATUS_CHANGED 的 "from"/"to" 各自是 {欄位名: 值} 的字典（只列有變化的
#      欄位），不是每個欄位各開一筆事件——events.jsonl 既有 7 欄結構沒有獨立的
#      「欄位名稱」欄，用字典可同時保留欄位名與新舊值，且不新增/更改欄位結構。
#      只在 judged=="NORMAL" 時計算與寫入，閘門條件與 LISTED／DELISTED／
#      REAPPEARED 完全一致。
#   7. 【零觀點鐵律】人類可讀輸出沿用第一階段措辭：「自清單消失」「新增」
#      「重新出現」「狀態變化」，不用「下架」；只陳述事實，不做原因推測。
# ============================================================================

GROUP_SOURCES = {
    "cex_currency_status": {
        "label": "交易所幣種層級狀態旗標（Gate／Coinbase Exchange）",
        "groups": {
            "gate": {
                "path": ("gate",), "shape": "list", "key_field": "currency",
                "desc_field": "name",
                "completeness": "range_check", "range": (4938, 6057),
                "status_fields": ("delisted", "trade_disabled", "withdraw_disabled"),
                # 語意過濾規則（2026-09-07 新增；規則語意、值域盤點、逐條證據見下方
                # 「狀態欄位語意過濾（做法 4）」區塊與本機 docs/0907-E-gate-flap-report.md §3）：
                # 已下架（delisted=True，且兩側都是 True）的幣種，withdraw_disabled 只是
                # 下架的下游結果（下架幣提幣本來就該是關閉狀態），不具獨立資訊價值，
                # 不產生 STATUS_CHANGED；被抑制的每一筆都寫進 STATUS_FILTER_LOG 供稽核。
                "status_filters": (
                    {"field": "withdraw_disabled", "when_both": {"delisted": True},
                     "reason": "delisted_dominates_withdraw_disabled"},
                ),
                "breaker_pct": 1.0, "abs_floor": 5,
            },
            "coinbase": {
                "path": ("coinbase",), "shape": "list", "key_field": "id",
                "desc_field": "name",
                "completeness": "range_check", "range": (453, 556),
                "status_fields": ("status",),
                "breaker_pct": 1.0, "abs_floor": 5,
            },
        },
    },
    "cex_earn_apr": {
        "label": "CEX 理財年化率（Bybit 活期理財／OKX 借貸利率總覽）",
        "groups": {
            "bybit": {
                "path": ("bybit",), "shape": "list", "key_field": "productId",
                "desc_field": "coin",
                "completeness": "range_check", "range": (206, 263),
                "status_fields": ("status",),
                "breaker_pct": 1.0, "abs_floor": 5,
            },
            "okx": {
                "path": ("okx",), "shape": "list", "key_field": "ccy",
                "desc_field": None,
                "completeness": "range_check", "range": (151, 185),
                "status_fields": (),
                "breaker_pct": 1.0, "abs_floor": 5,
            },
        },
    },
    "cex_symbols_ext": {
        "label": "擴充 3 家交易所交易對清單（Kraken／Coinbase Exchange／Upbit）",
        "groups": {
            "coinbase": {
                "path": ("coinbase",), "shape": "list", "key_field": "id",
                "desc_field": "display_name",
                "completeness": "range_check", "range": (752, 921),
                "status_fields": ("status",),
                "breaker_pct": 1.0, "abs_floor": 5,
            },
            "upbit": {
                "path": ("upbit",), "shape": "list", "key_field": "market",
                "desc_field": "english_name",
                "completeness": "range_check", "range": (762, 934),
                "status_fields": (),
                "breaker_pct": 1.0, "abs_floor": 5,
            },
            "kraken": {
                # data.kraken 是 {交易對代碼: 交易對物件} 的 dict-of-dict（非 list-of-dict）；
                # dict 鍵本身即主鍵，唯一性由 JSON object 結構保證，key_field 留 None
                # （extract_group_items() 依 shape=="dict" 走另一條路徑，不查 key_field）。
                # 設計文件盤點表未列 kraken 的主鍵欄位與筆數，本輪自行判定並記錄於報告 §2.3。
                "path": ("kraken",), "shape": "dict", "key_field": None,
                "desc_field": "wsname",
                "completeness": "range_check", "range": (1293, 1585),
                "status_fields": ("status",),
                "breaker_pct": 1.0, "abs_floor": 5,
            },
        },
    },
    "cex_withdrawal_limits": {
        "label": "KuCoin 幣種提幣費與最低提幣額",
        "groups": {
            "_top": {
                # data 頂層即 list，沒有巢狀 key，path=() 代表「不下鑽，直接用 data 本身」。
                "path": (), "shape": "list", "key_field": "currency",
                "desc_field": "fullName",
                "completeness": "range_check", "range": (2019, 2470),
                "status_fields": (),
                "breaker_pct": 1.0, "abs_floor": 5,
            },
        },
    },
    "ofac_sanctions_crypto": {
        "label": "OFAC SDN 制裁名單（美國財政部），含加密貨幣地址欄位",
        "groups": {
            "_items": {
                "path": ("items",), "shape": "list", "key_field": "uid",
                "desc_field": "sdn_name",
                # 第五階段修正（2026-09-08，見本檔頭「第五階段」區塊與
                # 本機 docs/0908-4-tautological-gates-report.md §3.1）：
                # 原設定 "total_match" + total_fields=("count",) 是**恆真式**
                # ——adapter 直接寫 "count": len(items)，自報值與被檢查對象是同一個
                # 數字。本輪親打上游確認 OFAC 另外發布的 SDN.XML 檔頭含
                # <publshInformation><Record_Count>，且 2026-09-08 實測
                # Record_Count(19329) == sdn.csv 資料列數(19329) == XML sdnEntry 數(19329)、
                # uid 集合完全相同（差集兩邊皆 0）。adapter 已改為用 HTTP Range 只取
                # XML 前 4KB 解析出這個數字並存成 data.reported_total，本表改為比對它，
                # **並刪除 total_fields**（不留一個假的保護感）。
                "completeness": "reported_total_match",
                "reported_total_field": "reported_total",
                # 容忍度門檻 = max(tolerance_abs_floor, tolerance_pct% × reported_total)
                # 本來源取 **max(0, 0%) = 0（嚴格相等）**，公式本身沿用 completeness()
                # 對 x402_bazaar 的同一組機制，但**數值刻意與它不同**，理由如下：
                #   x402_bazaar 是「活的分頁目錄」——一次全量分頁約 45 秒，期間目錄本身
                #   會增減，上游 pagination.total 與實得筆數天生會差 0~1 筆，所以必須留
                #   容忍度（任務 D §4.3）。
                #   本來源不是那種東西：sdn.csv 與 SDN.XML 是**同一次發布的兩個檔案**
                #   （每日快照抓的是靜態檔，不是即時查詢），同一版本內兩者筆數必然相等。
                #   2026-09-08 實測：Record_Count 19,329 ＝ CSV 資料列數 19,329
                #   ＝ XML sdnEntry 19,329，且 uid 集合逐一相同（差集皆 0）；
                #   另用上游 delta 檔（publication 968／969）對帳，19321+5+3=19329 閉合。
                # 為什麼不留 max(5, 0.1%)≈19 筆的容忍度（本輪實測後否決）：
                #   OFAC 單次發布的實際變動量可達 +65 列（2026-08-24, publication 964）、
                #   +47 列（08-20），**遠大於 19**。留 19 筆容忍度既擋不住真正的換版競態
                #   （那種情形落差會是幾十筆、照樣 fail），又會放過「CSV 真的少了 19 筆」
                #   這種小規模缺損 —— 兩頭都不討好。改用嚴格相等，語意乾淨：
                #   「兩個檔案對不起來就是不可信，不判定」。
                # 誤報風險評估：只有「CSV 與 XML 兩次請求之間 OFAC 正好換版」才會誤判。
                #   實測 2026-08-18~09-04 共 7 次發布（平均 2.6 天一次，發布時刻約
                #   UTC 14:01，同批各檔 Last-Modified 只差 7 秒），本專案排程在 UTC 00:00
                #   （相距約 10 小時），兩次請求相隔約 10 秒
                #   -> 【推論】約 0.39 次/日 × (10s/86400s) ≈ 4.5e-5，量級是「數十年一次」。
                #   真的發生時是 GATE_FAIL（當日不判定＋寫 gate_skips.jsonl），
                #   不是資料遺失，隔日即自動恢復。
                "tolerance_pct": 0.0,
                "tolerance_abs_floor": 0,
                # legacy_range：adapter 升版（PARSER_VERSION 1→2）之前的既有快照沒有
                # reported_total 欄位，退回區間檢查，否則全部歷史相鄰配對會變成
                # GATE_FAIL、毀掉重放。12 份既有快照（2026-08-28～09-08）實測
                # min=19319、max=19329 -> floor(19319×0.9)=17387、ceil(19329×1.1)=21262。
                # **誠實揭露**：區間法鑑別力遠弱於 reported_total_match（少 1,000 筆
                # 仍落在區間內），只是舊資料相容分支，不是等價替代。
                "legacy_range": (17387, 21262),
                "status_fields": (),
                "breaker_pct": 1.0, "abs_floor": 5,
            },
        },
    },
    "openrouter_models": {
        "label": "OpenRouter 全模型清單與定價",
        "groups": {
            "_models": {
                "path": ("models",), "shape": "list", "key_field": "id",
                "desc_field": "name",
                # count 與 total_count 兩個自報欄位皆須相符才算完整，比單一欄位更嚴格
                # （本輪對本來源的加強，見報告 §2.6）。
                "completeness": "total_match", "total_fields": ("count", "total_count"),
                "status_fields": ("expiration_date",),
                # 熔斷門檻專屬 3.0%（非 1.0% 底線）：09-01→09-02 實測 removed_pct=1.8824%，
                # 兩個自報欄位皆確認非截斷，套公式 max(1.0, 1.8824*1.35=2.5412) 進位得 3.0。
                "breaker_pct": 3.0, "abs_floor": 5,
            },
        },
    },
    "openrouter_providers": {
        "label": "OpenRouter 供應商清單",
        "groups": {
            "_providers": {
                "path": ("providers",), "shape": "list", "key_field": "slug",
                "desc_field": "name",
                # 第五階段修正（2026-09-08，見本檔頭「第五階段」區塊與
                # 本機 docs/0908-4-tautological-gates-report.md §3.2）：
                # 原設定 "total_match" + total_fields=("count",) 是**恆真式**
                # ——adapter 直接寫 "count": len(providers)。本輪親打上游確認
                # GET https://openrouter.ai/api/v1/providers 的回應**頂層只有 data
                # 一個鍵**、沒有任何總數或分頁中繼資料，且 limit／offset／page／
                # per_page 四種分頁參數全部被忽略（四次請求都回同一份 24,609B、106 筆），
                # 官方文件（llms-full.txt「List all providers」）也只有單一 List 操作、
                # 無分頁參數。**上游沒有真總數可比**，因此依本檔 GROUP_SOURCES 既有
                # 方法論改用 range_check（實測 min／max 各加 10% 邊界）。
                # 12 份既有快照（2026-08-28～09-08）實測 min=103、max=106 ->
                # floor(103×0.9)=92、ceil(106×1.1)=117。
                # **誠實揭露**：本來源是「單次請求取回整份清單」，沒有分頁迴圈，
                # 真正的截斷風險是 HTTP 讀取中斷（會直接拋例外、記為抓取失敗，
                # 不會產生半份快照）。區間法只能擋「整批塌陷／結構改變」這一類，
                # 對少數幾筆的遺漏沒有鑑別力；本來源的主要防線是熔斷
                # （breaker_pct=1.0%，n≈106 時 max(5, 1.06)=5 筆即熔斷）。
                # 區間上界 117 在目前成長速度（11 天 +3 家）下約 40 天後會被自然成長
                # 追上，**必須定期重新校準**（沿用本檔 range_check 既有立場）。
                "completeness": "range_check", "range": (92, 117),
                "status_fields": (),
                "breaker_pct": 1.0, "abs_floor": 5,
            },
        },
    },
    "payment_protocol_repos": {
        "label": "支付協議規格版本 GitHub Repo 中繼資料（x402／AP2／L402）",
        "groups": {
            "_repos": {
                "path": ("repos",), "shape": "list", "key_field": "id",
                "desc_field": "full_name",
                # require_empty=("errors",)：adapter 原始碼 MIN_SUCCESS=2（3 選 2 即成功），
                # count==len(repos) 單獨不足以保證完整（可能只是 2/3 成功但仍自我一致），
                # 額外要求 errors 為空字典才算完整性通過，見報告 §2.8。
                "completeness": "total_match", "total_fields": ("count",),
                "require_empty": ("errors",),
                "status_fields": ("archived",),
                # 熔斷門檻專屬「過半即熔斷」規則：n=3 時共通公式的 abs_floor=5 會讓熔斷
                # 永遠不可能觸發（最多只有 3 筆可移除），改用 breaker_pct=60%、abs_floor=1，
                # 移除 1 筆（1/3）判定為真實事件、移除 2 筆以上（≥2/3，過半）判定為熔斷。
                "breaker_pct": 60.0, "abs_floor": 1,
            },
        },
    },
# ============================================================================
# 第三階段新增（2026-09-04，接續第二階段，見 specs/SPEC-detect-phase3.md、
# 本機 docs/detect-phase3-report.md）：乙組 3 個來源實測後納入 2 個、1 個來源
# 只納入其中 1 個子集合（另 1 個子集合本輪判定證據不足，不納入，理由見下）。
# 完整推導過程、逐日實測數字、四項驗收見報告；本檔案只放程式碼與必要的簡短依據。
#
#   1.【agent_virtuals，新增完整性檢查方式 tolerant_total_match，見
#      completeness_group() 對應分支】該來源用嚴格相等（total_match）比對
#      平台自報總數 total_reported 與可分頁取得筆數 total_returned 永遠不通過
#      （兩者恆有約 0.05% 落差，屬預期現象，見報告 §2.1），等於沒有偵測。
#      新增第三種完整性檢查方式：truncated_field 必須明確是布林 False（缺失／
#      True 一律 fail-closed），且 total_field 與原始筆數的相對誤差 ≤
#      tolerance_pct。
#      tolerance_pct=0.3%：實測 4 個乾淨日（2026-09-01～09-04，truncated=False）
#      相對誤差穩定落在 0.0532%~0.0558%，門檻取約 5.4 倍安全邊界；同時仍比
#      單一分頁遺漏的量級 0.604%（500 筆/頁 ÷ 82,765 總數）更嚴格，兩者間留
#      約 2 倍緩衝，不會把「漏一頁」誤判為「正常」。4 個時間預算截斷日
#      （2026-08-28~08-31，data.truncated=True，落差 48.96%~59.84%）與乾淨日
#      之間相差 3 個數量級，門檻取值在此區間內都能正確區分，不是精確調校
#      依賴症；truncated 旗標本身已是 fail-closed 的第一道防線，tolerance_pct
#      是第二道防線（見報告 §2.1 完整推導）。
#      breaker_pct=0.02%、abs_floor=20：在目前規模（n≈8.3 萬）等同固定門檻
#      20 筆（0.02%×82,721≈16.5 < 20，floor 主導，直到 n 成長超過約 10 萬），
#      是實測 3 組乾淨日相鄰配對中最大單日消失數 2 筆的 10 倍。這 2 筆消失項目
#      皆為 status=UNDERGRAD 且 totalValueLocked 極低（3、438）的代幣，與已
#      graduate 的 AVAILABLE 代幣無關，比較像平台常態淘汰未畢業代幣的現象
#      （見報告 §2.1，僅陳述觀察到的欄位相關性，不推測平台政策原因）。
#   2.【crypto_project_liveness，dedup() 新增 tuple 複合鍵支援，見 dedup()
#      對應段落】defillamaId 58.4%缺失（731/1252）不能當主鍵；改用 (name, date)
#      複合鍵（SPEC 明文指定）。複合鍵字串成分一律先轉小寫再組字串鍵——實測
#      發現 2026-08-29 出現同一筆歷史事件（同 date=1715040000、同
#      classification/technique/amount/chain）的 name 欄位從 "Saturn" 修正為
#      "SATURN"，純大小寫變更；若不忽略大小寫，複合鍵集合差會把這筆事實上
#      沒有變化的紀錄誤判為「一筆消失＋一筆新增」，這是本輪實測發現、滿足
#      「零假消失」驗收的必要修正，不是 SPEC 原始要求（見報告 §2.2）。
#      忽略大小寫後複合鍵在 8 天歷史內穩定剩 3 組真實重複
#      （Gamma／OcelotDex／Merlin 各自同 name+date 有 2 筆技術手法與金額都
#      不同的獨立事件，見報告 §2.2），套用既有 dedup()「同鍵取最後出現」規則；
#      本輪已驗證這 3 組留存記錄在 8 天內的相對順序完全穩定，去重結果具
#      決定性、不會逐日翻動。
#      完整性檢查沿用既有 total_match（data.count 自報值）；本輪讀 adapter
#      原始碼查明 count 實為 len(hacks) 的同義重複計算（adapter 單次不分頁
#      取得 https://api.llama.fi/hacks 全量陣列後才組出這個欄位），對「抓到
#      一半」沒有獨立驗證力，僅對欄位缺失／型別錯誤等結構性問題有防護——
#      本項為誠實揭露，不隱藏此檢查的實際強度（見報告 §2.1）。
#      🔴 **2026-09-08（第五階段）更新**：上面這段誠實揭露只揭露、沒有修。
#      本輪親打上游確認 api.llama.fi/hacks 回的是裸 JSON 陣列、上游確實沒有
#      任何可比對的總數，已把這個子集合的 completeness 從恆真的 total_match
#      改成 range_check[1115,1383]（見該子集合設定處的行內註解與本檔頭
#      「第五階段」區塊）。上面這段文字保留原樣是為了保存當時的判斷紀錄，
#      **現行設定以 GROUP_SOURCES 為準，已不再是 total_match**。
#      breaker_pct=1.0%、abs_floor=5：實測 7 組乾淨相鄰配對中唯一一次真實
#      消失事件 1 筆／1247 筆，門檻約為其 12.5 倍；該事件（MORE Markets，
#      2026-09-01→09-02）經追查其 defillamaId／parentProtocolId 在後續
#      09-02～09-04 三份快照皆未再出現，未觸發 REAPPEARED（見報告 §2.2）。
#   3.【oracle_feed_directory，只納入 pyth 子集合，chainlink 本輪不納入，
#      依 SPEC「range 規則不足就不要納入，寧可少做」的指示】chainlink 292 筆
#      在整個可用歷史（8 天，2026-08-28~09-04）逐筆內容（含 contractAddress
#      集合本身）除了 09-02→09-03 對既有 2 筆做過中繼資料補充（欄位值變更，
#      membership 未變）之外完全零異動。既有 range_check 公式
#      [floor(min×0.9), ceil(max×1.1)] 的前提是「min／max 反映真實觀測到的
#      變動範圍」（本檔案其餘 range_check 設定皆是如此，見第二階段新增段落
#      開頭原則 4）；chainlink 沒有這個前提（min＝max＝292，觀測不到任何
#      變動），套用同一公式會退化成「單一觀測值 ± 10%」，證據強度與其餘
#      range_check 設定不同一個等級，本輪判定不足以防止假消失，依 SPEC
#      指示不納入（詳見報告 §4.3）。
#      pyth 子集合有真實 8 天增減證據可供校準，納入：key_field="id"
#      （adapter 端 _collect_pyth() 已用 RuntimeError 保證唯一，本輪 8 天
#      複驗同樣 0 重複）；completeness=range_check，range=(1658, 2051)
#      （8 天實測 min=1843／max=1864，套用既有公式 floor(1843×0.9)=1658、
#      ceil(1864×1.1)=2051）；breaker_pct=1.0%、abs_floor=5（實測 7 組相鄰
#      配對最大單日消失 3 筆，門檻約為其 6.2 倍）。desc_field 留 None：pyth
#      項目的人類可讀描述在巢狀 attributes.description，short_desc_generic()
#      只支援單層欄位存取，本輪不擴充該函式（風險/效益不對稱，比照
#      cex_earn_apr.okx 已有的 desc_field=None 先例）。
#      補充背景（報告 §4.3 有更完整說明，本輪未實測驗證，僅供未來參考）：
#      chainlink 每筆同時有 contractAddress 與 proxyAddress 兩個位址欄位，
#      adapter 端只對 contractAddress 做唯一性保證；但公開文件描述的 Chainlink
#      架構慣例是代理合約（proxy）位址在餵送升級時保持不變、底層實作合約
#      位址會變動，若未來累積足夠歷史重新評估納入 chainlink，主鍵應優先
#      考慮 proxyAddress（與設計文件原始建議一致）而非 contractAddress，
#      這點屬背景知識推論，未經本輪實測資料驗證。
#   4.【風險揭露】本階段新納入的 agent_virtuals、crypto_project_liveness、
#      oracle_feed_directory.pyth 三者完整性判定依據，除 agent_virtuals 的
#      truncated 旗標是來源一手訊號外，其餘（total_match 的同義重複計算（tautology）、
#      range_check 的 10% 邊界）皆為本輪工程判斷，非官方欄位保證，且樣本數
#      僅 7~8 天，日後應隨資料累積定期重新校準（沿用第二階段 range_check
#      註解的同一立場）。熔斷門檻同樣只用 7~8 天資料訂定，樣本數雖比
#      第二階段的 6 天略多，但仍屬相對少量樣本，比照同一立場處理。
# ============================================================================
    "agent_virtuals": {
        "label": "Virtuals Protocol Agent 代幣清單",
        "groups": {
            "_items": {
                "path": ("items",), "shape": "list", "key_field": "id",
                "desc_field": "name",
                "completeness": "tolerant_total_match",
                "total_field": "total_reported",
                "truncated_field": "truncated",
                "tolerance_pct": 0.3,
                "status_fields": (),
                "breaker_pct": 0.02, "abs_floor": 20,
            },
        },
    },
    "crypto_project_liveness": {
        "label": "DefiLlama 駭客事件清單（死亡監控資料面）",
        "groups": {
            "_hacks": {
                "path": ("hacks",), "shape": "list", "key_field": ("name", "date"),
                "desc_field": "name",
                # 第五階段修正（2026-09-08，見本檔頭「第五階段」區塊與
                # 本機 docs/0908-4-tautological-gates-report.md §3.3）：
                # 原設定 "total_match" + total_fields=("count",) 是**恆真式**
                # ——adapter 直接寫 "count": len(j)；本檔下方第二階段區塊早就自己
                # 誠實揭露過這件事（「count 實為 len(hacks) 的同義重複計算」），
                # 但當時沒有換掉。本輪親打上游確認
                # GET https://api.llama.fi/hacks **回傳的是裸 JSON 陣列**
                # （頂層不是物件，沒有任何 count／total／分頁欄位），limit／page
                # 參數被忽略（同一份 342,071B、1,257 筆），官方文件
                # （api-docs.defillama.com llms-pro.txt）對 /api/hacks 的描述也是
                # 「Returns: array of {date, name, ...}」。**上游沒有真總數可比**，
                # 因此依本檔既有方法論改用 range_check。
                # 12 份既有快照（2026-08-28～09-08）實測 min=1239、max=1257 ->
                # floor(1239×0.9)=1115、ceil(1257×1.1)=1383。
                # **誠實揭露**：同 openrouter_providers，本來源是單次請求取回整份
                # 陣列、無分頁迴圈；區間法只擋得住「整批塌陷」，主要防線是熔斷
                # （breaker_pct=1.0%，n≈1257 時門檻 max(5, 12.57)=12.6 筆）。
                # 這份清單是**只增不減的累積事件簿**（12 天實測單調不減 1239→1257），
                # 上界 1383 約 77 天後會被自然成長追上，**必須定期重新校準**。
                "completeness": "range_check", "range": (1115, 1383),
                "status_fields": (),
                "breaker_pct": 1.0, "abs_floor": 5,
                # 第四階段新增（2026-09-07，任務 B）：穩定識別欄位，供 reconcile_renames()
                # 判斷「消失的那筆」與「新增的那筆」是不是同一個東西被上游改了名字。
                # 只有設定了這個鍵的子集合才會啟用抵銷層；其餘 12 個子集合沒有這個鍵，
                # compare_group() 走 stable_id_fields 為 None 的路徑，行為與本輪之前
                # 逐位元組相同（已用 11 天全歷史重放驗證，見報告 §4）。
                #
                # 為什麼是 ("defillamaId", "date") 而不是單獨的 "defillamaId"：
                #   defillamaId 是 DefiLlama 的**專案** id，不是**單一駭客事件** id。
                #   同一個專案被攻擊多次時，多筆事件共用同一個 defillamaId——本案的
                #   Stake DAO 就是 defillamaId="249" 同時對應 date=1773273600 與
                #   date=1779840000 兩筆不同事件。單用 defillamaId 會把它們壓成一筆，
                #   製造出比原問題更嚴重的假消失。加上 date 之後，11 天全歷史實測
                #   (defillamaId, date) 只有 3 組重複，且與既有 (name, date) 的 3 組重複
                #   完全是同一批（Gamma／OcelotDex／Merlin，同專案同日期發生兩起不同攻擊，
                #   見 docs/detect-phase3-report.md §2.2），去重後不留任何歧義
                #   （實測 11 天 ambiguous 恆為 0，見報告 §4.2）。
                #
                # 為什麼不改主鍵：見檔頭「第四階段修正」段落第 1～3 點的實測數字。
                "stable_id_fields": ("defillamaId", "date"),
            },
        },
    },
    "oracle_feed_directory": {
        "label": "Pyth 價格餵送目錄（chainlink 子集合本輪評估後不納入，見上方本區塊第 3 點）",
        "groups": {
            "pyth": {
                "path": ("pyth",), "shape": "list", "key_field": "id",
                "desc_field": None,
                "completeness": "range_check", "range": (1658, 2051),
                "status_fields": (),
                "breaker_pct": 1.0, "abs_floor": 5,
            },
        },
    },
# ============================================================================
# 第五階段新增（2026-09-08，使用者裁示「6. 按照建議」＝把 mcp_smithery 納入下架偵測；
# 完整推導、逐項實測數字、風險揭露見本機 docs/0908-3-smithery-detect-report.md）。
#
# 為什麼**現在**才納入：2026-09-07 之前 adapter 少帶 seed 參數，只抓到 272 / 11,771 筆
# （覆蓋率 2.3%），把它納入偵測會用 2.3% 的任意子集合去推「消失」，必然產生大量假事件；
# 2026-09-07 修好（docs/0907-A-smithery-rootcause.md）之後 09-08 實測 11,917 / 11,917
# ＝ 覆蓋率 100.0%、跨頁重複 0，才夠格納入。
#
#   1.【主鍵用 id，不用 qualifiedName —— 這是 0907-B 補丁踩過的坑】
#      id 是 UUID v4（36 碼），12 份真實快照（2026-08-28～09-08，272～11,917 筆）
#      實測：缺失 0 筆、每日唯一 100%（去重前後筆數相同）。
#      qualifiedName（例：`pipeworx/gateway`）是 `namespace + "/" + slug` 組出來的
#      **人類可讀名稱**，兩個成分都是使用者可自行修改的展示欄位；上游改名時
#      集合差會同時吐出「一筆消失＋一筆新增」的假事件（crypto_project_liveness 的
#      Saturn→SATURN 就是同一類問題，見第三階段第 2 點）。
#      11 組相鄰日實測交叉驗證：同一 id 的 qualifiedName 改變 0 次、
#      同一 qualifiedName 的 id 改變 0 次 —— 目前兩者都穩定，但只有 id 是
#      **結構上**不可能被使用者改的識別碼，故取 id。
#      desc_field 取 qualifiedName（只用於人類可讀報告的說明欄，不參與判定）。
#   2.【完整性守門用 full_flag_tolerant_total_match，且**不是恆真式**】
#      adapter 產出的 data 節點有兩個「總數」欄位，必須挑對：
#        - total_returned：值 = len(servers) 本身 → **恆真式**，12 份快照實測差恆為 0，
#          對「抓一半」零防護力。**刻意不用。**
#        - total_count_reported：上游回應 pagination.totalCount 保存下來的自報總數
#          → 真正的獨立驗證。12 份快照實測與 len(servers) 的相對誤差：
#          2026-08-28～09-07（舊 adapter）97.51%～97.69%（例 09-07：272 vs 11,771），
#          2026-09-08（新 adapter）0.0000%（11,917 vs 11,917）。
#          同一組資料下兩個欄位給出完全相反的結論 → 鑑別力已實證，不是恆真式。
#      再加一道 is_full 旗標（adapter 一手訊號，True 才算抓完；定義為
#      stop_reason=="exhausted" 且覆蓋率 >= 98%），缺失/False 一律 fail-closed。
#      tolerance_pct=0.3% 的推導（兩側都留 2.8 倍以上餘裕）：
#        上界（不可誤殺）：實得筆數與自報總數的最大實測落差 0.0085%
#          （2026-09-07 全量掃描 11,814 vs 11,813，見 docs/0907-A-smithery-rootcause.md）；
#          2026-09-08 正式排程與本輪 15:47 重抓皆為 0.0000%。adapter 原始碼記錄
#          「同一輪內 totalCount 在 11,803~11,814 之間漂移」＝ 11 筆 ＝ 0.093%
#          （一輪全量約 229 秒，期間目錄本身會成長）。0.3% 是最壞值 0.093% 的 3.2 倍。
#        下界（要抓得到）：單一分頁遺漏 = PAGE_SIZE = 100 筆 = 現行規模的 0.839%，
#          是門檻的 2.8 倍 → 漏一頁一定會被擋下。
#        樣本揭露：全量快照目前**只有 1 天**（2026-09-08）＋本輪 1 次重抓，
#          樣本極薄，應隨每日快照累積重新校準（沿用第二／第三階段同一立場）。
#   3.【熔斷門檻 breaker_pct=1.0%、abs_floor=20】
#      兩組互相獨立的實測日移除率，結論收斂：
#        (i) 舊 adapter 的 272 筆子集合，10 組相鄰日（08-28～09-07）移除數
#            1,0,1,0,1,1,0,2,0,0 → 合計 6 筆，平均 0.221%/日，單日最大 2/271 ＝ 0.738%。
#        (ii) 全量母體同日內實測：2026-09-08 00:00 UTC 正式快照（11,917 筆）對
#            本輪 07:55 UTC 重抓（11,936 筆），間隔 7 小時 55 分，移除 9 筆
#            （0.0755%）、新增 28 筆；線性外推 24 小時約 27.8 筆 ＝ 0.233%/日【推論】。
#      套本檔案第二階段既有公式 ceil(max(1.0, 單日最大% × 1.35))：
#        0.738 × 1.35 = 0.996 → max(1.0, 0.996) = **1.0**。與 (ii) 外推值
#        0.233 × 1.35 = 0.315 相比也遠在安全側。現行規模下 1.0% ≈ 119 筆，
#        約為外推日均移除量的 4.3 倍。
#      abs_floor=20：現行規模下**可證明是惰性的**（1.0%×11,917＝119 ≫ 20，
#        只有 n_old < 2,000 時才會生效），而 n_old < 2,000 在結構上不可能發生
#        ——adapter 的 MIN_ITEMS=8000 會先丟 RuntimeError，該日根本不會有快照；
#        取 20 是與同為五位數規模的 agent_virtuals 一致，不是精確調校。
#      **樣本只有 1 天全量 + 1 次同日重抓**，比照專案既有 30~60 天慣例，
#      這個門檻要等累積 30~60 天全量快照後才算真正校準過（見報告 §5.3）。
#   4.【status_fields=("unlisted","inactive")】上游原生的「已下架／已停用」旗標，
#      比照第二階段原則 6（旗標優先）納入。實測成本為零：
#        09-08 全量 11,917 筆 unlisted True=0、inactive True=0、缺失 0；
#        10 組 v2 相鄰配對（交集約 271 筆）兩欄位變動 0；
#        09-08 同日全量交集 11,908 筆兩欄位變動 0。
#      **不納入** verified（True 283 筆／2.375%）、isDeployed（8,666 筆／72.72%）、
#      remote（3,251 筆為 None）、bySmithery（137 筆／1.15%）：這四個是能力／品質
#      屬性不是上架狀態；remote 大量缺值，上游若補值會產生 None→False 的假變化。
#      【推論】unlisted／inactive 也可能結構上永遠為 False（上游可能在清單端就
#      濾掉這類項目，那樣它們只會直接從清單消失＝走 DELISTED），本輪無法證實或證偽；
#      納入的成本是 0，留著是為了「真的翻旗標時抓得到」。
#   5.【parser_version 版本下限守門 min_parser_version=3 —— 本輪最重要的風險控制】
#      09-07 以前的舊快照只有 272 筆、09-08 起是 11,917 筆，直接比對會產生
#      **11,645 筆假 LISTED**（實測：09-07→09-08 以 id 做集合差，added=11,645、
#      removed=0）。本檔案原本的 parser_version 豁免機制只存在於
#      breaker_release_check()，那條路徑只在 judged=="BREAKER" 時才會走到，
#      **管不到這個情境**（本情境 removed=0，熔斷根本不會成立）。
#      因此本輪新增 parser_version_floor_check()（見該函式），並在
#      process_group_source_pair() 掛上。只有設定 min_parser_version 的子集合
#      才啟用，其餘 13 個子集合完全 no-op。
#      同時也已實測確認：即使把這道守門整個拿掉，完整性守門仍會獨立擋下全部
#      11 組舊配對（舊快照 is_full=False → GATE_FAIL），兩層互相獨立（見報告 §4.3）。
# ============================================================================
    "mcp_smithery": {
        "label": "Smithery MCP 註冊表全量伺服器清單（registry.smithery.ai/servers）",
        "groups": {
            "_servers": {
                "path": ("servers",), "shape": "list", "key_field": "id",
                "desc_field": "qualifiedName",
                "completeness": "full_flag_tolerant_total_match",
                "full_field": "is_full",
                "total_field": "total_count_reported",
                "tolerance_pct": 0.3,
                "status_fields": ("unlisted", "inactive"),
                "breaker_pct": 1.0, "abs_floor": 20,
                # 版本下限：只有 parser_version >= 3（帶 seed 的全量 adapter）且兩日
                # 相同的配對才進行比對。低於下限或兩日不同一律 GATE_FAIL，見上方第 5 點
                # 與 parser_version_floor_check()。
                "min_parser_version": 3,
            },
        },
    },
}


# ============================================================================
# 第四階段新增（2026-09-07，本輪任務 E；派工來源 docs/0907-events-audit-0904-0907.md
# §5.8 與 §9.3 第 4 項，使用者裁示「做法 2＋做法 4，不做做法 3」。完整推導、實測數字、
# 歷史全量重放驗證見本機 docs/0907-E-gate-flap-report.md）：
#
# 背景（實測，非推測）：`cex_currency_status/gate` 在 2026-09-06 出現 170 筆
# `withdraw_disabled: true→false`、09-07 出現 171 筆 `false→true`，兩批鍵集合交集 170 筆
# ——同一批幣種翻過去又翻回來。同期 `delisted`／`trade_disabled` 兩個旗標完全沒動。
# 這 341 筆佔 2026-09-04～09-07 期間 STATUS_CHANGED 總數 370 筆的 92.2%。
# 現行設計對 STATUS_CHANGED 沒有任何抖動抑制（熔斷只看 removed_pct），這是設計缺口。
#
# 本輪加兩層互相獨立的機制，兩層都「不刪除任何既有事件行」：
#
#   做法 2【抖動標記 flap detection】—— 見 FLAP_WINDOW_DAYS／flap_marks()／annotate_flaps()。
#     某個 (group, key, 欄位) 的值在 N 天內翻回原值時，把相關的兩筆 STATUS_CHANGED
#     事件都補上 `flapped`／`flap_fields`／`flap_with` 三個欄位。**事件照寫、不阻擋、
#     不刪除**——兩天的事件各自都如實描述了「快照之間欄位值確實不同」這個事實，
#     刪掉會損失保真度（這是使用者明確裁示不採「做法 3」的理由）。
#     因為第 2 筆事件出現時第 1 筆早已寫進 events.jsonl，標記必須「回頭更新既有事件行」，
#     所以 annotate_flaps() 是整檔改寫（原子寫入），不是附加。冪等性見該函式 docstring。
#
#   做法 4【語意過濾 semantic filter】—— 見 status_filter_hit()／status_changes_for_group()。
#     某些欄位在特定前提下沒有資訊價值（例如已下架幣種的提幣旗標），這類欄位變化
#     一開始就不該產生 STATUS_CHANGED。規則寫在 GROUP_SOURCES 各子集合的
#     "status_filters"（與它管的 "status_fields" 放在一起，方便下一輪的人找到），
#     schema 見下方；被抑制的每一筆都會寫進 STATUS_FILTER_LOG 這份事實紀錄檔，
#     「不產生事件」不等於「資料消失」，稽核時仍可完整還原。
#
# 「哪些欄位在哪些前提下沒有資訊價值」的逐欄位盤點表見報告 §3.2。本輪**只**啟用
# cex_currency_status/gate 的一條規則（withdraw_disabled 在 delisted 兩側皆 True 時）。
# 其餘 6 個帶 status_fields 的子集合（cex_currency_status/coinbase、cex_earn_apr/bybit、
# cex_symbols_ext/coinbase、cex_symbols_ext/kraken、openrouter_models/_models、
# payment_protocol_repos/_repos）都只有單一狀態欄位，沒有「另一個欄位可以當前提」的
# 結構，本輪一律不設規則（預設 deny：沒寫規則＝不過濾，行為與本輪之前完全相同）。
#
# ---------------------------------------------------------------------------
# status_filters schema（放在 GROUP_SOURCES[<source>]["groups"][<group>] 裡）：
#
#   "status_filters": (
#       {"field": <欄位名>,                 # 只抑制這一個欄位的變化
#        "when_both": {<前提欄位>: <值>, ...},  # 前提：**新舊兩側**都必須符合全部條件
#        "reason": <字串代碼>},             # 寫進 STATUS_FILTER_LOG 的理由碼
#       ...
#   )
#
# 「when_both＝新舊兩側都要成立」是刻意的設計，不是實作細節：
#   - 它保證「前提欄位本身正在變化的那一天」不會被過濾掉。例如 2026-09-03 有 26 個幣種
#     同時發生 delisted:False→True 與 trade_disabled:False→True（下架事件本身），
#     那一天 delisted 舊值是 False，when_both 不成立，整筆事件完整保留。
#   - 實測全歷史 251 筆命中本規則的欄位變化，其中「同一 (key, date) 的 delisted 欄位
#     也同時變化」的筆數是 0，與上述設計預期一致（見報告 §3.3）。
# ---------------------------------------------------------------------------

# 抖動回翻視窗（天）。用實測資料訂，不是拍腦袋——完整推導見報告 §2.2：
#   全歷史 gate 448 筆欄位級轉換，配對出的「翻回原值」間隔分佈是
#   gap=1 天 176 組、gap=2 天 **0 組**、gap=3 天 1 組、gap=4 天 4 組、gap=6 天 1 組、
#   gap=8 天 1 組。gap=1 與 gap>=3 之間存在一個**實測為空**的天然斷層（gap=2）。
#   取 N=2 的理由：
#     (a) 對現有資料，N=2 與 N=1 的結果**完全相同**（176 組、352 筆），不多標記任何一筆；
#     (b) 但 N=2 可以吸收「中間缺一天快照」的情況——快照缺 1 天時，相鄰快照配對會跨 2 個
#         日曆日，事件日期間隔會從 1 天變成 2 天，N=1 會漏掉這種真實抖動；
#     (c) N 太大的副作用是**讓異常日回頭污染更早的正常事件**：實測 N=3 會把 PRIMAL
#         09-03 的一筆正常變化與 09-06 異常日配成對；N=4 會把 ONT／WING／TT／ONG
#         09-01→09-05 的四天期提幣暫停（看起來像真實的維護窗，有資訊價值）標成抖動。
#   結論：N=2 是「涵蓋全部已觀測抖動 + 容忍一天快照缺漏 + 不碰到任何 gap>=3 案例」的取值。
#   樣本僅 11 天，應隨資料累積重新校準（沿用本檔案 range_check／熔斷門檻註解的同一立場）。
FLAP_WINDOW_DAYS = 2

# 語意過濾事實紀錄檔：被 status_filters 抑制掉、因此不會出現在 events.jsonl 的每一筆
# 欄位變化，都在這裡留下完整紀錄（含新舊值與理由碼）。設計理由與 GATE_FAIL_LOG 完全同構
# （見該常數註解）：放在 track-crypto/data/_status_filter/（底線開頭＝跨來源共用、
# 非單一 <source> 專屬），只用附加模式寫檔，去重鍵 (date, source, group, key, field)。
# 「不產生事件」必須可稽核——沒有這份紀錄，語意過濾就變成把資料悄悄丟掉。
STATUS_FILTER_LOG = os.path.join(TRACK_CRYPTO, "data", "_status_filter", "suppressed.jsonl")
STATUS_FILTER_LOG_SIZE_HINT_LINES = 5000



def path_get(root, path):
    """從 root 依 path（key 的 tuple）逐層下鑽，任何一層不是 dict 或 key 不存在就回傳 None。
    path=() 代表不下鑽，直接回傳 root 本身（用於 cex_withdrawal_limits 這種「data 頂層即清單」的來源）。
    """
    node = root
    for k in path:
        if not isinstance(node, dict):
            return None
        node = node.get(k)
    return node


def extract_group_items(data_root, gcfg):
    """回傳 (keyed, dup, missing, n_raw)。
    shape=="list"：沿用既有 dedup()（不修改該函式，只是換一組引數呼叫）。
    shape=="dict"：dict 鍵本身即主鍵，JSON object 結構保證不重複，dup/missing 固定 0。
    路徑不存在或型別不符時回傳 (None, None, None, None)，由呼叫端視為完整性失敗。
    """
    node = path_get(data_root, gcfg["path"]) if gcfg["path"] else data_root
    if gcfg["shape"] == "list":
        if not isinstance(node, list):
            return None, None, None, None
        keyed, dup, missing = dedup(node, gcfg["key_field"])
        return keyed, dup, missing, len(node)
    elif gcfg["shape"] == "dict":
        if not isinstance(node, dict):
            return None, None, None, None
        return dict(node), 0, 0, len(node)
    return None, None, None, None


def completeness_group(data_root, gcfg):
    """回傳 (ok, n_raw, reason)。
    total_match：gcfg["total_fields"] 逐一比對 data_root 上的自報欄位是否等於子集合原始筆數
                 （去重前），全部存在且相符才 ok；require_empty 額外要求指定欄位為空/假值。
    range_check：子集合原始筆數是否落在 gcfg["range"] = (lo, hi) 區間內。
    tolerant_total_match：第三階段新增（見下方對應分支的行內註解），自報總數與原始筆數
                 容許 gcfg["tolerance_pct"] 相對誤差，並要求 gcfg["truncated_field"]
                 明確為 False，目前只有 agent_virtuals 使用。
    reported_total_match：第五階段新增（2026-09-08，見下方對應分支的行內註解）。
                 gcfg["reported_total_field"] 讀到的**上游自報總數**與原始筆數比對，
                 容忍度 = max(tolerance_abs_floor, tolerance_pct% × 自報總數)；
                 該欄位不存在（adapter 升版前的舊快照）時退回 gcfg["legacy_range"]
                 區間檢查。目前只有 ofac_sanctions_crypto 使用。
                 ⚠️ 這個欄位的值必須來自**上游另一份獨立來源**，不可以是 adapter 自己
                 算出來的 len(items)——那會讓守門變成恆真式（本輪修掉的缺陷）。
    total_fields／require_empty／total_field／truncated_field 一律讀 data_root 這一層
    （來源的 data 節點本身），不是子集合節點內——本階段 8 個來源的自報總數欄位
    （count／total_count／errors）實測皆位於 data 頂層，不在子集合節點內部
    （見報告 §2 逐來源小節的實測依據）。
    """
    node = path_get(data_root, gcfg["path"]) if gcfg["path"] else data_root
    if gcfg["shape"] == "list":
        if not isinstance(node, list):
            return False, None, "節點缺失或非清單"
        n_raw = len(node)
    elif gcfg["shape"] == "dict":
        if not isinstance(node, dict):
            return False, None, "節點缺失或非物件"
        n_raw = len(node)
    else:
        return False, None, "未知 shape=%r" % (gcfg.get("shape"),)

    method = gcfg["completeness"]
    if method == "total_match":
        if not isinstance(data_root, dict):
            return False, n_raw, "data 節點非物件，無法讀自報欄位"
        for tf in gcfg["total_fields"]:
            tv = data_root.get(tf)
            if tv is None:
                return False, n_raw, "缺 %s 欄位" % tf
            if tv != n_raw:
                return False, n_raw, "%s(%r) != len(%d)" % (tf, tv, n_raw)
        for rf in gcfg.get("require_empty", ()):
            rv = data_root.get(rf)
            if rv:
                return False, n_raw, "%s 非空（%r），視為部分抓取失敗" % (rf, rv)
        return True, n_raw, "total_match"
    elif method == "range_check":
        lo, hi = gcfg["range"]
        if n_raw < lo or n_raw > hi:
            return False, n_raw, "n=%d 超出實測合理區間 [%d, %d]" % (n_raw, lo, hi)
        return True, n_raw, "range_check[%d,%d]" % (lo, hi)
    elif method == "tolerant_total_match":
        # 第三階段新增（specs/SPEC-detect-phase3.md，目前只有 agent_virtuals 使用）：
        # 來源本身有自報總數，但該總數與可分頁取得筆數之間有一個已知、小幅且持續
        # 存在的落差（agent_virtuals 實測 4 個乾淨日恆為 0.05%~0.06%，見報告 §2.1），
        # 嚴格相等（total_match）在這個來源永遠不通過，等於沒有偵測；改用「容忍度」：
        #   1. truncated_field 必須明確是布林 False（不是 falsy，是 is False 這個精確
        #      型別檢查）。缺失、None、True 或任何非 False 值一律 fail-closed 視為
        #      不完整——這是來源自己回報的「這次抓取有沒有被分頁上限/時間預算中止」
        #      一手訊號，比本函式其餘方式都更直接，優先權最高。
        #   2. total_field 讀到的自報總數與 n_raw（原始筆數，去重前）相對誤差不得
        #      超過 tolerance_pct（相對誤差以 total_field 的值為分母）。
        # 兩者皆通過才算完整；任一者不通過即回傳 False，理由文字分別標示。
        if not isinstance(data_root, dict):
            return False, n_raw, "data 節點非物件，無法讀自報欄位與 truncated 旗標"
        tf_name = gcfg["truncated_field"]
        tf_val = data_root.get(tf_name)
        if tf_val is not False:
            return False, n_raw, "%s(%r) 非布林 False（缺失/True 一律 fail-closed 視為不完整）" % (tf_name, tf_val)
        total_field = gcfg["total_field"]
        total = data_root.get(total_field)
        if not isinstance(total, (int, float)) or isinstance(total, bool) or total <= 0:
            return False, n_raw, "缺 %s 欄位或非正數（%r）" % (total_field, total)
        gap_pct = abs(total - n_raw) / total * 100.0
        tol = gcfg["tolerance_pct"]
        if gap_pct > tol:
            return False, n_raw, ("%s(%r) 與原始筆數(%d) 相對誤差 %.4f%% 超過容忍度 %.2f%%"
                                   % (total_field, total, n_raw, gap_pct, tol))
        return True, n_raw, "tolerant_total_match(gap=%.4f%%,tol=%.2f%%)" % (gap_pct, tol)
    elif method == "full_flag_tolerant_total_match":
        # 第五階段新增（2026-09-08，目前只有 mcp_smithery 使用；完整推導與實測數字見
        # 本機 docs/0908-3-smithery-detect-report.md §3）。
        #
        # 與 tolerant_total_match 的差別只有一個：旗標的**極性相反**。
        # agent_virtuals 的 adapter 自報 `truncated`（True＝抓壞了），mcp_smithery 的
        # adapter 自報 `is_full`（True＝抓好了）。snap_crypto.py 只在寫 manifest 時
        # 把 is_full 反極性成 truncated，**快照 data 節點裡沒有 truncated 這個欄位**
        # （2026-08-28～09-08 全部 12 份快照實測確認），所以不能直接沿用
        # tolerant_total_match：`data_root.get("truncated")` 恆為 None，
        # `None is not False` 會讓這個來源**每一天都 fail-closed**，等於永遠沒有偵測。
        # 依本檔案第二／第三階段既有慣例（新需求＝新增一個具名分支，不改既有分支），
        # 另開這個分支；既有三個分支一個字元都沒有動。
        #
        # 兩個條件都要通過：
        #   1. full_field（is_full）必須明確是布林 True。缺失／None／False 一律
        #      fail-closed。這是 adapter 自己回報的「這次有沒有抓完」一手訊號
        #      （adapter 內部定義：stop_reason=="exhausted" 且覆蓋率 >= 98%），
        #      優先權最高，比照 tolerant_total_match 的旗標優先原則。
        #   2. total_field（total_count_reported，即上游 pagination.totalCount）
        #      與 n_raw（原始筆數，去重前）的相對誤差不得超過 tolerance_pct
        #      （分母是 total_field 的值，與 tolerant_total_match 同一算式）。
        #
        # **這不是恆真式**（第四階段 x402_bazaar 踩過的坑，見檔頭與本檔 SOURCES 上方
        # 註解）：adapter 另有一個 `total_returned` 欄位，它的值就是 len(servers)
        # 本身，拿它來比對是自我一致的假保護；本設定刻意**不用** total_returned，
        # 用的是上游回應 pagination.totalCount 保存下來的 total_count_reported。
        # 12 份真實快照實測：2026-08-28～09-07 這 11 天 total_returned 恆等於
        # len(servers)（差 0），但 total_count_reported 與 len(servers) 差
        # 97.51%～97.69%（例如 09-07：272 vs 11,771），09-08 修好後差 0.0000%
        # （11,917 vs 11,917）——同一組資料下兩個欄位給出完全相反的結論，
        # 證明本守門對「抓一半」有真實鑑別力。
        if not isinstance(data_root, dict):
            return False, n_raw, "data 節點非物件，無法讀自報欄位與 is_full 旗標"
        ff_name = gcfg["full_field"]
        ff_val = data_root.get(ff_name)
        if ff_val is not True:
            return False, n_raw, ("%s(%r) 非布林 True（缺失/False 一律 fail-closed 視為不完整）"
                                   % (ff_name, ff_val))
        total_field = gcfg["total_field"]
        total = data_root.get(total_field)
        if not isinstance(total, (int, float)) or isinstance(total, bool) or total <= 0:
            return False, n_raw, "缺 %s 欄位或非正數（%r）" % (total_field, total)
        gap_pct = abs(total - n_raw) / total * 100.0
        tol = gcfg["tolerance_pct"]
        if gap_pct > tol:
            return False, n_raw, ("%s(%r) 與原始筆數(%d) 相對誤差 %.4f%% 超過容忍度 %.2f%%"
                                   % (total_field, total, n_raw, gap_pct, tol))
        return True, n_raw, ("full_flag_tolerant_total_match(gap=%.4f%%,tol=%.2f%%)"
                             % (gap_pct, tol))
    elif method == "reported_total_match":
        # 第五階段新增（2026-09-08，恆真式守門修正第二批，見本檔頭「第五階段」區塊，
        # 目前只有 ofac_sanctions_crypto 使用）：比對「上游另外發布的自報總數」與
        # 子集合原始筆數，容忍度 = max(tolerance_abs_floor, tolerance_pct% × 自報總數)。
        # 名稱與語意刻意與 completeness()（SOURCES 路徑，x402_bazaar，任務 D）的
        # reported_total_match 完全一致，不另創第二套講法；兩者是不同函式、不同
        # 程式碼路徑（一個服務單一清單來源，一個服務多子集合來源），彼此不能互相涵蓋。
        #
        # 與同函式 tolerant_total_match 的差異，以及為什麼不直接沿用它：
        #   1. 門檻表示法不同：本方法用「絕對筆數」門檻 max(abs_floor, pct%×total)
        #      ——這是本檔既有房規（熔斷 threshold_count、completeness() 皆同構）；
        #      tolerant_total_match 用的是相對誤差百分比。
        #   2. tolerant_total_match 強制要求 truncated_field 明確為布林 False。
        #      本方法的唯一使用者是「單次下載整份 CSV」的來源，沒有分頁迴圈，
        #      也就沒有「翻頁翻到一半」這個一手訊號可回報；硬塞一個恆為 False 的
        #      旗標只會製造另一個假保護感——那正是本輪要修掉的東西，所以不塞。
        # 舊快照（adapter 升版前沒有這個欄位）退回 legacy_range 區間檢查，比照
        # completeness() 的同名相容分支：不這樣做的話全部歷史相鄰配對都會 GATE_FAIL。
        if not isinstance(data_root, dict):
            return False, n_raw, "data 節點非物件，無法讀自報欄位"
        rtot = data_root.get(gcfg["reported_total_field"])
        if rtot is None:
            lo_g, hi_g = gcfg["legacy_range"]
            if n_raw < lo_g or n_raw > hi_g:
                return False, n_raw, ("legacy_range_check[%d,%d] 未通過：原始筆數 %d 超出實測合理區間"
                                      % (lo_g, hi_g, n_raw))
            return True, n_raw, "legacy_range_check[%d,%d]" % (lo_g, hi_g)
        if not isinstance(rtot, (int, float)) or isinstance(rtot, bool) or rtot <= 0:
            return False, n_raw, "%s 非正數（%r）" % (gcfg["reported_total_field"], rtot)
        tol_n = max(gcfg["tolerance_abs_floor"], gcfg["tolerance_pct"] / 100.0 * rtot)
        gap_n = abs(rtot - n_raw)
        if gap_n > tol_n:
            return False, n_raw, ("%s(%s) 與原始筆數(%d) 相差 %d 筆，超過容忍度 %.1f 筆"
                                  "（max(%s, %.2f%%×%s)）"
                                  % (gcfg["reported_total_field"], rtot, n_raw, gap_n, tol_n,
                                     gcfg["tolerance_abs_floor"], gcfg["tolerance_pct"], rtot))
        return True, n_raw, "reported_total_match(gap=%d,limit=%.1f)" % (gap_n, tol_n)
    return False, n_raw, "未知完整性檢查方式 %r" % (method,)


def short_desc_generic(item, desc_field, n=120):
    """比照既有 short_desc()（不修改該函式），改成可指定欄位名稱的通用版本，
    供本階段多個來源、各自不同的「友善描述欄位」共用（例如 gate 用 name、
    ofac 用 sdn_name、payment_protocol_repos 用 full_name）。"""
    if not isinstance(item, dict) or not desc_field:
        return ""
    s = item.get(desc_field) or ""
    s = " ".join(str(s).split())
    return (s[:n] + "\u2026") if len(s) > n else s


def stable_identity(item, fields):
    """第四階段新增（2026-09-07，任務 B）：回傳這一筆項目的「穩定識別字串」，
    無法構成時回傳 None。

    fields 是欄位名稱的 tuple（例如 crypto_project_liveness 的
    ("defillamaId", "date")）。任一欄位缺失、為 None 或為空字串，整筆就沒有穩定
    識別（回傳 None）——這是刻意的 fail-closed：**寧可不抵銷（維持現狀，可能留下
    一組假事件），也不要用殘缺的識別亂配對而抵銷掉真實的消失事件**。

    組字串的規則刻意與 dedup() 的複合鍵完全一致（字串成分轉小寫、其餘型別原樣
    轉字串、用 "\x1f" 連接），這樣兩種鍵在日誌／報告裡看起來是同一種格式，
    也避免將來有人以為兩者可以互換卻踩到大小寫差異。
    """
    if not isinstance(item, dict) or not fields:
        return None
    parts = []
    for f in fields:
        v = item.get(f)
        if v is None or v == "":
            return None
        parts.append(v.lower() if isinstance(v, str) else v)
    return "\x1f".join(str(p) for p in parts)


def build_stable_id_index(keyed, fields):
    """第四階段新增（2026-09-07，任務 B）：回傳 (index, ambiguous)。

    index：{穩定識別字串 -> 主鍵}，只收「在這份快照裡穩定識別唯一對應一個主鍵」的項目。
    ambiguous：被排除的穩定識別集合（同一份快照裡有兩個以上主鍵共用它）。

    為什麼要排除歧義而不是取第一個／最後一個：抵銷層會直接讓一筆 DELISTED 不寫入
    事件流，是「減少事實紀錄」的動作，必須比一般判定更保守。歧義代表我們無法確定
    「消失的那筆」對應到「新增的哪一筆」，此時**不抵銷**（維持現行行為，照常寫
    DELISTED／LISTED），把判斷留給人。11 天全歷史實測 ambiguous 恆為 0
    （見報告 §4.2），這條路徑目前不會被觸發，是純粹的防禦性設計。
    """
    index = {}
    ambiguous = set()
    for k, it in keyed.items():
        sid = stable_identity(it, fields)
        if sid is None:
            continue
        if sid in index or sid in ambiguous:
            index.pop(sid, None)
            ambiguous.add(sid)
        else:
            index[sid] = k
    return index, ambiguous


def reconcile_renames(gcfg, keyed_old, keyed_new, added_keys, removed_keys):
    """第四階段新增（2026-09-07，任務 B）：把「同一個東西被上游改名」造成的
    一筆假消失＋一筆假新增配對起來抵銷。

    回傳 (added_keys, removed_keys, renamed_pairs)：
      - renamed_pairs：[(old_key, new_key, 穩定識別字串), ...]，依 old_key 排序。
      - added_keys／removed_keys：已扣掉配對成功者的新清單（保持原本的排序規則）。

    未設定 gcfg["stable_id_fields"] 的子集合（本輪除 crypto_project_liveness/_hacks
    以外全部 12 個子集合）在第一行就原樣回傳，**連一次迴圈都不會跑**，因此
    removed_keys／added_keys 逐位元組不變。

    抵銷條件（三個條件都成立才算改名，任何一個不成立就維持現行行為）：
      1. 消失的那筆有完整的穩定識別（stable_identity() 非 None）。
      2. 同一個穩定識別在**當日**快照裡唯一對應到某個主鍵（不在 ambiguous 裡）。
      3. 那個主鍵**確實出現在本次的 added_keys 裡**——這一條是關鍵：若該主鍵在前日
         快照就已存在（不是新增），代表這是「兩筆本來就各自存在的紀錄」，
         不是改名，不可抵銷。

    刻意不做的事：不比對 name 以外的其他欄位（例如 amount／chain）是否也相同。
    理由是穩定識別已經包含上游自己的專案 id 與事件日期，再加欄位比對只會讓
    「上游同時修正了名稱與金額」這種情形無法抵銷，反而回到假事件；欄位層級的
    變化本來就有 status_fields／STATUS_CHANGED 這條既有管道負責（本來源
    status_fields 為空，屬設計選擇，不在本輪範圍）。
    """
    fields = gcfg.get("stable_id_fields") or ()
    if not fields:
        return added_keys, removed_keys, []
    idx_new, _amb_new = build_stable_id_index(keyed_new, fields)
    added_set = set(added_keys)
    renamed_pairs = []
    matched_old, matched_new = set(), set()
    for k_old in removed_keys:
        sid = stable_identity(keyed_old.get(k_old), fields)
        if sid is None:
            continue
        k_new = idx_new.get(sid)
        if k_new is None or k_new not in added_set or k_new in matched_new:
            continue
        renamed_pairs.append((k_old, k_new, sid))
        matched_old.add(k_old)
        matched_new.add(k_new)
    if not renamed_pairs:
        return added_keys, removed_keys, []
    added_keys = [k for k in added_keys if k not in matched_new]
    removed_keys = [k for k in removed_keys if k not in matched_old]
    renamed_pairs.sort(key=lambda t: repr(t[0]))
    return added_keys, removed_keys, renamed_pairs


def compare_group(source, gname, gcfg, data_old, data_new):
    """單一子集合、單一相鄰日配對的完整比對結果。比照 compare_pair() 但泛化到支援
    range_check／total_match 兩種完整性檢查與 list／dict 兩種資料形狀。"""
    ok_old, n_old_raw, reason_old = completeness_group(data_old, gcfg)
    ok_new, n_new_raw, reason_new = completeness_group(data_new, gcfg)
    gate_ok = ok_old and ok_new

    keyed_old, dup_old, miss_old, _ = extract_group_items(data_old, gcfg)
    keyed_new, dup_new, miss_new, _ = extract_group_items(data_new, gcfg)
    keyed_old = keyed_old or {}
    keyed_new = keyed_new or {}

    added_keys = sorted(set(keyed_new) - set(keyed_old), key=repr)
    removed_keys = sorted(set(keyed_old) - set(keyed_new), key=repr)

    # 第四階段新增（2026-09-07，任務 B）：上游改名抵銷層。刻意放在「集合差算完」
    # 之後、「移除率／熔斷門檻算出來」之前——改名本來就不是消失，讓它繼續留在
    # removed_keys 裡去墊高 removed_rate，等於用假事件去逼近熔斷門檻，是錯的。
    # 未設定 stable_id_fields 的子集合，reconcile_renames() 第一行就原樣回傳，
    # 下面三行的計算結果與本輪之前逐位元組相同。
    added_keys, removed_keys, renamed_pairs = reconcile_renames(
        gcfg, keyed_old, keyed_new, added_keys, removed_keys)

    removed_rate = (len(removed_keys) / len(keyed_old) * 100.0) if keyed_old else 0.0
    threshold_count = max(gcfg["abs_floor"], gcfg["breaker_pct"] / 100.0 * len(keyed_old))
    breaker = gate_ok and (len(removed_keys) > threshold_count)
    # 第四階段（熔斷語意統一）新增的純加法欄位，見 compare_pair() 同一段註解。
    tail_run, tail_cover = removal_tail_metrics(keyed_old, removed_keys)

    return {
        "source": source, "group": gname,
        "gate_ok": gate_ok, "ok_old": ok_old, "ok_new": ok_new,
        "reason_old": reason_old, "reason_new": reason_new,
        "n_old_raw": n_old_raw, "n_new_raw": n_new_raw,
        "dup_old": dup_old or 0, "dup_new": dup_new or 0,
        "miss_old": miss_old or 0, "miss_new": miss_new or 0,
        "keyed_old": keyed_old, "keyed_new": keyed_new,
        "added_keys": added_keys, "removed_keys": removed_keys,
        "removed_rate": removed_rate, "threshold_count": threshold_count, "breaker": breaker,
        "tail_run": tail_run, "tail_cover": tail_cover,
        # 第四階段新增：本次配對抵銷掉的「上游改名」清單，[(舊主鍵, 新主鍵, 穩定識別), ...]。
        # 未啟用抵銷層的子集合恆為空 list，既有讀取端（judge()／build_group_events()／
        # status_changes_for_group()）完全不讀這個欄位，多一個鍵不影響任何既有邏輯。
        "renamed_pairs": renamed_pairs,
    }


def status_filter_hit(filters, field, old_item, new_item):
    """做法 4【語意過濾】的單筆判定（純函式，無副作用）：回傳命中的規則 dict，沒命中回傳 None。

    規則 schema 見檔案上方「第四階段新增」區塊。命中條件（全部成立才算命中）：
      1. rule["field"] == field（規則只管指定的那一個欄位）；
      2. rule["when_both"] 裡的每一組 (前提欄位, 期望值)，在 **old_item 與 new_item 兩側**
         都必須相等（用 == 比對，不是 truthy 判定——withdraw_disabled 這類旗標的 True/1、
         False/0/None 語意不同，必須嚴格比對）。

    「兩側都要成立」是刻意的：前提欄位本身正在變化的那一天（例如幣種當天才剛被標成
    delisted），when_both 不會成立，那筆事件就會完整保留，不會被誤濾。"""
    for rule in (filters or ()):
        if rule.get("field") != field:
            continue
        cond = rule.get("when_both") or {}
        if all(old_item.get(cf) == cv and new_item.get(cf) == cv for cf, cv in cond.items()):
            return rule
    return None


def status_changes_for_group(gcfg, keyed_old, keyed_new, suppressed_out=None):
    """回傳 {key: (delta_from_dict, delta_to_dict)}，只含實際有變化的欄位。
    只比對兩側都存在（key 未消失）的項目——key 本身的存在/消失由 DELISTED/LISTED
    處理，這裡只處理「還在清單裡、但欄位值變了」的情況（旗標優先，見檔案上方
    第二階段設計原則第 6 點）。

    本輪（2026-09-07，做法 4）新增語意過濾：gcfg["status_filters"] 命中的欄位變化直接
    從 delta 拿掉；一筆 (key) 的全部變化欄位都被拿掉時，該 key 不會出現在回傳值裡，
    也就不會產生 STATUS_CHANGED 事件。**沒有設定 status_filters 的子集合行為與本輪之前
    逐位元組相同**（預設 deny：沒寫規則＝不過濾），selftest 既有的合成 gcfg 也不受影響。

    suppressed_out：可選的 list，呼叫端傳入後會被原地附加每一筆被抑制的欄位變化
    （{key, field, from, to, reason}），供呼叫端寫進 STATUS_FILTER_LOG 稽核。不傳
    （None）時純粹不記錄，過濾行為完全相同——process_group_source_pair() 為了統計
    報表筆數會再呼叫本函式一次，那一次刻意不傳，避免同一筆被記錄兩次。"""
    fields = gcfg.get("status_fields") or ()
    if not fields:
        return {}
    filters = gcfg.get("status_filters") or ()
    changes = {}
    for k in sorted(set(keyed_old) & set(keyed_new), key=repr):
        old_item, new_item = keyed_old[k], keyed_new[k]
        if not isinstance(old_item, dict) or not isinstance(new_item, dict):
            continue
        delta_from, delta_to = {}, {}
        for f in fields:
            ov, nv = old_item.get(f), new_item.get(f)
            if ov != nv:
                rule = status_filter_hit(filters, f, old_item, new_item)
                if rule is not None:
                    if suppressed_out is not None:
                        suppressed_out.append({"key": k, "field": f, "from": ov, "to": nv,
                                               "reason": rule.get("reason") or "unspecified"})
                    continue
                delta_from[f] = ov
                delta_to[f] = nv
        if delta_from:
            changes[k] = (delta_from, delta_to)
    return changes


def build_group_events(source, gname, gcfg, r, judged, d_new, last_delisted,
                       to_events=None, marks=None):
    """比照 process_pair() 內的事件建構邏輯，泛化到支援 STATUS_CHANGED。
    回傳 (new_events, reappeared_from)。

    第四階段（2026-09-07，熔斷語意統一）新增兩個**有預設值**的關鍵字引數，
    純加法、不改變任何既有呼叫端的行為：

      to_events  這組事件要不要進 events.jsonl（True）還是進隔離檔（False）。
                 **未傳入（None）時完全沿用舊行為**：只有 judged=="NORMAL" 才建事件，
                 其餘直接回傳空清單——scripts/selftest.py 既有三處 7 個位置引數的
                 呼叫方式（chk_dd_status_changed／chk_dd_group_reappeared）因此不受
                 影響。process_group_source_pair() 一律明確傳入，走新語意。
      marks      熔斷標記欄位字典（見 breaker_marks()），會 update 進每一筆事件。
                 未傳入時為空字典，事件欄位與本輪之前逐位元組相同。

    last_delisted 只在 to_events 為真時更新，理由與 process_pair() 內同一段註解相同
    （讓 last_delisted 恆等於 events.jsonl 的內容，避免 REAPPEARED 指向只存在於
    隔離檔的 DELISTED）。
    """
    new_events = []
    reappeared_from = {}
    if to_events is None:
        to_events = (judged == "NORMAL")
        if not to_events:
            return new_events, reappeared_from
    marks = marks or {}
    desc_field = gcfg.get("desc_field")
    for k in r["removed_keys"]:
        new_events.append({"date": d_new, "source": source, "group": gname, "key": k,
                            "event": "DELISTED",
                            "from": short_desc_generic(r["keyed_old"].get(k), desc_field), "to": None})
    for k in r["added_keys"]:
        new_events.append({"date": d_new, "source": source, "group": gname, "key": k,
                            "event": "LISTED",
                            "from": None, "to": short_desc_generic(r["keyed_new"].get(k), desc_field)})
        if k in last_delisted:
            reappeared_from[k] = last_delisted[k]
            new_events.append({"date": d_new, "source": source, "group": gname, "key": k,
                                "event": "REAPPEARED", "from": last_delisted[k],
                                "to": short_desc_generic(r["keyed_new"].get(k), desc_field)})
    if to_events:
        for k in r["removed_keys"]:
            last_delisted[k] = d_new

    # 第五階段新增（2026-09-08，任務 0908-1）：把 compare_group() 抵銷掉的每一組
    # 上游改名補寫成一筆第 5 種事件型別 RENAMED。
    #
    # 為什麼第四階段（任務 B）沒寫、本輪要寫：B 刻意把改名只記在人類可讀日報，
    # 代價是「只讀 events.jsonl 的下游會看到一個主鍵無聲消失、另一個主鍵無聲出現」
    # （docs/0907-B-rename-key-report.md §9.4 第 1 項列為待裁示）。使用者裁示
    # 「要看到改名」，因此本輪把改名升格為正式事件。
    #
    # key 取「舊主鍵」而不是新主鍵：舊主鍵才是**從當日快照消失**的那一個，追蹤它的
    # 下游若查不到任何事件，就會誤以為資料靜默遺失——那正是本輪要修掉的失效模式。
    # 新主鍵由同一筆事件的 to_key 明確指出；兩個主鍵字串都在同一行裡，純文字 grep
    # 任一邊都找得到。from_key 與 key 恆等，是刻意保留的自我說明冗餘：events.jsonl
    # 的 key 欄位語意本來就隨 event 型別而異（DELISTED＝消失的鍵、LISTED＝出現的鍵、
    # STATUS_CHANGED＝續存的鍵），RENAMED 一次牽涉兩個鍵，用具名欄位講清楚方向，
    # 下游不必去背「RENAMED 的 key 是哪一邊」。
    #
    # stable_id／stable_id_fields 回答「依據什麼判定這是同一個東西」，讓每一筆
    # RENAMED 都能被獨立複核，不必回頭讀程式碼才知道判定基礎。
    #
    # 未啟用抵銷層的 12 個子集合 renamed_pairs 恆為空 list，這個迴圈一次都不會跑，
    # 產出的事件清單與本輪之前逐位元組相同。
    for k_old, k_new, sid in (r.get("renamed_pairs") or ()):
        new_events.append({"date": d_new, "source": source, "group": gname, "key": k_old,
                            "event": "RENAMED",
                            "from": short_desc_generic(r["keyed_old"].get(k_old), desc_field),
                            "to": short_desc_generic(r["keyed_new"].get(k_new), desc_field),
                            "from_key": k_old, "to_key": k_new, "stable_id": sid,
                            "stable_id_fields": list(gcfg.get("stable_id_fields") or ())})

    # 做法 4【語意過濾】：suppressed 收集被規則抑制、因此不產生 STATUS_CHANGED 的欄位變化，
    # 逐筆寫進 STATUS_FILTER_LOG 事實紀錄檔（見 record_status_filtered()）。
    # process_group_source_pair() 為了統計報表筆數會再呼叫一次 status_changes_for_group()，
    # 那一次不傳 suppressed_out，所以同一筆只會被記錄一次（見該函式 docstring）。
    suppressed = []
    status_changes = status_changes_for_group(gcfg, r["keyed_old"], r["keyed_new"],
                                              suppressed_out=suppressed)
    for s in suppressed:
        record_status_filtered(source, gname, d_new, s)
    for k in sorted(status_changes, key=repr):
        delta_from, delta_to = status_changes[k]
        new_events.append({"date": d_new, "source": source, "group": gname, "key": k,
                            "event": "STATUS_CHANGED", "from": delta_from, "to": delta_to})

    # 熔斷標記統一在最後一次套用，理由同 process_pair()：保住既有事件建構程式碼的
    # 逐字元原貌（scripts/selftest.py 的 mut_dd_group_reappeared 錨點落在其中）。
    if marks:
        for e in new_events:
            e.update(marks)

    return new_events, reappeared_from


def render_group_source_report(source, scfg, d_old, d_new, group_results):
    """多子集合來源的人類可讀日報（changes/<source>/YYYY-MM-DD.md）。
    措辭政策與第一階段 render_report() 完全一致（見該函式 docstring），
    本函式只是把單一子集合的表格擴充成逐子集合各一段。"""
    L = []
    L.append("# 變動偵測 %s %s" % (EMDASH, scfg["label"]))
    L.append("")
    L.append("| 項目 | 值 |")
    L.append("|---|---|")
    L.append("| 來源 | `track-crypto/%s`（%d 個子集合） |" % (source, len(scfg["groups"])))
    L.append("| 比對區間 | `%s` %s `%s` |" % (d_old, "→", d_new))
    L.append("| 改寫 | %s |" % EMDASH)
    L.append("| 偵測時間 | %s |" % datetime.now(timezone.utc).isoformat())
    L.append("")
    # 第五階段改（2026-09-08，任務 0908-1）：這段是**嵌在已公開資料檔裡的 schema 宣告**，
    # 事件型別集合由 4 值擴充成 5 值時必須同步更新，否則已公開的 changes/*.md 會繼續
    # 宣告一個過期的封閉集合。代價是重放會改寫全部既有 changes/*.md（實測 66 份，
    # 見報告 §6.2），這些檔案必須與程式碼同一個 commit 進去。
    L.append("> \u2139\ufe0f **措辭說明**：「自清單消失」「新增」「重新出現」「上游改名」「狀態變化」都只是描述"
              "『這個項目在這兩份快照裡的狀態』的事實，**不代表任何原因推測**。"
              "機器可讀事件型別為 `DELISTED`／`LISTED`／`REAPPEARED`／`RENAMED`／`STATUS_CHANGED`"
              "（型別定義見 `track-crypto/scripts/detect_delistings.py` 檔頭）。"
              "本來源含 %d 個子集合，各子集合的完整性守門與熔斷各自獨立判定，"
              "互不影響（例如某子集合熔斷不會連帶讓其他子集合也不判定）。" % len(scfg["groups"]))
    L.append("")
    for gname, gr in group_results.items():
        r, judged, gcfg = gr["r"], gr["judged"], gr["gcfg"]
        reappeared_from = gr["reappeared_from"]
        n_reappeared = len(reappeared_from)
        status_changes = gr["status_changes"]
        L.append("## 子集合 `%s`" % gname)
        L.append("")
        L.append("| 項目 | 值 |")
        L.append("|---|---|")
        # 第四階段（熔斷語意統一）：與 render_report() 同一條措辭規則，依「事件有沒有
        # 寫進 events.jsonl」決定，不再只看 judged=="NORMAL"。
        _g_to_events = gr.get("to_events", judged == "NORMAL")
        if _g_to_events:
            tag = "" if judged == "NORMAL" else "（熔斷已標記，仍寫入事件流）"
        else:
            tag = "（%s，未寫入事件流%s）" % ("不判定" if judged == "GATE_FAIL" else "熔斷",
                                              "，已隔離" if gr.get("quarantined") else "")
        L.append("| **自清單消失**（實際差集筆數，%s） | **%d**%s |" %
                  ("已寫入事件流為 `DELISTED`" if _g_to_events else "僅供人工參考，非正式事件",
                   len(r["removed_keys"]), tag))
        L.append("| 新增（實際差集筆數，%s） | %d%s |" %
                  ("已寫入事件流為 `LISTED`" if _g_to_events else "僅供人工參考，非正式事件",
                   len(r["added_keys"]), tag))
        L.append("| \u2514\u2500 其中重新出現 | %d%s |" % (n_reappeared, tag))
        if r.get("renamed_pairs"):
            # 第四階段新增（2026-09-07，任務 B）：只有真的抵銷到東西才多這一列，
            # 其餘情況表格逐位元組不變。
            # 第五階段改（2026-09-08，任務 0908-1）：改名現在會寫入事件流為 RENAMED，
            # 措辭比照同表格其他列的既有慣例（依 _g_to_events 分兩種寫法）。
            L.append("| 上游改名（%s） | %d%s |" %
                      ("已寫入事件流為 `RENAMED`" if _g_to_events else "僅供人工參考，非正式事件",
                       len(r["renamed_pairs"]), tag))
        if gcfg.get("status_fields"):
            L.append("| 狀態變化（%s） | %d%s |" %
                      ("已寫入 STATUS_CHANGED" if _g_to_events else "僅供人工參考", len(status_changes), tag))
        L.append("| 去重 dup_keys（前日／當日） | %d / %d |" % (r["dup_old"], r["dup_new"]))
        if r["miss_old"] or r["miss_new"]:
            L.append("| 主鍵缺失 missing_key（前日／當日） | %d / %d |" % (r["miss_old"], r["miss_new"]))
        L.append("| 完整性守門：前日 | %s（%s，n=%r） |" % ("通過" if r["ok_old"] else "**未通過**", r["reason_old"], r["n_old_raw"]))
        L.append("| 完整性守門：當日 | %s（%s，n=%r） |" % ("通過" if r["ok_new"] else "**未通過**", r["reason_new"], r["n_new_raw"]))
        L.append("| 熔斷門檻 | %.1f%%，abs_floor=%d（換算前日筆數為 %.2f 筆；removed 筆數 %d，%s） |" %
                  (gcfg["breaker_pct"], gcfg["abs_floor"], r["threshold_count"], len(r["removed_keys"]),
                   "已觸發" if judged == "BREAKER" else "未觸發"))
        L.append("")
        if judged == "GATE_FAIL":
            L.append("> \u26a0\ufe0f **因完整性守門未通過，本日子集合 `%s` 不做「自清單消失／新增」判定，"
                      "`events.jsonl` 未寫入任何事件。** 上表筆數僅為程式算出的原始差集，"
                      "**未經完整性驗證，不代表正式判定**。" % gname)
            L.append("")
        if judged == "BREAKER":
            L.append("> \U0001f534 **熔斷觸發：子集合 `%s` 的 removed 筆數 %d 超過門檻"
                      "（max(%d, %.1f%%×前日筆數)＝%.2f）。%s** 完整性守門本身通過"
                      "（前後兩側 n 皆在合理範圍內），移除比例超出實測日常區間，"
                      "可能是抓取異常，也可能是真的有大量項目同時自清單消失，"
                      "本程式不自動判斷成因，僅陳述數字。"
                      % (gname, len(r["removed_keys"]), gcfg["abs_floor"], gcfg["breaker_pct"],
                         r["threshold_count"],
                         ("本日事件**照常寫入** `events.jsonl`，每一筆都帶 "
                          "`note`／`breaker_tripped`／`removed_pct`／`breaker_threshold` 標記，"
                          "並已寫 `ALERT-DELIST.md` 要求人工複核。")
                         if _g_to_events else
                         ("同時命中「疑似分頁截斷」結構性指紋，本日事件未寫入 `events.jsonl`，"
                          "改寫入隔離檔 `data/%s/%s` 並寫 `ALERT-DELIST.md` 等待人工確認"
                          "（事實沒有遺失，可人工複核後提升）。" % (source, QUARANTINE_BASENAME))))
            L.append("")
        if r["removed_keys"]:
            L.append("### \u26a0\ufe0f 自清單消失（%d）%s" % (len(r["removed_keys"]),
                      "" if judged != "GATE_FAIL" else "（未經完整性驗證）"))
            L.append("")
            for k in r["removed_keys"]:
                desc = short_desc_generic(r["keyed_old"].get(k), gcfg.get("desc_field"))
                L.append("- `%s`%s" % (k, (" \u2014 " + desc) if desc else ""))
            L.append("")
        if r["added_keys"]:
            extra = "（含 %d 筆重新出現，詳見下一節）" % n_reappeared if n_reappeared else ""
            L.append("### 新增（%d）%s%s" % (len(r["added_keys"]), extra,
                      "" if judged != "GATE_FAIL" else "（未經完整性驗證）"))
            L.append("")
            for k in r["added_keys"]:
                desc = short_desc_generic(r["keyed_new"].get(k), gcfg.get("desc_field"))
                L.append("- `%s`%s" % (k, (" \u2014 " + desc) if desc else ""))
            L.append("")
        if reappeared_from:
            L.append("### \U0001f501 重新出現（%d，事件型別 `REAPPEARED`）" % n_reappeared)
            L.append("")
            for k in sorted(reappeared_from, key=repr):
                desc = short_desc_generic(r["keyed_new"].get(k), gcfg.get("desc_field"))
                L.append("- `%s`（先前於 `%s` 記為自清單消失）%s" % (k, reappeared_from[k], (" \u2014 " + desc) if desc else ""))
            L.append("")
        if r.get("renamed_pairs"):
            # 第四階段新增（2026-09-07，任務 B）：只有抵銷層真的配對到東西時才輸出這一節，
            # 其餘任何情況（含未啟用抵銷層的 12 個子集合）連這個 if 都不會成立，
            # 日報內容與本輪之前逐位元組相同。
            L.append("### \U0001f504 上游改名（%d，事件型別 `RENAMED`）" % len(r["renamed_pairs"]))
            L.append("")
            L.append("以下項目的主鍵字串在兩份快照之間變了，但來源端的穩定識別"
                      "（`%s`）完全相同，判定為**同一個東西被上游改了名字**，"
                      "不是「消失」也不是「新增」，因此**不寫入 `DELISTED`／`LISTED`**，"
                      "改為各寫一筆 `RENAMED` 事件（`key`＝舊主鍵、`to_key`＝新主鍵）。"
                      "只陳述兩個主鍵字串與該穩定識別，不推測上游為什麼改名。"
                      % "＋".join(gcfg.get("stable_id_fields") or ()))
            L.append("")
            for k_old, k_new, sid in r["renamed_pairs"]:
                d_from = short_desc_generic(r["keyed_old"].get(k_old), gcfg.get("desc_field"))
                d_to = short_desc_generic(r["keyed_new"].get(k_new), gcfg.get("desc_field"))
                L.append("- `%s`%s \u2192 `%s`%s（穩定識別 `%s`）"
                          % (k_old, (" \u2014 " + d_from) if d_from else "",
                             k_new, (" \u2014 " + d_to) if d_to else "", sid))
            L.append("")
        if status_changes:
            L.append("### \U0001f501 狀態變化（%d，事件型別 `STATUS_CHANGED`）" % len(status_changes))
            L.append("")
            L.append("以下項目主鍵仍在清單中（未消失），但下列欄位的值改變了。"
                      "只陳述欄位新舊值，不推測原因。")
            L.append("")
            for k in sorted(status_changes, key=repr):
                delta_from, delta_to = status_changes[k]
                desc = short_desc_generic(r["keyed_new"].get(k), gcfg.get("desc_field"))
                changes_txt = "；".join("%s: %r \u2192 %r" % (f, delta_from[f], delta_to[f]) for f in delta_from)
                L.append("- `%s`%s \u2014 %s" % (k, (" (" + desc + ")") if desc else "", changes_txt))
            L.append("")
    L.append("---")
    L.append("")
    L.append("本紀錄由 `track-crypto/scripts/detect_delistings.py` 自動產生（第二階段）。")
    L.append("僅陳述「哪個項目在哪天消失／出現／重新出現／被上游改名／狀態變化」此一事實，**不含任何解讀或評論**。")
    return "\n".join(L) + "\n"


def write_alert_block_group(source, gname, d_new, lines):
    """比照 write_alert_block()（未修改該函式），供第二階段多子集合來源使用，
    差異只在 marker 格式（多帶 group）與檔頭文字（不寫死來源名稱，因為
    ALERT-DELIST.md 是多來源共用檔案）。與 write_alert_block() 各自獨立、
    互不呼叫，也各自獨立判斷檔案是否已存在——若檔案已由另一函式建立，
    這裡不會重寫檔頭，只會照既有慣例把新區塊接在檔尾（見下方判斷式）。"""
    marker = "<!-- detect_delistings:GROUP:%s:%s:%s -->" % (source, gname, d_new)
    existing = ""
    if os.path.exists(ALERT_DELIST):
        with open(ALERT_DELIST, encoding="utf-8") as f:
            existing = f.read()
    if marker in existing:
        return False
    block = "\n".join(
        ["", "## \U0001f534 track-crypto/%s（子集合 %s）自清單消失熔斷警報\uff08%s\uff09" % (source, gname, d_new),
         "", marker, ""] + lines + [""])
    if existing.strip():
        content = existing.rstrip("\n") + "\n" + block
    else:
        header = """# \U0001f534 track-crypto 自清單消失規模異常警報（熔斷）

本檔案由 `track-crypto/scripts/detect_delistings.py` 獨佔寫入，不與任何其他程式共用
（另見 `ALERT.md` 是 `scripts/healthcheck.py` 的獨立輸出，兩者互不相干）。

本檔案記錄「removed 筆數超過熔斷門檻」這個事實（見下方各則區塊的數字），**不代表這些
項目已永久下架**：本程式對「自清單消失」與「永久下架」不畫等號。熔斷只代表移除比例
（或筆數）超出該來源／子集合的實測日常區間，需要人工確認成因，本程式不自動判斷是
抓取異常還是真的有大量項目同時自清單消失。

本檔案涵蓋白名單內所有來源（第一階段 `x402_bazaar`、第二階段甲組其餘 8 個來源），
依「來源＋子集合＋日期」個別記錄每一則熔斷事件，只會新增，不會自動刪除既有區塊。
人工確認後若需歸檔，請自行搬移或加註（例如在行尾加 `<!-- ack:YYYY-MM-DD -->`），
本程式不會自動清除任何已寫入的區塊。
"""
        content = header + block
    with open(ALERT_DELIST, "w", encoding="utf-8") as f:
        f.write(content)
    return True


def process_group_source_pair(source, scfg, f_old, f_new, seen, last_delisted_by_group, gate_fail_seen=None):
    """比照 process_pair()，處理一個多子集合來源的一組相鄰快照，逐子集合各自判定、
    合併寫入同一份 events.jsonl（該來源專屬）與同一份 changes/<source>/YYYY-MM-DD.md。"""
    d_old, d_new = os.path.basename(f_old)[:10], os.path.basename(f_new)[:10]
    j_old, j_new = load(f_old), load(f_new)
    data_old, data_new = j_old.get("data", {}) or {}, j_new.get("data", {}) or {}

    group_results = {}
    all_new_events = []
    quarantine_batches = []  # 第四階段新增：[(gname, judged, reason_text, r, events)]
    for gname, gcfg in scfg["groups"].items():
        r = compare_group(source, gname, gcfg, data_old, data_new)
        # 第五階段新增（2026-09-08，mcp_smithery 納入偵測）：解析器版本下限守門。
        # 只有設定了 "min_parser_version" 的子集合才啟用；其餘 13 個子集合
        # gcfg.get("min_parser_version") 是 None，parser_version_floor_check()
        # 第一行就原樣回傳 (True, "")，r 的既有鍵一個都不會被改到，行為與本輪之前
        # 逐位元組相同（已用全歷史重放驗證，見 docs/0908-3-smithery-detect-report.md §4）。
        pv_ok, pv_reason = parser_version_floor_check(source, gcfg, d_old, d_new)
        r["parser_version_gate_ok"] = pv_ok
        r["parser_version_gate_reason"] = pv_reason
        if not pv_ok:
            # 併進既有的完整性守門結論，不新增第四種 judged 值：judge() 只讀
            # r["gate_ok"]，壓成 False 就會走既有的 GATE_FAIL 路徑
            # ——事件不進 events.jsonl、寫 _gate_fail/gate_skips.jsonl 事實紀錄、
            # 產生人類可讀日報，行為與完整性守門不通過完全一致。
            # ok_old／ok_new 只在「本來通過」時才覆寫，本來就不通過的那一側保留原本的
            # 完整性理由，不損失稽核資訊（render_group_source_report() 會把兩側的
            # reason 都印出來）。
            r["gate_ok"] = False
            for _side in ("old", "new"):
                if r["ok_%s" % _side]:
                    r["ok_%s" % _side] = False
                    r["reason_%s" % _side] = "parser_version 守門：%s" % pv_reason
        judged = judge(r, gcfg)
        last_delisted = last_delisted_by_group.setdefault(gname, {})
        # 第四階段（2026-09-07，熔斷語意統一）：逐子集合各自決定事件的落地去向，
        # 與 process_pair() 同一條規則（NORMAL→events.jsonl；BREAKER 放行→events.jsonl
        # 並標記；BREAKER 未放行／GATE_FAIL→隔離檔）。子集合之間互不影響的既有不變量
        # 不變：release_ok／to_events／marks 全部是這個子集合自己的 r 算出來的。
        release_ok, release_reason = True, ""
        if judged == "BREAKER":
            release_ok, release_reason = breaker_release_check(source, d_old, d_new, r)
        to_events = (judged == "NORMAL") or (judged == "BREAKER" and release_ok)
        marks = breaker_marks(r["removed_rate"], r["threshold_count"]) if judged == "BREAKER" else {}
        r["breaker_release_ok"] = release_ok
        r["breaker_release_reason"] = release_reason
        r["to_events"] = to_events
        new_events, reappeared_from = build_group_events(
            source, gname, gcfg, r, judged, d_new, last_delisted,
            to_events=to_events, marks=marks)
        status_changes = status_changes_for_group(gcfg, r["keyed_old"], r["keyed_new"]) if to_events else {}
        group_results[gname] = {"r": r, "judged": judged, "gcfg": gcfg,
                                 "reappeared_from": reappeared_from if to_events else {},
                                 "quarantined_reappeared_from": {} if to_events else reappeared_from,
                                 "status_changes": status_changes,
                                 "to_events": to_events, "release_reason": release_reason,
                                 "quarantined": (not to_events) and (judged == "BREAKER" or QUARANTINE_GATE_FAIL)}
        if to_events:
            all_new_events.extend(new_events)
        elif new_events and (judged == "BREAKER" or QUARANTINE_GATE_FAIL):
            # GATE_FAIL 是否落隔離檔由 QUARANTINE_GATE_FAIL 控制（預設 False）。
            quarantine_batches.append((gname, judged, release_reason, r, new_events))

    jsonl_path = os.path.join(TRACK_CRYPTO, "data", source, "events.jsonl")
    fresh = write_events(jsonl_path, all_new_events, seen)
    seen.update((e["date"], e["source"], e["group"], e["key"], e["event"]) for e in fresh)

    # 第四階段：不進 events.jsonl 的子集合事件一律寫入隔離檔（同一份檔案、逐來源一份），
    # 事實完整保留、可冪等重跑，理由見 write_quarantine() docstring。
    quarantined_total = 0
    if quarantine_batches:
        q_path = os.path.join(TRACK_CRYPTO, "data", source, QUARANTINE_BASENAME)
        q_seen = load_quarantine_seen(q_path)
        for gname, judged_g, reason_text, rg, evs in quarantine_batches:
            reason_code = "GATE_FAIL" if judged_g == "GATE_FAIL" else "BREAKER_TRUNCATION_SUSPECT"
            txt = reason_text or ("完整性守門不通過：前日(%s)=%s／當日(%s)=%s"
                                  % (d_old, rg["reason_old"], d_new, rg["reason_new"]))
            q = write_quarantine(source, d_new, evs, reason_code, txt, q_seen)
            quarantined_total += len(q)
            if q:
                print("   [QUARANTINE] %s/%s @ %s->%s：%d 筆事件寫入 %s（%s：%s）"
                      % (source, gname, d_old, d_new, len(q), QUARANTINE_BASENAME, reason_code, txt))

    need_report = False
    for gr in group_results.values():
        if gr["judged"] != "NORMAL":
            need_report = True
        elif (gr["r"]["removed_keys"] or gr["r"]["added_keys"] or gr["reappeared_from"]
              or gr["status_changes"] or gr["r"].get("renamed_pairs")):
            # 第四階段新增（2026-09-07，任務 B）：renamed_pairs 也算「今天有事發生」。
            # 只有改名、其餘皆無變動的日子仍要產生日報，否則抵銷層會讓那一天完全沒有
            # 任何可稽核的落地紀錄（事件流本來就不會寫，日報是唯一的痕跡）。
            # 未啟用抵銷層的子集合 renamed_pairs 恆為空，判斷結果與本輪之前相同。
            need_report = True

    entries_for_index = []
    alert_written = False
    if need_report:
        outdir = os.path.join(CHANGES, source)
        os.makedirs(outdir, exist_ok=True)
        out = os.path.join(outdir, "%s.md" % d_new)
        with open(out, "w", encoding="utf-8") as f:
            f.write(render_group_source_report(source, scfg, d_old, d_new, group_results))

        # 第四階段：統計口徑由「judged == NORMAL」改為「事件真的有進 events.jsonl」
        # （to_events），因為熔斷放行後事件是有寫的，索引列不能再把它算成 0。
        total_removed = sum(len(gr["r"]["removed_keys"]) for gr in group_results.values() if gr["to_events"])
        total_added = sum(len(gr["r"]["added_keys"]) for gr in group_results.values() if gr["to_events"])
        total_reappeared = sum(len(gr["reappeared_from"]) for gr in group_results.values() if gr["to_events"])
        total_status = sum(len(gr["status_changes"]) for gr in group_results.values() if gr["to_events"])
        non_normal = [g for g, gr in group_results.items() if gr["judged"] != "NORMAL"]
        # 第五階段改（2026-09-08，任務 0908-1）：口徑由 judged=="NORMAL" 對齊成
        # to_events，與上面 4 行 total_* 完全一致。理由：RENAMED 現在是真的會寫進
        # events.jsonl 的事件，落地與否由 to_events 決定（BREAKER 放行時也會寫），
        # 索引列若還用 judged=="NORMAL" 就會出現「事件流有 RENAMED、索引列寫 0」的
        # 矛盾。judged=="NORMAL" 蘊含 to_events==True，因此這個改動只在
        # 「BREAKER 但放行」時才有差異，其餘情況索引列逐位元組不變。
        total_renamed = sum(len(gr["r"].get("renamed_pairs") or ())
                            for gr in group_results.values() if gr["to_events"])
        removed_cell = str(total_removed)
        added_cell = str(total_added)
        if total_reappeared:
            added_cell += "（含 %d 筆重新出現）" % total_reappeared
        if total_status:
            removed_cell += "；狀態變化 %d" % total_status
        if total_renamed:
            # 第四階段新增（2026-09-07，任務 B）：比照上一行「；狀態變化 %d」的既有慣例，
            # 只有真的抵銷到東西才附註，其餘日期的索引列逐位元組不變。
            removed_cell += "；上游改名抵銷 %d" % total_renamed
        if non_normal:
            # 後綴語意（與 process_pair() 同一條規則）：事件有寫進 events.jsonl → 「已標記」；
            # 有寫進隔離檔 → 「已隔離」；兩者都沒有（GATE_FAIL 且 QUARANTINE_GATE_FAIL=False，
            # 即預設情況）→ 不加後綴，索引列維持本輪之前的原樣。
            def _suffix(gr_):
                if gr_["to_events"]:
                    return "，已標記"
                return "，已隔離" if gr_.get("quarantined") else ""
            tag = "；".join("%s:%s%s" % (g, group_results[g]["judged"], _suffix(group_results[g]))
                            for g in non_normal)
            removed_cell += "（%s）" % tag
        entries_for_index.append(
            "| %s | `track-crypto/%s` | %s | %s | %s | [紀錄](changes/%s/%s.md) |"
            % (d_new, source, EMDASH, removed_cell, added_cell, source, d_new))

        for gname, gr in group_results.items():
            if gr["judged"] == "GATE_FAIL":
                # 記錄 GATE_FAIL 事實供 healthcheck.py 告警用（specs/SPEC-gate-dedup.md），
                # 手法與 process_pair() 的同一段落完全對稱，差別只在欄位來源（ok_old／
                # ok_new／n_old_raw／n_new_raw 是 compare_group() 的回傳欄位，見該函式）。
                r, gcfg = gr["r"], gr["gcfg"]
                reasons = []
                if not r["ok_old"]:
                    reasons.append("前日(%s)：%s（n=%r）" % (d_old, r["reason_old"], r["n_old_raw"]))
                if not r["ok_new"]:
                    reasons.append("當日(%s)：%s（n=%r）" % (d_new, r["reason_new"], r["n_new_raw"]))
                record_gate_fail(source, gname, d_new, d_old, "；".join(reasons),
                                  r["n_old_raw"], r["n_new_raw"], gate_fail_seen)
            if gr["judged"] == "BREAKER":
                r, gcfg = gr["r"], gr["gcfg"]
                lines = [
                    "檢查時間（UTC）：%s" % datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "",
                    "| 項目 | 值 |",
                    "|---|---|",
                    "| 來源 | `track-crypto/%s`／子集合 `%s` |" % (source, gname),
                    "| 比對區間 | `%s` \u2192 `%s` |" % (d_old, d_new),
                    "| removed 筆數 | %d（門檻 max(%d, %.1f%%\u00d7前日筆數)\uff1d%.2f） |"
                    % (len(r["removed_keys"]), gcfg["abs_floor"], gcfg["breaker_pct"], r["threshold_count"]),
                    "| 前日筆數（去重後） | %d |" % len(r["keyed_old"]),
                ]
                if gr["to_events"]:
                    lines += [
                        "| 處置 | **標記但不否決**：事件已寫入 `data/%s/events.jsonl` |" % source,
                        "| 放行依據 | %s |" % gr["release_reason"],
                        "",
                        ("本日 `%s`／子集合 `%s` 的「自清單消失」判定**照常寫入** "
                         "`data/%s/events.jsonl`，但該組轉換產生的每一筆事件都額外帶 "
                         "`note:\"anomalous_scale\"`、`breaker_tripped:true`、`removed_pct`、"
                         "`breaker_threshold` 四個欄位，**需要人工複核**。移除比例超出實測日常"
                         "區間，可能是抓取異常，也可能是真的有大量項目同時自清單消失，"
                         "本程式不對成因下判斷（零觀點鐵律）。詳見 `changes/%s/%s.md`。"
                         "若複核後判定為假事件，請用 `scripts/apply_correction.py` 更正。"
                         % (source, gname, source, source, d_new)),
                    ]
                else:
                    lines += [
                        "| 處置 | **隔離**：事件已寫入 `data/%s/%s`，未進 events.jsonl |"
                        % (source, QUARANTINE_BASENAME),
                        "| 隔離原因 | %s |" % gr["release_reason"],
                        "",
                        ("本日 `%s`／子集合 `%s` 的「自清單消失」判定**未寫入** "
                         "`data/%s/events.jsonl`，因為除了移除規模超過熔斷門檻之外，"
                         "還同時命中「疑似分頁截斷」的結構性指紋（見上表）。事件事實"
                         "**沒有遺失**，已完整寫入隔離檔 `data/%s/%s`，人工複核確認不是"
                         "抓取問題後可提升回事件流。詳見 `changes/%s/%s.md`。"
                         % (source, gname, source, source, QUARANTINE_BASENAME, source, d_new)),
                    ]
                if write_alert_block_group(source, gname, d_new, lines):
                    alert_written = True

    return group_results, fresh, entries_for_index, alert_written


def snapshots(source):
    """每個 UTC 日期只取最後一份快照（同日多份是重跑產物，不是改寫事件）。
    邏輯抄自 scripts/detect_changes.py 的 snapshots()：sorted(glob(...)) 後
    以檔名前 10 碼（YYYY-MM-DD）為 key 覆蓋寫入 dict，同日較晚的檔名（含 T 時分秒後綴）
    在字典序上排在無後綴的檔名之後，故迴圈跑完後留下的是「當日最後一次成功寫入」。"""
    d = os.path.join(TRACK_CRYPTO, "data", source)
    if not os.path.isdir(d):
        return []
    per_day = {}
    for p in sorted(glob.glob(os.path.join(d, "*.json.gz"))):
        per_day[os.path.basename(p)[:10]] = p
    return [per_day[k] for k in sorted(per_day)]


def load(p):
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return json.load(f)


def completeness(data, cfg):
    """完整性守門（2026-09-07 改寫，見 SOURCES 設定表上方的完整推導）。
    回傳 (ok, reported_total, n_items, reason)。

    【為什麼改寫】舊版做的是 `data.total != len(items)` -> fail。但 adapter 寫進
    data.total 的值**就是** len(items)，被檢查的數字與自報的數字是同一個，
    這個判斷式永遠為假、永遠不會 return False —— 是一個**恆真式守門**，
    對分頁截斷零防護力（實證：13 份歷史快照全部 total == len(items)，
    見 docs/0907-events-audit-0904-0907.md §8.1）。舊版的 "total_match" 這個
    名字與 reason 字串一併**移除**，不留假的保護感。

    【新版兩條路徑】
      A. 新快照（adapter PARSER_VERSION>=2，data 有 reported_total 欄位）：
         走 reported_total_match —— 拿**上游 pagination.total** 跟 len(items) 比，
         兩者來源互相獨立，才有鑑別力。三道檢查依序：
           A1. reported_total 必須是正整數（缺失/型別錯/<=0 一律 fail-closed）。
           A2. data.truncated 必須明確是布林 False（缺失/True 一律 fail-closed，
               比照 completeness_group() 的 tolerant_total_match 既有寫法）。
           A3. |reported_total - len(items)| 不得超過
               max(tolerance_abs_floor, tolerance_pct% × reported_total)。
      B. 舊快照（2026-09-07 之前，沒有 reported_total 欄位）：
         走 legacy_range_check —— 只能退回「筆數是否落在實測歷史區間」。
         這是**相容分支**，鑑別力明確較弱（見 SOURCES 設定表註解的誠實揭露），
         目的是不讓歷史重放整批變成 GATE_FAIL。

    回傳值第二格語意也跟著變了：舊版是 data.total（＝len(items)，沒有資訊量），
    新版是 reported_total（上游自報總數；走 B 路徑時為 None，代表這份舊快照
    根本沒有上游總數可比）。呼叫端 compare_pair() 已同步把它改名為
    total_old／total_new 的來源，render_report()／write_alert_block() 的顯示
    文字也已同步改成「上游自報總數」。
    """
    items = data.get("items")
    if not isinstance(items, list):
        return False, None, None, "items 缺失或非清單"
    n = len(items)

    reported_total = data.get(cfg["reported_total_field"])

    # --- 路徑 B：舊快照相容（沒有上游自報總數可用）---
    if reported_total is None:
        lo, hi = cfg["legacy_range"]
        if n < lo or n > hi:
            return False, None, n, ("legacy_range_check[%d,%d] 未通過：len(items)=%d 超出實測合理區間"
                                     % (lo, hi, n))
        return True, None, n, "legacy_range_check[%d,%d]" % (lo, hi)

    # --- 路徑 A：新快照，拿上游自報總數比對 ---
    if not isinstance(reported_total, int) or isinstance(reported_total, bool) or reported_total <= 0:
        return False, reported_total, n, ("%s 非正整數（%r），fail-closed"
                                           % (cfg["reported_total_field"], reported_total))
    tr_field = cfg["truncated_field"]
    tr = data.get(tr_field)
    if tr is not False:
        return False, reported_total, n, ("%s(%r) 非布林 False（缺失/True 一律 fail-closed 視為不完整）"
                                           % (tr_field, tr))
    gap = abs(reported_total - n)
    limit = max(cfg["tolerance_abs_floor"], cfg["tolerance_pct"] / 100.0 * reported_total)
    if gap > limit:
        return False, reported_total, n, ("%s(%d) 與 len(items)(%d) 相差 %d 筆，超過容忍度 %.1f 筆"
                                           "（max(%d, %.2f%%×%d)）"
                                           % (cfg["reported_total_field"], reported_total, n, gap,
                                              limit, cfg["tolerance_abs_floor"],
                                              cfg["tolerance_pct"], reported_total))
    return True, reported_total, n, ("reported_total_match(gap=%d,limit=%.1f)" % (gap, limit))


def dedup(items, key_field):
    """同鍵取最後出現的一筆。回傳 (dict[key->item], dup_keys 數量, missing_key 數量)。
    missing_key：主鍵欄位缺失或為空值的筆數，這類項目不參與比對（不計入 dup_keys，
    也不計入任何一邊的集合），x402_bazaar 實測 08-26～09-01 全部為 0。

    key_field 型別（第三階段新增，見 specs/SPEC-detect-phase3.md、本機
    docs/detect-phase3-report.md §2.2）：
      - str（既有行為，完全不變）：k = it.get(key_field)。
      - tuple（本輪新增，複合主鍵，目前只有 crypto_project_liveness 使用
        ("name", "date")）：把 tuple 內各欄位的值依序取出，任一欄位缺失或為
        空字串則整筆視為 missing（比照單一欄位鍵既有規則）；字串型別的欄位值
        一律先轉小寫再組字串鍵，其餘型別（例如 date 是 int）原樣轉字串——
        用 "\x1f"（ASCII Unit Separator，正常業務資料不會出現的字元）連接，
        確保複合鍵仍是單一、可雜湊、可 JSON 往返（json.dumps/loads 後仍能繼續
        當 dict 鍵用於 REAPPEARED 判定）的純字串，不是 JSON 陣列。
        大小寫正規化理由（實測發現，非規格書原始要求）：crypto_project_liveness
        2026-08-29 出現同一筆歷史事件（同 date、同 classification/technique/
        amount/chain）的 name 欄位從 "Saturn" 修正為 "SATURN"，純大小寫變更；
        若不忽略大小寫，複合鍵集合差會把這筆事實上沒有變化的紀錄誤判為
        「一筆消失＋一筆新增」，屬於必須修正的假消失風險，見報告 §2.2。
    """
    d = {}
    missing = 0
    for it in items:
        if not isinstance(it, dict):
            missing += 1
            continue
        if isinstance(key_field, tuple):
            parts = []
            ok = True
            for f in key_field:
                v = it.get(f)
                if v is None or v == "":
                    ok = False
                    break
                parts.append(v.lower() if isinstance(v, str) else v)
            if not ok:
                missing += 1
                continue
            k = "\x1f".join(str(p) for p in parts)
        else:
            k = it.get(key_field)
            if not k:
                missing += 1
                continue
        d[k] = it  # 同鍵取最後出現的一筆
    dup_keys = len(items) - len(d) - missing
    return d, dup_keys, missing


def short_desc(item, n=120):
    """給事件流／報告用的簡短描述，只取 description 欄位前 n 字，不落地完整 item
    （accepts/extensions/quality 等欄位可能有數 KB 巢狀 schema，事件流只記事實即可）。"""
    s = (item or {}).get("description") or ""
    s = " ".join(str(s).split())
    return (s[:n] + "\u2026") if len(s) > n else s


def compare_pair(source, cfg, f_old, f_new):
    """回傳這一對快照的完整比對結果字典。不論是否通過守門／熔斷都回傳，
    由呼叫端決定要不要落地事件／報告（判定邏輯與輸出邏輯分離，方便測試）。"""
    d_old, d_new = os.path.basename(f_old)[:10], os.path.basename(f_new)[:10]
    j_old, j_new = load(f_old), load(f_new)
    data_old, data_new = j_old.get("data", {}) or {}, j_new.get("data", {}) or {}

    ok_old, total_old, n_old, reason_old = completeness(data_old, cfg)
    ok_new, total_new, n_new, reason_new = completeness(data_new, cfg)
    gate_ok = ok_old and ok_new

    keyed_old, dup_old, miss_old = dedup(data_old.get("items") or [], cfg["key_field"])
    keyed_new, dup_new, miss_new = dedup(data_new.get("items") or [], cfg["key_field"])

    added_keys = sorted(set(keyed_new) - set(keyed_old))
    removed_keys = sorted(set(keyed_old) - set(keyed_new))
    removed_rate = (len(removed_keys) / len(keyed_old) * 100.0) if keyed_old else 0.0
    breaker = gate_ok and (removed_rate > cfg["breaker_pct"])
    # 第四階段（熔斷語意統一）新增的兩個純加法欄位，不參與上面任何既有判定：
    #   tail_run／tail_cover：分頁截斷指紋，見 removal_tail_metrics()。
    #   threshold_count：把第一階段的「百分比門檻」換算成筆數，讓事件標記欄位
    #                    breaker_threshold 與第二階段、與 cex_events.py 同單位。
    tail_run, tail_cover = removal_tail_metrics(keyed_old, removed_keys)
    threshold_count = cfg["breaker_pct"] / 100.0 * len(keyed_old)

    return {
        "source": source, "d_old": d_old, "d_new": d_new, "f_old": f_old, "f_new": f_new,
        # ok_old／ok_new 為 2026-09-07 新增（純加法，比照 compare_group() 既有做法）：
        # 原本 render_report()／write_alert_block() 是用 `reason == "total_match"` 這個
        # **字串字面值**回推有沒有通過守門；完整性守門改寫後 reason 文字不再只有一種，
        # 用字串比對會把「通過」誤印成「未通過」。改成直接帶出布林結果，語意正確且不再
        # 依賴 reason 的措辭。
        "gate_ok": gate_ok, "ok_old": ok_old, "ok_new": ok_new,
        "reason_old": reason_old, "reason_new": reason_new,
        "total_old": total_old, "total_new": total_new, "n_old": n_old, "n_new": n_new,
        "dup_old": dup_old, "dup_new": dup_new, "miss_old": miss_old, "miss_new": miss_new,
        "keyed_old": keyed_old, "keyed_new": keyed_new,
        "added_keys": added_keys, "removed_keys": removed_keys,
        "removed_rate": removed_rate, "breaker": breaker,
        "tail_run": tail_run, "tail_cover": tail_cover, "threshold_count": threshold_count,
    }


def judge(r, cfg):
    """回傳 "NORMAL" / "GATE_FAIL" / "BREAKER"。"""
    if not r["gate_ok"]:
        return "GATE_FAIL"
    if r["breaker"]:
        return "BREAKER"
    return "NORMAL"


def render_report(source, cfg, r, judged):
    """人類可讀日報（changes/<source>/YYYY-MM-DD.md）。

    措辭政策（本輪修正，父代理裁示「採方案 1＋3，不採方案 2」，見檔頭「事件型別語意
    定義」小節、docs/detect-phase1-report.md §9）：本函式產生的內容全面把「下架」改為
    「自清單消失」這類只描述觀察事實的用詞，並在表格與清單旁註明對應的機器可讀事件
    型別名稱（DELISTED／LISTED／REAPPEARED，型別名稱本身不變），避免讀者把「自清單
    消失」誤讀成「永久下架」。
    """
    reappeared_from = r.get("reappeared_from") or {}
    n_reappeared = len(reappeared_from)
    L = []
    L.append("# 變動偵測 %s %s" % (EMDASH, cfg["label"]))
    L.append("")
    L.append("| 項目 | 值 |")
    L.append("|---|---|")
    L.append("| 來源 | `track-crypto/%s` |" % source)
    L.append("| 比對區間 | `%s` %s `%s` |" % (r["d_old"], "→", r["d_new"]))
    L.append("| 改寫 | %s |" % EMDASH)
    # 第四階段（熔斷語意統一）：措辭一律依「事件到底有沒有寫進 events.jsonl」決定，
    # 不再只看 judged=="NORMAL"——熔斷放行後事件是有寫的，舊措辭會變成假話。
    _to_events = r.get("to_events", judged == "NORMAL")
    if _to_events:
        removed_note = "" if judged == "NORMAL" else "（熔斷已標記，仍寫入事件流）"
        _wrote = ("已寫入事件流為 `DELISTED`", "已寫入事件流為 `LISTED`", "已另寫入事件流為 `REAPPEARED`")
    else:
        removed_note = "（%s，未寫入事件流%s）" % (
            "不判定" if judged == "GATE_FAIL" else "熔斷",
            "，已隔離" if r.get("quarantined") else "")
        _wrote = ("僅供人工參考，非正式事件",) * 3
    added_note = removed_note
    L.append("| **自清單消失**（實際差集筆數，%s） | **%d**%s |" %
              (_wrote[0], len(r["removed_keys"]), removed_note))
    L.append("| 新增（實際差集筆數，%s） | %d%s |" %
              (_wrote[1], len(r["added_keys"]), added_note))
    L.append("| └─ 其中重新出現（先前記為自清單消失，本次又出現，%s） | %d%s |" %
              (_wrote[2], n_reappeared, added_note))
    L.append("| 去重 dup_keys（前日／當日） | %d / %d |" % (r["dup_old"], r["dup_new"]))
    if r["miss_old"] or r["miss_new"]:
        L.append("| 主鍵缺失 missing_key（前日／當日） | %d / %d |" % (r["miss_old"], r["miss_new"]))
    L.append("| 完整性守門：前日 | %s（%s，上游自報總數=%r, len(items)=%r） |" %
              ("通過" if r["ok_old"] else "**未通過**", r["reason_old"], r["total_old"], r["n_old"]))
    L.append("| 完整性守門：當日 | %s（%s，上游自報總數=%r, len(items)=%r） |" %
              ("通過" if r["ok_new"] else "**未通過**", r["reason_new"], r["total_new"], r["n_new"]))
    L.append("| 熔斷門檻 | %.1f%%（removed 率 %.2f%%，%s） |" %
              (cfg["breaker_pct"], r["removed_rate"], "已觸發" if judged == "BREAKER" else "未觸發"))
    L.append("| 偵測時間 | %s |" % datetime.now(timezone.utc).isoformat())
    L.append("")
    L.append("> ℹ️ **措辭說明**：「自清單消失」「新增」「重新出現」都只是描述"
              "『這個 resource 有沒有出現在這兩份快照裡』的事實，**不代表服務永久關閉或全新上線**"
              "——同一資料源實測約 5%～17%（依觀察窗長短）的「自清單消失」案例會在數天內重新出現"
              "（見本機 docs/detect-phase1-report.md §5）。機器可讀事件型別名稱維持"
              "`DELISTED`／`LISTED`／`REAPPEARED` 不變，僅在此以更準確的中文描述呈現，"
              "本表與下方清單皆為事實紀錄，不做原因推測。")
    L.append("")
    if judged == "GATE_FAIL":
        L.append("> ⚠️ **因完整性守門未通過，本日不做「自清單消失／新增」判定，`events.jsonl` 未寫入任何事件。** "
                  "上游自報總數 `data.reported_total`（Coinbase CDP `pagination.total`）與 `len(items)`"
                  "（去重前）相差超過容忍度、或 `data.truncated` 非 `false`、或該欄位缺失；"
                  "2026-09-07 之前的舊快照沒有 `reported_total`，改判筆數是否落在實測合理區間。"
                  "上表的自清單消失／新增筆數僅為程式算出的原始差集，**未經完整性驗證，不代表正式判定**，"
                  "僅供人工評估用。")
        L.append("")
    if judged == "BREAKER" and _to_events:
        L.append("> 🔴 **熔斷觸發：removed 率 %.2f%% 超過門檻 %.1f%%。本日事件**照常寫入** "
                  "`events.jsonl`，但每一筆都帶 `note:\"anomalous_scale\"`／`breaker_tripped:true`／"
                  "`removed_pct`／`breaker_threshold`，並已寫 `ALERT-DELIST.md` 要求人工複核。** "
                  "完整性守門本身是通過的（`total == len(items)` 兩側皆相符），"
                  "但移除比例超出日常區間，可能是抓取異常，也可能是真的有大量 resource 同時"
                  "自清單消失，本程式不自動判斷成因，僅陳述數字。"
                  % (r["removed_rate"], cfg["breaker_pct"]))
        L.append("")
    if judged == "BREAKER" and not _to_events:
        L.append("> 🔴 **熔斷觸發：removed 率 %.2f%% 超過門檻 %.1f%%，且同時命中「疑似分頁截斷」"
                  "結構性指紋，本日事件未寫入 `events.jsonl`，改寫入隔離檔 "
                  "`data/%s/%s` 並寫 `ALERT-DELIST.md` 等待人工確認。** 事件事實沒有遺失，"
                  "人工複核確認不是抓取問題後可提升回事件流。"
                  % (r["removed_rate"], cfg["breaker_pct"], source, QUARANTINE_BASENAME))
        L.append("")
    if r["removed_keys"]:
        L.append("## ⚠️ 自清單消失（%d）%s" % (len(r["removed_keys"]),
                  "" if judged != "GATE_FAIL" else "（未經完整性驗證）"))
        L.append("")
        for k in r["removed_keys"]:
            desc = short_desc(r["keyed_old"].get(k))
            L.append("- `%s`%s" % (k, (" — " + desc) if desc else ""))
        L.append("")
    if r["added_keys"]:
        extra = "（含 %d 筆重新出現，詳見下一節）" % n_reappeared if n_reappeared else ""
        L.append("## 新增（%d）%s%s" % (len(r["added_keys"]), extra,
                  "" if judged != "GATE_FAIL" else "（未經完整性驗證）"))
        L.append("")
        for k in r["added_keys"]:
            desc = short_desc(r["keyed_new"].get(k))
            L.append("- `%s`%s" % (k, (" — " + desc) if desc else ""))
        L.append("")
    if reappeared_from:
        L.append("## 🔁 重新出現（%d，事件型別 `REAPPEARED`）" % n_reappeared)
        L.append("")
        L.append("以下 resource 先前曾被記錄為「自清單消失」（`DELISTED`），本次比對於 `%s` "
                  "重新出現於清單中。「先前消失日期」直接取自上一筆 `DELISTED` 事件的日期，"
                  "方便讀者自行計算消失了幾天；本節純粹陳述這個事實，不代表也不推測這段期間"
                  "發生了什麼事。" % r["d_new"])
        L.append("")
        for k in sorted(reappeared_from):
            desc = short_desc(r["keyed_new"].get(k))
            L.append("- `%s`（先前於 `%s` 記為自清單消失）%s" % (k, reappeared_from[k], (" — " + desc) if desc else ""))
        L.append("")
    L.append("---")
    L.append("")
    L.append("本紀錄由 `track-crypto/scripts/detect_delistings.py` 自動產生。")
    L.append("僅陳述「哪個 resource 在哪天消失／出現／重新出現」此一事實，**不含任何解讀或評論**。")
    return "\n".join(L) + "\n"


def load_seen(jsonl_path):
    seen = set()
    if os.path.exists(jsonl_path):
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                    seen.add((e["date"], e["source"], e["group"], e["key"], e["event"]))
                except Exception:
                    pass
    return seen


def write_events(jsonl_path, new_events, seen):
    fresh = [e for e in new_events
             if (e["date"], e["source"], e["group"], e["key"], e["event"]) not in seen]
    if fresh:
        os.makedirs(os.path.dirname(jsonl_path), exist_ok=True)
        with open(jsonl_path, "a", encoding="utf-8") as f:
            for e in fresh:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return fresh


def load_gate_fail_seen():
    """讀 GATE_FAIL_LOG 目前所有 (date, source, group, reason) 鍵值，供 record_gate_fail()
    冪等判斷用。比照 load_seen() 同一手法（同一份檔案讀取＋容錯解析慣例），
    唯一差別是鍵值定義（見 record_gate_fail() docstring）。"""
    seen = set()
    if os.path.exists(GATE_FAIL_LOG):
        with open(GATE_FAIL_LOG, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    g = json.loads(line)
                    seen.add((g["date"], g["source"], g["group"], g["reason"]))
                except Exception:
                    pass
    return seen


def record_gate_fail(source, group, date, from_date, reason, n_old, n_new, seen=None):
    """冪等記錄一筆 GATE_FAIL（完整性守門不通過）事實到 GATE_FAIL_LOG，供
    scripts/healthcheck.py 的 check_delist_gate_fail() 讀取後判斷是否要產生
    ALERT-DELISTGATE.md（見該常數定義處註解、specs/SPEC-gate-dedup.md）。

    去重鍵 (date, source, group, reason)：main() 的 SOURCES／GROUP_SOURCES 兩個迴圈
    都會對「完整歷史」重新配對計算（snapshots() 回傳全部歷史快照，不是只算最新一天），
    若不去重，同一筆 GATE_FAIL 事實會被每天重複附加——這正是本次派工另一項任務
    （gate_skips.jsonl 缺去重，見 scripts/cex_events.py）教訓的直接應用：這份全新的
    紀錄檔從第一天就內建去重，不重蹈覆轍。只用附加模式（"a"）寫檔，從不覆寫或刪減
    既有內容。

    seen：呼叫端傳入、原地更新的集合，供跨多次呼叫共用同一份已知鍵值（main() 在兩個
    迴圈開始前呼叫 load_gate_fail_seen() 一次、共用同一份 set 物件傳給
    process_pair()／process_group_source_pair()，理由是兩者寫的是同一份共用檔案，
    比照 ALERT_DELIST 本來就是兩個迴圈共用同一個輸出檔案的既有設計）。
    未傳入（None，例如既有呼叫端／測試直接呼叫本函式而不先呼叫 load_gate_fail_seen()）
    時，退化成每次呼叫都重新讀檔案判斷——正確性不變，只是失去跨呼叫共用記憶體狀態的
    效能好處，對 GATE_FAIL 這種罕見事件（實測至今 0 次觸發）的呼叫頻率而言可忽略；
    這個預設值的存在是為了不必修改任何既有呼叫端或既有 selftest 檢查的既有呼叫方式
    （純加法，比照本檔案一貫的相容性原則）。"""
    if seen is None:
        seen = load_gate_fail_seen()
    key = (date, source, group, reason)
    if key in seen:
        return False
    os.makedirs(os.path.dirname(GATE_FAIL_LOG), exist_ok=True)
    rec = {"date": date, "source": source, "group": group, "from_date": from_date,
           "reason": reason, "n_old": n_old, "n_new": n_new}
    with open(GATE_FAIL_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    seen.add(key)
    try:
        _lines = sum(1 for _ in open(GATE_FAIL_LOG, encoding="utf-8"))
    except OSError:
        _lines = None
    if _lines is not None and _lines >= GATE_FAIL_LOG_SIZE_HINT_LINES:
        print("   [NOTE] %s 已累積 %d 行（提示門檻 %d），可考慮執行 "
              "scripts/dedup_gate_skips.py --file %s --key date,source,group,reason "
              "--apply --archive-before <YYYY-MM-DD> 歸檔舊紀錄"
              % (GATE_FAIL_LOG, _lines, GATE_FAIL_LOG_SIZE_HINT_LINES, GATE_FAIL_LOG))
    return True


# ---------------------------------------------------------------------------
# 做法 4【語意過濾】的事實紀錄（STATUS_FILTER_LOG）
# ---------------------------------------------------------------------------

_STATUS_FILTER_SEEN = None  # 行程內快取，見 load_status_filter_seen()


def load_status_filter_seen(refresh=False):
    """讀 STATUS_FILTER_LOG 目前所有 (date, source, group, key, field) 鍵值，供
    record_status_filtered() 冪等判斷用。手法比照 load_seen()／load_gate_fail_seen()
    （同一份容錯解析慣例），差別只在鍵值定義與「行程內快取」。

    為什麼加快取（load_gate_fail_seen() 沒有）：GATE_FAIL 是罕見事件（實測至今 4 筆），
    每次呼叫重讀整份檔案的成本可忽略；語意過濾的抑制筆數是「每天數十到數百筆 × 全歷史
    重放」的量級（實測全歷史 251 筆），若每筆都重讀整份檔案會變成 O(n^2)。快取只在
    本行程內有效，且 record_status_filtered() 寫入後會同步更新快取，不會不一致。
    refresh=True 可強制重讀（供測試或呼叫端明確需要時使用）。"""
    global _STATUS_FILTER_SEEN
    if _STATUS_FILTER_SEEN is not None and not refresh:
        return _STATUS_FILTER_SEEN
    seen = set()
    if os.path.exists(STATUS_FILTER_LOG):
        with open(STATUS_FILTER_LOG, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    g = json.loads(line)
                    seen.add((g["date"], g["source"], g["group"], g["key"], g["field"]))
                except Exception:
                    pass
    _STATUS_FILTER_SEEN = seen
    return seen


def record_status_filtered(source, group, date, s, seen=None):
    """冪等記錄一筆「被 status_filters 語意過濾抑制、因此沒有寫進 events.jsonl」的欄位變化。

    這份紀錄是語意過濾可稽核的關鍵：抑制事件不等於丟掉資料——被抑制的每一筆的
    key／欄位／新舊值／理由碼都完整保留在 STATUS_FILTER_LOG，任何人都能重新檢視
    「這條規則到底濾掉了什麼」，必要時可反推回事件流。設計與 record_gate_fail() 同構
    （只用附加模式 "a" 寫檔、從不覆寫或刪減、去重鍵含 date 以支援全歷史重放）。

    s：status_changes_for_group() 放進 suppressed_out 的 dict，含 key／field／from／to／reason。"""
    if seen is None:
        seen = load_status_filter_seen()
    key = (date, source, group, s["key"], s["field"])
    if key in seen:
        return False
    os.makedirs(os.path.dirname(STATUS_FILTER_LOG), exist_ok=True)
    rec = {"date": date, "source": source, "group": group, "key": s["key"],
           "field": s["field"], "from": s["from"], "to": s["to"], "reason": s["reason"]}
    with open(STATUS_FILTER_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    seen.add(key)
    return True


# ---------------------------------------------------------------------------
# 做法 2【抖動標記 flap detection】
# ---------------------------------------------------------------------------

FLAP_MARK_FIELDS = ("flapped", "flap_fields", "flap_with")


def _flap_val(v):
    """把欄位值正規化成可雜湊、可比較的字串（狀態旗標可能是 bool／字串／None，
    未來也可能出現巢狀值）。只用於抖動配對的相等比較，不影響事件內容本身。"""
    return json.dumps(v, ensure_ascii=False, sort_keys=True)


def _day_gap(d1, d2):
    """兩個 YYYY-MM-DD 字串相差幾個日曆日；任一側格式不合回傳 None（呼叫端當作不可配對）。"""
    try:
        return (datetime.strptime(d2, "%Y-%m-%d") - datetime.strptime(d1, "%Y-%m-%d")).days
    except Exception:
        return None


def flap_marks(events, window_days=FLAP_WINDOW_DAYS):
    """做法 2 的核心判定（純函式，無 I/O、無副作用）。

    輸入：一串事件 dict（同一個 source 的 events.jsonl 全部內容即可，非 STATUS_CHANGED
          會自動略過）。輸出：{(date, group, key): {"fields": [...], "with": [日期字串...]}}。

    判定：把每筆 STATUS_CHANGED 的 from/to 字典拆成逐欄位的轉換 (date, 舊值, 新值)，
    對同一個 (group, key, 欄位) 的轉換序列，若存在兩筆 t1(a→b)、t2(b→a) 且
    0 < 日期差 <= window_days，就把**兩筆事件**都標記起來，並互相記下對方的日期。
    「翻回原值」的定義是嚴格的值相等（a、b 兩個值互換），不是「有變化就算」。

    為什麼標記兩筆而不是只標第二筆：兩天的事件各自都如實描述了「快照之間欄位值確實
    不同」這個事實，第一筆並沒有比第二筆更可信；抖動是**這一對**的性質，不是單筆的性質。

    為什麼 flap_with 是日期清單而不是單一日期：events.jsonl 的去重鍵是
    (date, source, group, key, event)，同一個 (group, key) 的兩筆 STATUS_CHANGED 之間
    唯一不同的成分就是 date，所以「對方的日期」已足以唯一指出對應的那一筆事件
    （沿用 REAPPEARED 的 "from" 欄位放日期字串的既有慣例）。用清單是因為連續震盪時
    （例如連三天 a→b→a→b）中間那筆會同時與前後兩筆配對，單一值會漏掉資訊。

    決定性：不依賴輸入順序（內部先排序），不做貪婪「配到就跳出」，同一組輸入永遠得到
    同一組輸出——這是 annotate_flaps() 冪等的前提。"""
    by_kf = {}
    for e in events:
        if not isinstance(e, dict) or e.get("event") != "STATUS_CHANGED":
            continue
        f_from, f_to = e.get("from"), e.get("to")
        if not isinstance(f_from, dict) or not isinstance(f_to, dict):
            continue
        for f in f_from:
            by_kf.setdefault((e.get("group"), e.get("key"), f), []).append(
                (e.get("date"), _flap_val(f_from.get(f)), _flap_val(f_to.get(f))))
    marks = {}
    for (g, k, f), rows in sorted(by_kf.items(), key=repr):
        rows = sorted(set(rows))
        for i, (d1, a1, b1) in enumerate(rows):
            for (d2, a2, b2) in rows[i + 1:]:
                gap = _day_gap(d1, d2)
                if gap is None:
                    continue
                if gap > window_days:
                    break  # rows 已依日期排序，後面只會更遠
                if gap <= 0:
                    continue
                if a2 == b1 and b2 == a1:
                    for dd, other in ((d1, d2), (d2, d1)):
                        m = marks.setdefault((dd, g, k), {"fields": set(), "with": set()})
                        m["fields"].add(f)
                        m["with"].add(other)
    return {kk: {"fields": sorted(v["fields"]), "with": sorted(v["with"])}
            for kk, v in marks.items()}


def annotate_flaps(jsonl_path, window_days=FLAP_WINDOW_DAYS):
    """把 flap_marks() 算出的抖動標記回寫進既有的 events.jsonl，回傳 (被標記事件數, 改寫行數)。

    為什麼必須回頭改既有行：抖動要成立需要「第 2 筆事件」出現，而那時第 1 筆早就寫進
    events.jsonl 了。這是本檔案唯一一處非附加寫入，因此刻意做了三層保護：
      1. **從不刪除任何一行**，也從不改動 date/source/group/key/event/from/to 這 7 個既有
         欄位——只加、改、拿掉 FLAP_MARK_FIELDS 這 3 個本輪新增欄位。
      2. **無法解析的行原樣保留**（不當成錯誤、不丟棄），非 STATUS_CHANGED 的行原樣保留。
      3. **原子寫入**（先寫 .flaptmp 再 os.replace），中途失敗不會留下半截檔案。

    冪等性（scripts/verify_prod.py 第 6 項「detect_delistings 冪等（重跑零變化）」的關鍵）：
    標記完全是「這份檔案內容」的純函式（flap_marks() 決定性，見該函式 docstring），而且
    這裡同時處理「該標而沒標」與「不該標卻標了」兩個方向——後者讓標記狀態有唯一不動點，
    所以第 1 次執行把標記寫進去之後，第 2 次執行算出完全相同的標記、比對相同、
    `changed == 0`、**完全不開檔寫入**，檔案位元組不變。
    唯一會改變檔案的時機是「真的有新標記或標記需要更新」，包含部署後的第一次執行
    （見報告 §6.3 的部署順序提醒：先跑一次再 commit，不要先 commit 再跑 verify_prod）。

    未被標記的行：如果它本來就沒有 FLAP_MARK_FIELDS，走「原樣保留」路徑，一個位元組都不動
    （不做 json 反序列化再序列化的來回，避免任何非預期的格式漂移）。"""
    if not os.path.exists(jsonl_path):
        return 0, 0
    with open(jsonl_path, encoding="utf-8") as f:
        orig_lines = f.readlines()
    parsed = []
    for ln in orig_lines:
        s = ln.strip()
        if not s:
            parsed.append(None)
            continue
        try:
            parsed.append(json.loads(s))
        except Exception:
            parsed.append(None)   # 解析不了就原樣保留，不動它
    marks = flap_marks([e for e in parsed if isinstance(e, dict)], window_days)
    out_lines = []
    changed = 0
    for ln, e in zip(orig_lines, parsed):
        if not isinstance(e, dict) or e.get("event") != "STATUS_CHANGED":
            out_lines.append(ln)
            continue
        want = marks.get((e.get("date"), e.get("group"), e.get("key")))
        cur = (e.get("flapped"), e.get("flap_fields"), e.get("flap_with"))
        tgt = (True, want["fields"], want["with"]) if want else (None, None, None)
        if cur == tgt:
            out_lines.append(ln)
            continue
        for kk in FLAP_MARK_FIELDS:
            e.pop(kk, None)
        if want:
            e["flapped"] = True
            e["flap_fields"] = want["fields"]
            e["flap_with"] = want["with"]
        out_lines.append(json.dumps(e, ensure_ascii=False) + ("\n" if ln.endswith("\n") else ""))
        changed += 1
    if changed:
        tmp = jsonl_path + ".flaptmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("".join(out_lines))
        os.replace(tmp, jsonl_path)
    return len(marks), changed


def update_index(entries):
    """完全比照 scripts/detect_changes.py 的 update_index()：讀舊列 + 合併 + 去重 + 反序。
    與軌二共用同一個 CHANGES.md，兩支程式互相 append 不會覆寫對方。"""
    head = ["# 變動紀錄索引", "",
            "本檔案自動維護。列出所有偵測到**內容改寫或下架**的日期。", "",
            "| 日期 | 來源 | 改寫 | 下架 | 新增 | 紀錄 |", "|---|---|---|---|---|---|"]
    old = []
    if os.path.exists(INDEX):
        for line in open(INDEX, encoding="utf-8"):
            if line.startswith("| 2") and "|---|" not in line:
                old.append(line.rstrip("\n"))
    rows = sorted(set(old + entries), reverse=True)
    with open(INDEX, "w", encoding="utf-8") as f:
        f.write("\n".join(head + rows) + "\n")


def write_alert_block(source, d_new, lines):
    """寫入 ALERT-DELIST.md（本程式獨佔的告警檔，見檔頭「異常告警改用獨立檔案」說明）。

    設計取捨（本輪修正，取代先前假設共用 ALERT.md 的草稿；完整分析見報告第 4 節）：
    1. 檔案所有權：ALERT-DELIST.md 只有本程式會寫，repo 內其餘任何程式
       （healthcheck.py、detect_changes.py、push.sh 等）都不會讀寫這個檔名，
       不存在「被別的程式覆寫或刪除」的可能，因此也不需要依賴掛載順序。
    2. 狀態機刻意與 ALERT.md 不同：healthcheck.py 的 ALERT.md 是「現在有事」旗標——
       每次執行都重新計算目前的真相，issues 清空就整檔刪除（healthcheck.py 第 253~257
       行），語意是「此刻是否需要處理」。熔斷警報語意不同：一組 (source, 比對區間)
       一旦判定熔斷，就是已發生的既成事實，不會因隔天資料恢復正常而消失。本函式只
       追加、永不刪除既有區塊，是永久的觸發紀錄，不是即時狀態旗標。
    3. 冪等合併（HTML 註解 marker 判斷是否已寫過同一 (source, date)）予以保留：
       解決的是「本程式自己重跑同一區間」，跟第 1 點解決的「被別的程式蓋掉」是
       兩個不同問題；先前草稿誤以為前者能緩解後者，實測（見報告第 4 節）證明不能。
    """
    marker = "<!-- detect_delistings:%s:%s -->" % (source, d_new)
    existing = ""
    if os.path.exists(ALERT_DELIST):
        with open(ALERT_DELIST, encoding="utf-8") as f:
            existing = f.read()
    if marker in existing:
        return False
    block = "\n".join(
        ["", "## \U0001f534 track-crypto/%s 自清單消失熔斷警報\uff08%s\uff09" % (source, d_new),
         "", marker, ""] + lines + [""])
    if existing.strip():
        content = existing.rstrip("\n") + "\n" + block
    else:
        header = """# 🔴 track-crypto x402_bazaar 自清單消失規模異常警報（熔斷）

本檔案由 `track-crypto/scripts/detect_delistings.py` 獨佔寫入，不與任何其他程式共用
（另見 `ALERT.md` 是 `scripts/healthcheck.py` 的獨立輸出，兩者互不相干）。

本檔案記錄「removed 率超過熔斷門檻」這個事實（見下方各則區塊的數字），**不代表這些
resource 已永久下架**：本程式對「自清單消失」與「永久下架」不畫等號（詳見
`track-crypto/scripts/detect_delistings.py` 檔頭「事件型別語意定義」小節與本機
`docs/detect-phase1-report.md` §5、§9——同一資料源實測約 5%～17%（依觀察窗長短）的
「自清單消失」案例會在數天內重新出現）。熔斷只代表移除比例超出日常區間（1.8%~3.7%），
需要人工確認成因，本程式不自動判斷是抓取異常還是真的有大量 resource 同時消失。

本檔案只會新增，不會自動刪除既有區塊：每一則對應一組已發生的熔斷事件
（特定來源×特定比對日期），不是「現在是否有異常」的即時狀態旗標。
人工確認後若需歸檔，請自行搬移或加註（例如在行尾加 `<!-- ack:YYYY-MM-DD -->`），
本程式不會自動清除任何已寫入的區塊。
"""
        content = header + block
    with open(ALERT_DELIST, "w", encoding="utf-8") as f:
        f.write(content)
    return True


def process_pair(source, cfg, f_old, f_new, seen, last_delisted, gate_fail_seen=None):
    """比對一組相鄰快照並落地事件／報告／索引／告警。

    last_delisted（呼叫端傳入、本函式原地更新的 dict：key -> 最近一次被記為
    「自清單消失」的日期字串）：REAPPEARED 事件型別（本輪新增）判定用的狀態。
    這個 dict 完全由「這一對快照本身算出的 removed_keys／added_keys」驅動，
    跟 events.jsonl 既有內容或 seen 集合無關——main() 本來就是從最早的可用快照
    開始，依時間先後重算「每一對」相鄰快照的差集（不是只算最新一天），所以只要
    呼叫端依時間先後順序呼叫本函式（main() 本來就是這樣做的），這個 dict 在任何
    一次完整重跑裡都會被重新、正確地建立一次，不依賴、也不會被過去哪一次重跑
    寫過什麼事件所影響（正確性論證與回放驗證見本機 docs/detect-phase1-report.md
    §9）。
    """
    r = compare_pair(source, cfg, f_old, f_new)
    judged = judge(r, cfg)

    # ----------------------------------------------------------------------
    # 第四階段（2026-09-07，熔斷語意統一）：事件建構與「落地去向」分離。
    #   舊行為：judged != "NORMAL" 就完全不建事件 → 事實永久遺失（尤其 REAPPEARED）。
    #   新行為：三種判定**一律建事件**，只有「寫去哪裡」不同：
    #     NORMAL                     → events.jsonl
    #     BREAKER 且放行檢查通過      → events.jsonl，每筆加熔斷標記（標記但不否決）
    #     BREAKER 且放行檢查不通過    → events_quarantine.jsonl（疑似分頁截斷）
    #     GATE_FAIL                  → events_quarantine.jsonl（資料不可信）
    # 完整理由見檔頭「第四階段」。
    # ----------------------------------------------------------------------
    release_ok, release_reason = True, ""
    if judged == "BREAKER":
        release_ok, release_reason = breaker_release_check(source, r["d_old"], r["d_new"], r)
    to_events = (judged == "NORMAL") or (judged == "BREAKER" and release_ok)
    # GATE_FAIL 是否落隔離檔由 QUARANTINE_GATE_FAIL 控制（預設 False，理由見該常數註解）。
    to_quarantine = (not to_events) and (judged == "BREAKER" or QUARANTINE_GATE_FAIL)
    marks = breaker_marks(r["removed_rate"], r["threshold_count"]) if judged == "BREAKER" else {}
    r["breaker_release_ok"] = release_ok
    r["breaker_release_reason"] = release_reason
    r["to_events"] = to_events

    new_events = []
    reappeared_from = {}
    # 第四階段：judge() 只會回傳這三個值，三種判定**一律建事件**（舊版是
    # `if judged == "NORMAL":`），差別只在下面的落地去向。這裡刻意保留一層
    # 條件式而不是把迴圈拉平，是為了讓下面三段既有的事件建構程式碼連縮排都
    # 逐字元不變——scripts/selftest.py 的 mut_dd_reappeared 破壞驗證錨點含縮排，
    # 拉平會讓那條檢查找不到錨點（教訓見 docs/selftest-fix-report.md §1.2）。
    if judged in ("NORMAL", "BREAKER", "GATE_FAIL"):
        for k in r["removed_keys"]:
            new_events.append({"date": r["d_new"], "source": source, "group": source,
                                "key": k, "event": "DELISTED",
                                "from": short_desc(r["keyed_old"].get(k)), "to": None})
        for k in r["added_keys"]:
            new_events.append({"date": r["d_new"], "source": source, "group": source,
                                "key": k, "event": "LISTED",
                                "from": None, "to": short_desc(r["keyed_new"].get(k))})
            if k in last_delisted:
                # REAPPEARED：這個 key 過去曾被記為消失，這次又出現在「新增」
                # 集合裡——在上面剛寫的 LISTED 事件之外，額外補寫這一筆，不取代
                # LISTED（兩者同一天、同時存在）。"from" 放上一次消失的日期，讓
                # 這一筆事件本身就能還原「消失了幾天」，見檔頭「事件型別語意定義」。
                reappeared_from[k] = last_delisted[k]
                new_events.append({"date": r["d_new"], "source": source, "group": source,
                                    "key": k, "event": "REAPPEARED",
                                    "from": last_delisted[k], "to": short_desc(r["keyed_new"].get(k))})
    # 熔斷標記統一在事件全部建好之後一次套用（不在上面三個 append 內就地 update），
    # 這樣三段既有的事件建構程式碼可以逐字元保持原樣——scripts/selftest.py 的
    # mut_dd_reappeared 破壞驗證錨點就落在其中一段，改寫它們會讓那條檢查失去錨點。
    if marks:
        for e in new_events:
            e.update(marks)
    if to_events:
        # 用這一對快照本身的事實更新「最近一次消失日期」——跟下面 write_events()／
        # seen 判斷的「這筆事件是不是本次執行才第一次寫進檔案」完全無關：即使這筆
        # DELISTED 早就寫過（seen 命中，這次不會重複落地），這一對快照仍然「確實
        # 顯示」這個 key 在 r["d_new"] 這天消失，這件事實本身就是下一次牠重新出現時
        # 應該比對的基準，不能因為事件已經寫過就不更新這個狀態。
        # 第四階段新增條件 to_events：只有真的寫進 events.jsonl 的事實才更新這個狀態，
        # 讓 last_delisted 恆等於 events.jsonl 的內容。被隔離的移除**不更新**，
        # 否則之後某天那個 key 回來時，events.jsonl 會出現一筆 REAPPEARED，
        # 但它對應的 DELISTED 只存在於隔離檔裡，兩個檔案互相矛盾。
        for k in r["removed_keys"]:
            last_delisted[k] = r["d_new"]

    # r["reappeared_from"] 的語意固定是「這次寫進 events.jsonl 的重新出現」，
    # render_report()／下面的索引列都沿用這個語意（本輪未修改 render_report()）。
    r["reappeared_from"] = reappeared_from if to_events else {}
    r["quarantined_reappeared_from"] = {} if to_events else reappeared_from

    jsonl_path = os.path.join(TRACK_CRYPTO, "data", source, "events.jsonl")
    if to_events:
        fresh = write_events(jsonl_path, new_events, seen)
        seen.update((e["date"], e["source"], e["group"], e["key"], e["event"]) for e in fresh)
        quarantined = []
    elif not to_quarantine:
        fresh = []
        quarantined = []
    else:
        fresh = []
        q_path = os.path.join(TRACK_CRYPTO, "data", source, QUARANTINE_BASENAME)
        q_seen = load_quarantine_seen(q_path)
        reason_code = "GATE_FAIL" if judged == "GATE_FAIL" else "BREAKER_TRUNCATION_SUSPECT"
        reason_text = (release_reason if judged == "BREAKER"
                       else "完整性守門不通過：前日=%s／當日=%s" % (r["reason_old"], r["reason_new"]))
        quarantined = write_quarantine(source, r["d_new"], new_events, reason_code, reason_text, q_seen)
        if quarantined:
            print("   [QUARANTINE] %s @ %s->%s：%d 筆事件寫入 %s（%s：%s）"
                  % (source, r["d_old"], r["d_new"], len(quarantined),
                     QUARANTINE_BASENAME, reason_code, reason_text))
    r["quarantined"] = len(quarantined)

    entries_for_index = []
    if judged == "NORMAL" and not r["removed_keys"] and not reappeared_from:
        # 比照 detect_changes.py：無自清單消失、也無重新出現（軌一沒有「改寫」概念）
        # 時不留 changes/ 紀錄，避免雜訊。
        pass
    else:
        # GATE_FAIL / BREAKER 一律落地紀錄（即使 removed_keys 剛好是 0）——
        # 「不判定」本身就是必須留下痕跡的事件，不能因為數字剛好是 0 就靜默跳過。
        # NORMAL 但有重新出現（即使 removed_keys 剛好是 0，本輪新增的情境）也要
        # 落地：「有 resource 重新出現」本身就是值得留下痕跡的事實，不能因為當天
        # 沒有新的自清單消失就靜默跳過（本輪 08-26～09-01 回放區間內每天
        # removed_keys 都非 0，未實際觸發這個新分支，見報告 §9 的誠實揭露）。
        outdir = os.path.join(CHANGES, source)
        os.makedirs(outdir, exist_ok=True)
        out = os.path.join(outdir, "%s.md" % r["d_new"])
        with open(out, "w", encoding="utf-8") as f:
            f.write(render_report(source, cfg, r, judged))
        if judged == "NORMAL" or (judged == "BREAKER" and to_events):
            removed_cell = str(len(r["removed_keys"]))
            added_cell = str(len(r["added_keys"]))
            if reappeared_from:
                added_cell += "（含 %d 筆重新出現）" % len(reappeared_from)
            if judged == "BREAKER":
                # 第四階段：熔斷改成「標記但不否決」後，事件是有寫的，索引列不能再寫
                # 「熔斷」讓人以為沒寫；改成明確說明「已標記」。
                removed_cell += "（熔斷已標記）"
        else:
            tag = "不判定" if judged == "GATE_FAIL" else "熔斷"
            # 「，已隔離」只在事件真的有寫進隔離檔時才加；GATE_FAIL 在
            # QUARANTINE_GATE_FAIL=False（預設）下沒有隔離任何東西，索引列必須維持
            # 本輪之前的原樣，才不會憑空製造一堆與事實不符的差異。
            suffix = "，已隔離" if to_quarantine else ""
            removed_cell = "%d（%s%s）" % (len(r["removed_keys"]), tag, suffix)
            added_cell = "%d（%s%s）" % (len(r["added_keys"]), tag, suffix)
        entries_for_index.append(
            "| %s | `track-crypto/%s` | %s | %s | %s | [紀錄](changes/%s/%s.md) |"
            % (r["d_new"], source, EMDASH, removed_cell, added_cell, source, r["d_new"]))

    if judged == "GATE_FAIL":
        # 記錄 GATE_FAIL 事實供 healthcheck.py 告警用（specs/SPEC-gate-dedup.md）。
        # reason 文字直接沿用 completeness() 算出的 reason_old／reason_new，不重新
        # 詮釋（比照 scripts/healthcheck.py 的 check_cex_gate_skips() 對
        # gate_skips.jsonl reason 欄位的既有處理原則）。
        reasons = []
        if not r["ok_old"]:
            reasons.append("前日(%s)：%s（上游自報總數=%r, len(items)=%r）"
                            % (r["d_old"], r["reason_old"], r["total_old"], r["n_old"]))
        if not r["ok_new"]:
            reasons.append("當日(%s)：%s（上游自報總數=%r, len(items)=%r）"
                            % (r["d_new"], r["reason_new"], r["total_new"], r["n_new"]))
        record_gate_fail(source, source, r["d_new"], r["d_old"], "；".join(reasons),
                          r["n_old"], r["n_new"], gate_fail_seen)

    alert_written = False
    if judged == "BREAKER":
        lines = [
            "檢查時間（UTC）：%s" % datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "",
            "| 項目 | 值 |",
            "|---|---|",
            "| 來源 | `track-crypto/%s` |" % source,
            "| 比對區間 | `%s` → `%s` |" % (r["d_old"], r["d_new"]),
            "| removed 率 | %.2f%%（門檻 %.1f%%） |" % (r["removed_rate"], cfg["breaker_pct"]),
            "| 前日筆數（去重後） | %d |" % len(r["keyed_old"]),
            "| 當日移除筆數 | %d |" % len(r["removed_keys"]),
        ]
        if to_events:
            lines += [
                "| 處置 | **標記但不否決**：事件已寫入 `data/%s/events.jsonl` |" % source,
                "| 放行依據 | %s |" % release_reason,
                "",
                ("本日 `%s` 的「自清單消失」判定**照常寫入** `data/%s/events.jsonl`，"
                 "但該組轉換產生的每一筆事件都額外帶 `note:\"anomalous_scale\"`、"
                 "`breaker_tripped:true`、`removed_pct`、`breaker_threshold` 四個欄位，"
                 "**需要人工複核**。removed 率超過該來源的熔斷門檻，可能是抓取異常，"
                 "也可能是真的有大量 resource 同時自清單消失，本程式不對成因下判斷"
                 "（零觀點鐵律）。詳見 `changes/%s/%s.md`。若複核後判定為假事件，"
                 "請用 `scripts/apply_correction.py` 更正，不要手動編輯事件流。"
                 % (source, source, source, r["d_new"])),
            ]
        else:
            lines += [
                "| 處置 | **隔離**：事件已寫入 `data/%s/%s`，未進 events.jsonl |"
                % (source, QUARANTINE_BASENAME),
                "| 隔離原因 | %s |" % release_reason,
                "",
                ("本日 `%s` 的「自清單消失」判定**未寫入** `data/%s/events.jsonl`，"
                 "因為除了移除規模超過熔斷門檻之外，還同時命中「疑似分頁截斷」的"
                 "結構性指紋（見上表）。事件事實**沒有遺失**，已完整寫入隔離檔 "
                 "`data/%s/%s`，人工複核確認不是抓取問題後可提升回事件流。"
                 "詳見 `changes/%s/%s.md`。"
                 % (source, source, source, QUARANTINE_BASENAME, source, r["d_new"])),
            ]
        alert_written = write_alert_block(source, r["d_new"], lines)

    return judged, r, fresh, entries_for_index, alert_written


# ==========================================================================
# 第四階段（2026-09-07，熔斷語意統一）新增的函式，全部集中在這一段連續區塊，
# 方便與其他同時進行的修改合併。本段之外的既有函式改動點見檔頭「本輪修改範圍」。
# ==========================================================================

def removal_tail_metrics(keyed_old, removed_keys):
    """分頁截斷指紋：算「前一日清單順序中，結尾連續且全部被移除」的區塊。

    回傳 (tail_run, tail_cover)：
      tail_run   ＝ 從前一日清單最後一筆往回數，連續落在 removed_keys 裡的筆數。
      tail_cover ＝ tail_run / len(removed_keys)，移除總數為 0 時定義為 0.0。

    為什麼是這個指標（原理，不是經驗法則）：offset 分頁一旦提前中止，被丟掉的一定是
    「伺服器排序的一段連續尾巴」，不會是清單中間的零星項目；真實下架則沒有這個限制。
    keyed_old 是 dedup() 回傳的 dict，Python dict 保留插入順序，插入順序＝原始 items
    的出現順序，所以 list(keyed_old) 就是前一日的清單順序，不必另外保存位置資訊。

    本函式是純函式：不讀檔、不寫檔、不看設定，只吃兩個集合。門檻判斷不在這裡，
    在 breaker_release_check()（門檻常數 BREAKER_TAIL_COVER_MAX）。
    """
    removed = set(removed_keys)
    if not removed:
        return 0, 0.0
    run = 0
    for k in reversed(list(keyed_old)):
        if k in removed:
            run += 1
        else:
            break
    return run, run / len(removed)


def _manifest_entry(date, source):
    """讀 track-crypto/data/_manifest/<date>.json 裡該來源的紀錄，讀不到一律回 None
    （由呼叫端 fail-closed 處理）。只讀不寫，任何例外都吞掉回 None——這是側證用的
    輔助資料，不能因為它出問題就讓主流程掛掉。"""
    p = os.path.join(TRACK_CRYPTO, "data", "_manifest", "%s.json" % date)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            m = json.load(f)
    except Exception:
        return None
    s = m.get("sources") or m.get("channels") or {}
    e = s.get(source) if isinstance(s, dict) else None
    return e if isinstance(e, dict) else None


def breaker_release_check(source, d_old, d_new, r):
    """熔斷成立時，判斷是否放行「標記但不否決」。回傳 (ok, reason)。

    全部 fail-closed：任何一項讀不到、型別不對、或不通過，一律回 False（＝改走隔離檔）。

    三道檢查：
      1. 截斷指紋：tail_cover < BREAKER_TAIL_COVER_MAX（門檻校準見該常數註解）。
      2. manifest 側證：兩側日期該來源的 ok 必須是 True、truncated 必須是 False
         （精確型別檢查，缺失/None/True 一律不通過）。
         **對 x402_bazaar 而言 truncated 這一項是恆真的**（見檔頭第四階段說明：
         adapter 沒有回報這個旗標，snap_crypto.py 讀不到時預設 False），
         這裡仍然檢查，是因為別的來源（agent_virtuals、mcp_smithery、vast_gpu）
         這個旗標是真訊號，統一規則不因單一來源的缺陷而放棄。
      3. parser_version 兩日一致：解析器改版會造成假消失（本專案三大假性變動陷阱
         之一，見 docs/source-value-audit.md），改版當天不該放行大規模移除判定。

    為什麼不檢查 manifest 的 complete 欄位：agent_virtuals 的 manifest complete 恆為
    False（manifest 用嚴格 total_match，偵測程式對該來源另用 tolerant_total_match，
    見 completeness_group()），加這個條件會讓該來源永遠無法放行，是把 manifest 的
    嚴格度誤當成本程式的守門結論。本程式自己的守門結論是 r["gate_ok"]，
    而 BREAKER 本來就蘊含 gate_ok==True（見 compare_pair()／compare_group()）。
    """
    cov = r.get("tail_cover")
    if not isinstance(cov, (int, float)):
        return False, "缺 tail_cover 欄位（fail-closed）"
    if cov >= BREAKER_TAIL_COVER_MAX:
        return False, ("疑似分頁截斷：尾端連續移除佔比 %.4f >= 門檻 %.2f（tail_run=%s）"
                       % (cov, BREAKER_TAIL_COVER_MAX, r.get("tail_run")))
    e_old = _manifest_entry(d_old, source)
    e_new = _manifest_entry(d_new, source)
    for d, e in ((d_old, e_old), (d_new, e_new)):
        if e is None:
            return False, "%s 的 manifest 查無 %s 紀錄（fail-closed）" % (d, source)
        if e.get("ok") is not True:
            return False, "%s manifest ok=%r（非布林 True）" % (d, e.get("ok"))
        if e.get("truncated") is not False:
            return False, "%s manifest truncated=%r（非布林 False）" % (d, e.get("truncated"))
    if e_old.get("parser_version") != e_new.get("parser_version"):
        return False, ("parser_version 兩日不同（%r → %r），解析器改版當天不放行"
                       % (e_old.get("parser_version"), e_new.get("parser_version")))
    return True, ("tail_cover=%.4f < %.2f；manifest ok/truncated/parser_version 兩日皆通過"
                  % (cov, BREAKER_TAIL_COVER_MAX))


def breaker_marks(removed_pct, threshold_count):
    """熔斷事件的標記欄位（本檔案與 scripts/cex_events.py 共用同一組欄位名與語意）。

      note              沿用 cex_events.py 從 2026-09-01 起就在用的既有值，
                        不新造第二個名字，讓既有下游查詢照樣命中。
      breaker_tripped   布林旗標，給不想比對字串的下游用。
      removed_pct       本次移除佔前一日去重後筆數的百分比（四捨五入到小數 4 位）。
      breaker_threshold 觸發門檻，**一律換算成筆數**（不是百分比）——本檔案第一階段
                        SOURCES 用百分比比較、第二階段 GROUP_SOURCES 與 cex_events.py
                        用筆數比較，換算成同一單位後三條路徑的欄位語意才真的一致。
    """
    return {"note": "anomalous_scale", "breaker_tripped": True,
            "removed_pct": round(float(removed_pct), 4),
            "breaker_threshold": round(float(threshold_count), 4)}


def load_quarantine_seen(jsonl_path):
    """讀隔離檔目前所有五元組鍵值，供 write_quarantine() 冪等判斷。
    手法與 load_seen() 完全相同（同一組鍵、同一種容錯解析），只是換一個檔案。"""
    return load_seen(jsonl_path)


def write_quarantine(source, d_new, events, reason_code, reason_text, seen):
    """把「本來會寫進 events.jsonl、但這組轉換不可信」的事件完整寫進隔離檔。

    設計重點：
      1. **隔離不是丟棄**。舊行為（judged != "NORMAL" 就完全不建事件）造成的遺失是
         不可逆的，尤其 REAPPEARED——key 一旦回到清單，之後任何一次比對都不會再把它
         放進 added_keys，判定機會永久消失（見檔頭第四階段問題 2）。寫進隔離檔之後，
         事實還在，人工複核後可以提升。
      2. 只追加，去重鍵與 events.jsonl 相同的五元組，重跑不會長出重複行（冪等）。
      3. 隔離檔**不是** events.jsonl 的一部分：scripts/verify_prod.py 的冪等檢查
         只雜湊 track-crypto/data/*/events.jsonl，本檔案不在其列；下游若要用，
         必須明確地另外讀這個檔名，不會被誤當成已確認的事件。
      4. 每筆額外帶 quarantine_reason／quarantine_detail／quarantine_date 三個欄位，
         說明「為什麼被隔離」，人工複核時不必回去翻 log。
    """
    if not events:
        return []
    path = os.path.join(TRACK_CRYPTO, "data", source, QUARANTINE_BASENAME)
    fresh = []
    for e in events:
        k = (e["date"], e["source"], e["group"], e["key"], e["event"])
        if k in seen:
            continue
        rec = dict(e)
        rec["quarantine_reason"] = reason_code
        rec["quarantine_detail"] = reason_text
        rec["quarantine_date"] = d_new
        fresh.append((k, rec))
    if not fresh:
        return []
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for _k, rec in fresh:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    for k, _rec in fresh:
        seen.add(k)
    return [rec for _k, rec in fresh]


# ==========================================================================
# 第五階段（2026-09-08，mcp_smithery 納入下架偵測）新增的函式，集中在這一段連續
# 區塊，方便與其他同時進行的修改合併。本段之外的改動點只有三處（全部是純追加）：
#   1. completeness_group()：新增 full_flag_tolerant_total_match 分支
#      （既有 total_match／range_check／tolerant_total_match 三個分支一字未改）。
#   2. GROUP_SOURCES：新增 "mcp_smithery" 條目（既有 11 個來源一字未改）。
#   3. process_group_source_pair()：compare_group() 之後多呼叫一次
#      parser_version_floor_check()（未設定 min_parser_version 的子集合是 no-op）。
# ==========================================================================

def parser_version_floor_check(source, gcfg, d_old, d_new):
    """解析器版本下限守門。回傳 (ok, reason)。

    **未設定 gcfg["min_parser_version"] 的子集合一律直接回 (True, "")**——這是
    opt-in 機制，不是全域行為改變（比照第四階段 stable_id_fields 的既有慣例：
    只有設定了那個鍵的子集合才啟用抵銷層）。目前只有 mcp_smithery/_servers 設定。

    為什麼需要這道守門（實測，不是推測）：
      `mcp_smithery` 的 adapter 在 2026-09-07 從 v2 升到 v3（少帶 seed 的 bug 修好，
      見 docs/0907-A-smithery-rootcause.md）。09-07 快照 272 筆、09-08 快照 11,917 筆，
      以 id 做集合差 added=11,645、removed=0 —— 直接比對會一次寫進 **11,645 筆假
      LISTED 事件**，而且 events.jsonl 不在 .gitignore 排除範圍內，會永久污染 git 歷史。

    為什麼既有機制不夠：
      本檔案原本唯一的 parser_version 檢查在 breaker_release_check()，那條路徑
      **只有 judged=="BREAKER" 時才會被呼叫**。本情境 removed=0，熔斷根本不成立，
      永遠走不到那個檢查。scripts/detect_changes.py 的「parser_version 不同就跳過」
      是另一支程式（軌二變動偵測器）的機制，管不到本檔案。

    三條規則，全部 fail-closed（任何一項讀不到／型別不對一律回 False）：
      1. 兩側日期在 track-crypto/data/_manifest/<date>.json 都要查得到本來源紀錄。
      2. 兩側的 parser_version 都必須是整數且 >= min_parser_version。
      3. 兩側的 parser_version 必須相同（解析器改版當天不比對，理由同
         breaker_release_check() 第 3 點：改版會造成假消失／假新增）。

    只讀 manifest，不讀快照本體；沿用既有的 _manifest_entry()（讀不到回 None，
    任何例外都吞掉），不新增任何檔案存取路徑。
    """
    floor = gcfg.get("min_parser_version")
    if floor is None:
        return True, ""
    entries = {}
    for d in (d_old, d_new):
        e = _manifest_entry(d, source)
        if e is None:
            return False, "%s 的 manifest 查無 %s 紀錄（fail-closed）" % (d, source)
        pv = e.get("parser_version")
        if not isinstance(pv, int) or isinstance(pv, bool):
            return False, ("%s 的 manifest parser_version=%r 非整數（fail-closed）" % (d, pv))
        if pv < floor:
            return False, ("%s 的 parser_version=%d 低於下限 %d，"
                           "舊解析器產出的快照不可與新版比對" % (d, pv, floor))
        entries[d] = pv
    if entries[d_old] != entries[d_new]:
        return False, ("parser_version 兩日不同（%d → %d），解析器改版當天不比對"
                       % (entries[d_old], entries[d_new]))
    return True, ("parser_version 兩日皆為 %d（>= 下限 %d）" % (entries[d_new], floor))


def main():
    # --------------------------------------------------------------------
    # 第一階段（x402_bazaar，SOURCES）：本迴圈與下方三行 summary print 自 commit
    # 7cce2dc 起除下述一項新增外逐字元原樣，未刪除、未重排任何一行，只是把原本
    # 「唯一迴圈」改成「第一個迴圈」，緊接第二階段迴圈之前。all_index_entries
    # 改成先收集、最後統一呼叫一次 update_index()（原本就是這個模式，只是現在
    # 兩個迴圈共用同一份 all_index_entries 累積清單，update_index() 本身完全
    # 不變——它是「讀舊行+合併+去重+反序」，天然支援多來源各自追加，見該函式
    # docstring）。
    # 本輪（specs/SPEC-gate-dedup.md）唯一新增：process_pair() 呼叫多傳一個
    # gate_fail_seen 關鍵字引數（供 GATE_FAIL 事實紀錄冪等判斷，見該函式與
    # record_gate_fail() docstring）——純粹多傳一個有預設值的引數，不改變
    # events.jsonl／changes/*.md／CHANGES.md／ALERT-DELIST.md 這四個既有輸出管道
    # 的任何既有邏輯或輸出內容，已用「對真實歷史資料重跑、events.jsonl 逐位元組
    # 不變」驗證，見本機 docs/gate-dedup-report.md。
    # --------------------------------------------------------------------
    total_listed = total_delisted = total_reappeared = 0
    normal_days = gate_fail_days = breaker_days = 0
    # 第四階段（熔斷語意統一）新增的兩個計數器，只用於最後的 SUMMARY 輸出，
    # 不影響任何既有計數器與既有輸出格式。
    breaker_marked_days = quarantined_events = 0
    all_index_entries = []
    any_source = False
    gate_fail_seen = load_gate_fail_seen()  # 本輪新增：跨 SOURCES／GROUP_SOURCES 兩迴圈共用一份
    for source, cfg in SOURCES.items():
        any_source = True
        snaps = snapshots(source)
        if len(snaps) < 2:
            print("%s: 快照不足 2 份，略過" % source)
            continue
        jsonl_path = os.path.join(TRACK_CRYPTO, "data", source, "events.jsonl")
        seen = load_seen(jsonl_path)
        last_delisted = {}  # REAPPEARED 判定用狀態（本輪新增），見 process_pair() docstring
        for f_old, f_new in zip(snaps[:-1], snaps[1:]):
            judged, r, fresh, entries, alert_written = process_pair(
                source, cfg, f_old, f_new, seen, last_delisted, gate_fail_seen=gate_fail_seen)
            if judged == "GATE_FAIL":
                gate_fail_days += 1
            elif judged == "BREAKER":
                breaker_days += 1
                if r.get("to_events"):
                    breaker_marked_days += 1
            else:
                normal_days += 1
            quarantined_events += r.get("quarantined", 0)
            n_listed = sum(1 for e in fresh if e["event"] == "LISTED")
            n_delisted = sum(1 for e in fresh if e["event"] == "DELISTED")
            n_reappeared = sum(1 for e in fresh if e["event"] == "REAPPEARED")
            total_listed += n_listed
            total_delisted += n_delisted
            total_reappeared += n_reappeared
            print("%s: %s->%s judged=%-10s 新事件 listed=%d delisted=%d reappeared=%d%s"
                  % (source, r["d_old"], r["d_new"], judged, n_listed, n_delisted, n_reappeared,
                     "  [ALERT-DELIST.md 已寫入]" if alert_written else ""))
            all_index_entries.extend(entries)

    # --------------------------------------------------------------------
    # 第二階段（甲組其餘 8 個來源，GROUP_SOURCES）：獨立迴圈、獨立計數器，
    # 完全不寫入／不讀取上面的 total_listed 等第一階段計數器，只共用
    # all_index_entries（累積清單，最後統一呼叫一次 update_index()）。
    # --------------------------------------------------------------------
    g_total_listed = g_total_delisted = g_total_reappeared = g_total_status = 0
    g_normal = g_gate_fail = g_breaker = 0
    g_breaker_marked = g_not_to_events = 0
    g_total_flapped = g_flap_rewritten = 0  # 本輪新增（做法 2 抖動標記），見 annotate_flaps()
    g_total_renamed = 0  # 第五階段新增（2026-09-08，任務 0908-1）：RENAMED 事件計數
    any_group_source = False
    for source, scfg in GROUP_SOURCES.items():
        any_group_source = True
        snaps = snapshots(source)
        if len(snaps) < 2:
            print("%s: 快照不足 2 份，略過" % source)
            continue
        jsonl_path = os.path.join(TRACK_CRYPTO, "data", source, "events.jsonl")
        seen = load_seen(jsonl_path)
        last_delisted_by_group = {}  # {group: {key: date}}，REAPPEARED 判定用狀態
        for f_old, f_new in zip(snaps[:-1], snaps[1:]):
            group_results, fresh, entries, alert_written = process_group_source_pair(
                source, scfg, f_old, f_new, seen, last_delisted_by_group, gate_fail_seen=gate_fail_seen)
            d_old = os.path.basename(f_old)[:10]
            d_new = os.path.basename(f_new)[:10]
            n_listed = sum(1 for e in fresh if e["event"] == "LISTED")
            n_delisted = sum(1 for e in fresh if e["event"] == "DELISTED")
            n_reappeared = sum(1 for e in fresh if e["event"] == "REAPPEARED")
            n_status = sum(1 for e in fresh if e["event"] == "STATUS_CHANGED")
            n_renamed = sum(1 for e in fresh if e["event"] == "RENAMED")
            g_total_listed += n_listed
            g_total_delisted += n_delisted
            g_total_reappeared += n_reappeared
            g_total_status += n_status
            g_total_renamed += n_renamed
            judged_summary = ",".join("%s=%s" % (g, gr["judged"]) for g, gr in group_results.items())
            for gr in group_results.values():
                if gr["judged"] == "GATE_FAIL":
                    g_gate_fail += 1
                elif gr["judged"] == "BREAKER":
                    g_breaker += 1
                    if gr.get("to_events"):
                        g_breaker_marked += 1
                else:
                    g_normal += 1
                if not gr.get("to_events", True):
                    g_not_to_events += 1
            print("%s: %s->%s [%s] 新事件 listed=%d delisted=%d reappeared=%d status_changed=%d%s"
                  % (source, d_old, d_new, judged_summary, n_listed, n_delisted, n_reappeared, n_status,
                     "  [ALERT-DELIST.md 已寫入]" if alert_written else ""))
            # 第五階段新增（2026-09-08，任務 0908-1）：改名是罕見事件，用**獨立的一行**
            # 印出來，刻意不塞進上面那行既有格式——上面那行的字面格式自第二階段起未變，
            # 下游若有人在 grep 它，本輪不承擔打壞它的風險。只有真的有改名的日子才會多印
            # 這一行（實測 12 組配對只有 2026-09-06 一天會印），其餘日子 stdout 逐位元組不變。
            if n_renamed:
                print("%s: %s->%s 上游改名 %d 筆，已寫入 events.jsonl（事件型別 RENAMED）"
                      % (source, d_old, d_new, n_renamed))
            all_index_entries.extend(entries)
        # 本輪新增（2026-09-07，做法 2 抖動標記）：本來源的全歷史配對跑完之後，對這份
        # events.jsonl 重算一次抖動標記並回寫。放在這裡而不是每組配對之後，是因為抖動要
        # 成立需要「後來那一筆」也已經寫進檔案；放在來源迴圈尾端剛好保證整段歷史都在了。
        # 只影響 FLAP_MARK_FIELDS 這 3 個新增欄位，不動任何既有欄位（見 annotate_flaps()）。
        n_flap, n_rewritten = annotate_flaps(jsonl_path)
        g_total_flapped += n_flap
        g_flap_rewritten += n_rewritten
        if n_rewritten:
            print("%s: 抖動標記回寫 %d 行（目前共 %d 筆事件帶標記，回翻視窗 %d 天）"
                  % (source, n_rewritten, n_flap, FLAP_WINDOW_DAYS))

    if not any_source and not any_group_source:
        print("FATAL 白名單 SOURCES 與 GROUP_SOURCES 皆為空", file=sys.stderr)
        return 1
    if all_index_entries:
        update_index(all_index_entries)
    print("SUMMARY listed=%d delisted=%d reappeared=%d normal_days=%d gate_fail_days=%d breaker_days=%d"
          % (total_listed, total_delisted, total_reappeared, normal_days, gate_fail_days, breaker_days))
    print("SUMMARY(GROUP_SOURCES) listed=%d delisted=%d reappeared=%d status_changed=%d "
          "normal=%d gate_fail=%d breaker=%d"
          % (g_total_listed, g_total_delisted, g_total_reappeared, g_total_status,
             g_normal, g_gate_fail, g_breaker))
    print("GATE_FAIL 事實紀錄檔：%s（去重後累積 %d 筆歷史紀錄，供 healthcheck.py 告警用）"
          % (GATE_FAIL_LOG, len(gate_fail_seen)))
    # 第四階段（熔斷語意統一）新增的一行 SUMMARY，格式與既有兩行 SUMMARY 同構，
    # 既有兩行逐字元未動（下游若有在 grep "SUMMARY listed=" 不受影響）。
    print("SUMMARY(BREAKER_SEMANTICS) breaker_days=%d breaker_marked_days=%d "
          "quarantined_events=%d group_breaker=%d group_breaker_marked=%d "
          "group_not_to_events=%d tail_cover_max=%.2f"
          % (breaker_days, breaker_marked_days, quarantined_events,
             g_breaker, g_breaker_marked, g_not_to_events, BREAKER_TAIL_COVER_MAX))
    print("SUMMARY(FLAP/FILTER) flapped_events=%d flap_rewritten_lines=%d flap_window_days=%d "
          "status_filtered=%d filter_log=%s"
          % (g_total_flapped, g_flap_rewritten, FLAP_WINDOW_DAYS,
             len(load_status_filter_seen(refresh=True)), STATUS_FILTER_LOG))
    # 第五階段新增（2026-09-08，任務 0908-1）：獨立一行，格式與既有四行 SUMMARY 同構，
    # 既有四行逐字元未動。
    print("SUMMARY(RENAMED) renamed_events=%d" % g_total_renamed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
