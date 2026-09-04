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
============================================================================
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
SOURCES = {
    "x402_bazaar": {
        "label": "x402 Bazaar 全量掛牌（Coinbase CDP x402 discovery API）",
        "key_field": "resource",
        "total_field": "total",
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
                "completeness": "total_match", "total_fields": ("count",),
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
                "completeness": "total_match", "total_fields": ("count",),
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
}


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
    total_fields／require_empty 一律讀 data_root 這一層（來源的 data 節點本身），
    不是子集合節點內——本階段 8 個來源的自報總數欄位（count／total_count／errors）
    實測皆位於 data 頂層，不在子集合節點內部（見報告 §2 逐來源小節的實測依據）。
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
    removed_rate = (len(removed_keys) / len(keyed_old) * 100.0) if keyed_old else 0.0
    threshold_count = max(gcfg["abs_floor"], gcfg["breaker_pct"] / 100.0 * len(keyed_old))
    breaker = gate_ok and (len(removed_keys) > threshold_count)

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
    }


def status_changes_for_group(gcfg, keyed_old, keyed_new):
    """回傳 {key: (delta_from_dict, delta_to_dict)}，只含實際有變化的欄位。
    只比對兩側都存在（key 未消失）的項目——key 本身的存在/消失由 DELISTED/LISTED
    處理，這裡只處理「還在清單裡、但欄位值變了」的情況（旗標優先，見檔案上方
    第二階段設計原則第 6 點）。"""
    fields = gcfg.get("status_fields") or ()
    if not fields:
        return {}
    changes = {}
    for k in sorted(set(keyed_old) & set(keyed_new), key=repr):
        old_item, new_item = keyed_old[k], keyed_new[k]
        if not isinstance(old_item, dict) or not isinstance(new_item, dict):
            continue
        delta_from, delta_to = {}, {}
        for f in fields:
            ov, nv = old_item.get(f), new_item.get(f)
            if ov != nv:
                delta_from[f] = ov
                delta_to[f] = nv
        if delta_from:
            changes[k] = (delta_from, delta_to)
    return changes


def build_group_events(source, gname, gcfg, r, judged, d_new, last_delisted):
    """比照 process_pair() 內的事件建構邏輯，泛化到支援 STATUS_CHANGED。
    只在 judged=="NORMAL" 時計算與寫入，與既有 LISTED／DELISTED／REAPPEARED 的
    閘門條件完全一致。回傳 (new_events, reappeared_from)。"""
    new_events = []
    reappeared_from = {}
    if judged != "NORMAL":
        return new_events, reappeared_from
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
    for k in r["removed_keys"]:
        last_delisted[k] = d_new

    status_changes = status_changes_for_group(gcfg, r["keyed_old"], r["keyed_new"])
    for k in sorted(status_changes, key=repr):
        delta_from, delta_to = status_changes[k]
        new_events.append({"date": d_new, "source": source, "group": gname, "key": k,
                            "event": "STATUS_CHANGED", "from": delta_from, "to": delta_to})

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
    L.append("> \u2139\ufe0f **措辭說明**：「自清單消失」「新增」「重新出現」「狀態變化」都只是描述"
              "『這個項目在這兩份快照裡的狀態』的事實，**不代表任何原因推測**。"
              "機器可讀事件型別為 `DELISTED`／`LISTED`／`REAPPEARED`／`STATUS_CHANGED`"
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
        tag = "" if judged == "NORMAL" else ("（%s，未寫入事件流）" % ("不判定" if judged == "GATE_FAIL" else "熔斷"))
        L.append("| **自清單消失**（實際差集筆數，%s） | **%d**%s |" %
                  ("已寫入事件流為 `DELISTED`" if judged == "NORMAL" else "僅供人工參考，非正式事件",
                   len(r["removed_keys"]), tag))
        L.append("| 新增（實際差集筆數，%s） | %d%s |" %
                  ("已寫入事件流為 `LISTED`" if judged == "NORMAL" else "僅供人工參考，非正式事件",
                   len(r["added_keys"]), tag))
        L.append("| \u2514\u2500 其中重新出現 | %d%s |" % (n_reappeared, tag))
        if gcfg.get("status_fields"):
            L.append("| 狀態變化（%s） | %d%s |" %
                      ("已寫入 STATUS_CHANGED" if judged == "NORMAL" else "僅供人工參考", len(status_changes), tag))
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
                      "（max(%d, %.1f%%×前日筆數)＝%.2f），本日「自清單消失」判定已暫停，"
                      "改寫入 `ALERT-DELIST.md`，等待人工確認。** 完整性守門本身通過"
                      "（前後兩側 n 皆在合理範圍內），移除比例超出實測日常區間，"
                      "可能是抓取異常，也可能是真的有大量項目同時自清單消失，"
                      "本程式不自動判斷成因，僅陳述數字。"
                      % (gname, len(r["removed_keys"]), gcfg["abs_floor"], gcfg["breaker_pct"], r["threshold_count"]))
            L.append("")
        if r["removed_keys"]:
            L.append("### \u26a0\ufe0f 自清單消失（%d）%s" % (len(r["removed_keys"]), "" if judged == "NORMAL" else "（未經完整性驗證）"))
            L.append("")
            for k in r["removed_keys"]:
                desc = short_desc_generic(r["keyed_old"].get(k), gcfg.get("desc_field"))
                L.append("- `%s`%s" % (k, (" \u2014 " + desc) if desc else ""))
            L.append("")
        if r["added_keys"]:
            extra = "（含 %d 筆重新出現，詳見下一節）" % n_reappeared if n_reappeared else ""
            L.append("### 新增（%d）%s%s" % (len(r["added_keys"]), extra, "" if judged == "NORMAL" else "（未經完整性驗證）"))
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
    L.append("僅陳述「哪個項目在哪天消失／出現／重新出現／狀態變化」此一事實，**不含任何解讀或評論**。")
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
    for gname, gcfg in scfg["groups"].items():
        r = compare_group(source, gname, gcfg, data_old, data_new)
        judged = judge(r, gcfg)
        last_delisted = last_delisted_by_group.setdefault(gname, {})
        new_events, reappeared_from = build_group_events(source, gname, gcfg, r, judged, d_new, last_delisted)
        status_changes = status_changes_for_group(gcfg, r["keyed_old"], r["keyed_new"]) if judged == "NORMAL" else {}
        group_results[gname] = {"r": r, "judged": judged, "gcfg": gcfg,
                                 "reappeared_from": reappeared_from, "status_changes": status_changes}
        all_new_events.extend(new_events)

    jsonl_path = os.path.join(TRACK_CRYPTO, "data", source, "events.jsonl")
    fresh = write_events(jsonl_path, all_new_events, seen)
    seen.update((e["date"], e["source"], e["group"], e["key"], e["event"]) for e in fresh)

    need_report = False
    for gr in group_results.values():
        if gr["judged"] != "NORMAL":
            need_report = True
        elif gr["r"]["removed_keys"] or gr["r"]["added_keys"] or gr["reappeared_from"] or gr["status_changes"]:
            need_report = True

    entries_for_index = []
    alert_written = False
    if need_report:
        outdir = os.path.join(CHANGES, source)
        os.makedirs(outdir, exist_ok=True)
        out = os.path.join(outdir, "%s.md" % d_new)
        with open(out, "w", encoding="utf-8") as f:
            f.write(render_group_source_report(source, scfg, d_old, d_new, group_results))

        total_removed = sum(len(gr["r"]["removed_keys"]) for gr in group_results.values() if gr["judged"] == "NORMAL")
        total_added = sum(len(gr["r"]["added_keys"]) for gr in group_results.values() if gr["judged"] == "NORMAL")
        total_reappeared = sum(len(gr["reappeared_from"]) for gr in group_results.values() if gr["judged"] == "NORMAL")
        total_status = sum(len(gr["status_changes"]) for gr in group_results.values() if gr["judged"] == "NORMAL")
        non_normal = [g for g, gr in group_results.items() if gr["judged"] != "NORMAL"]
        removed_cell = str(total_removed)
        added_cell = str(total_added)
        if total_reappeared:
            added_cell += "（含 %d 筆重新出現）" % total_reappeared
        if total_status:
            removed_cell += "；狀態變化 %d" % total_status
        if non_normal:
            tag = "；".join("%s:%s" % (g, group_results[g]["judged"]) for g in non_normal)
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
                    "",
                    ("本日 `%s`／子集合 `%s` 的「自清單消失」判定已**暫停**，未寫入 "
                     "`data/%s/events.jsonl`。移除比例超出實測日常區間，可能是抓取異常，"
                     "也可能是真的有大量項目同時自清單消失，詳見 `changes/%s/%s.md`。"
                     "人工確認後可手動處理（本程式不會自動重放此區間）。"
                     % (source, gname, source, source, d_new)),
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
    """total_match 完整性守門：data.total 必須存在且等於 len(items)（去重前，原始筆數）。
    回傳 (ok, total, n_items, reason)。"""
    items = data.get("items")
    if not isinstance(items, list):
        return False, None, None, "items 缺失或非清單"
    total = data.get(cfg["total_field"])
    n = len(items)
    if total is None:
        return False, total, n, "缺 total 欄位"
    if total != n:
        return False, total, n, "total(%r) != len(items)(%d)" % (total, n)
    return True, total, n, "total_match"


def dedup(items, key_field):
    """同鍵取最後出現的一筆。回傳 (dict[key->item], dup_keys 數量, missing_key 數量)。
    missing_key：主鍵欄位缺失或為空值的筆數，這類項目不參與比對（不計入 dup_keys，
    也不計入任何一邊的集合），x402_bazaar 實測 08-26～09-01 全部為 0。"""
    d = {}
    missing = 0
    for it in items:
        if not isinstance(it, dict):
            missing += 1
            continue
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

    return {
        "source": source, "d_old": d_old, "d_new": d_new, "f_old": f_old, "f_new": f_new,
        "gate_ok": gate_ok, "reason_old": reason_old, "reason_new": reason_new,
        "total_old": total_old, "total_new": total_new, "n_old": n_old, "n_new": n_new,
        "dup_old": dup_old, "dup_new": dup_new, "miss_old": miss_old, "miss_new": miss_new,
        "keyed_old": keyed_old, "keyed_new": keyed_new,
        "added_keys": added_keys, "removed_keys": removed_keys,
        "removed_rate": removed_rate, "breaker": breaker,
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
    removed_note = "" if judged == "NORMAL" else ("（%s，未寫入事件流）" % ("不判定" if judged == "GATE_FAIL" else "熔斷"))
    added_note = removed_note
    L.append("| **自清單消失**（實際差集筆數，%s） | **%d**%s |" %
              ("已寫入事件流為 `DELISTED`" if judged == "NORMAL" else "僅供人工參考，非正式事件",
               len(r["removed_keys"]), removed_note))
    L.append("| 新增（實際差集筆數，%s） | %d%s |" %
              ("已寫入事件流為 `LISTED`" if judged == "NORMAL" else "僅供人工參考，非正式事件",
               len(r["added_keys"]), added_note))
    L.append("| └─ 其中重新出現（先前記為自清單消失，本次又出現，%s） | %d%s |" %
              ("已另寫入事件流為 `REAPPEARED`" if judged == "NORMAL" else "僅供人工參考，非正式事件",
               n_reappeared, added_note))
    L.append("| 去重 dup_keys（前日／當日） | %d / %d |" % (r["dup_old"], r["dup_new"]))
    if r["miss_old"] or r["miss_new"]:
        L.append("| 主鍵缺失 missing_key（前日／當日） | %d / %d |" % (r["miss_old"], r["miss_new"]))
    L.append("| 完整性守門：前日 | %s（%s，total=%r, len(items)=%r） |" %
              ("通過" if r["reason_old"] == "total_match" else "**未通過**", r["reason_old"], r["total_old"], r["n_old"]))
    L.append("| 完整性守門：當日 | %s（%s，total=%r, len(items)=%r） |" %
              ("通過" if r["reason_new"] == "total_match" else "**未通過**", r["reason_new"], r["total_new"], r["n_new"]))
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
                  "`data.total` 與 `len(items)`（去重前）不相符，或缺 `total` 欄位。"
                  "上表的自清單消失／新增筆數僅為程式算出的原始差集，**未經完整性驗證，不代表正式判定**，"
                  "僅供人工評估用。")
        L.append("")
    if judged == "BREAKER":
        L.append("> 🔴 **熔斷觸發：removed 率 %.2f%% 超過門檻 %.1f%%，本日「自清單消失」的判定已暫停，"
                  "改寫入 `ALERT-DELIST.md`，等待人工確認。** 完整性守門本身是通過的（`total == len(items)` 兩側皆相符），"
                  "但移除比例超出日常區間（1.8%%~3.7%%），可能是抓取異常，也可能是真的有大量 resource 同時"
                  "自清單消失，本程式不自動判斷成因，僅陳述數字。"
                  % (r["removed_rate"], cfg["breaker_pct"]))
        L.append("")
    if r["removed_keys"]:
        L.append("## ⚠️ 自清單消失（%d）%s" % (len(r["removed_keys"]), "" if judged == "NORMAL" else "（未經完整性驗證）"))
        L.append("")
        for k in r["removed_keys"]:
            desc = short_desc(r["keyed_old"].get(k))
            L.append("- `%s`%s" % (k, (" — " + desc) if desc else ""))
        L.append("")
    if r["added_keys"]:
        extra = "（含 %d 筆重新出現，詳見下一節）" % n_reappeared if n_reappeared else ""
        L.append("## 新增（%d）%s%s" % (len(r["added_keys"]), extra, "" if judged == "NORMAL" else "（未經完整性驗證）"))
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

    new_events = []
    reappeared_from = {}
    if judged == "NORMAL":
        for k in r["removed_keys"]:
            new_events.append({"date": r["d_new"], "source": source, "group": source,
                                "key": k, "event": "DELISTED",
                                "from": short_desc(r["keyed_old"].get(k)), "to": None})
        for k in r["added_keys"]:
            new_events.append({"date": r["d_new"], "source": source, "group": source,
                                "key": k, "event": "LISTED",
                                "from": None, "to": short_desc(r["keyed_new"].get(k))})
            if k in last_delisted:
                # REAPPEARED（本輪新增）：這個 key 過去曾被記為消失，這次又出現在
                # added_keys 裡——在上面剛寫的 LISTED 事件之外，額外補寫這一筆，
                # 不取代 LISTED（兩者同一天、同時存在）。"from" 放上一次消失的日期，
                # 讓這一筆事件本身就能還原「消失了幾天」，見檔頭「事件型別語意定義」。
                reappeared_from[k] = last_delisted[k]
                new_events.append({"date": r["d_new"], "source": source, "group": source,
                                    "key": k, "event": "REAPPEARED",
                                    "from": last_delisted[k], "to": short_desc(r["keyed_new"].get(k))})
        # 用這一對快照本身的事實更新「最近一次消失日期」——跟下面 write_events()／
        # seen 判斷的「這筆事件是不是本次執行才第一次寫進檔案」完全無關：即使這筆
        # DELISTED 早就寫過（seen 命中，這次不會重複落地），這一對快照仍然「確實
        # 顯示」這個 key 在 r["d_new"] 這天消失，這件事實本身就是下一次牠重新出現時
        # 應該比對的基準，不能因為事件已經寫過就不更新這個狀態。
        for k in r["removed_keys"]:
            last_delisted[k] = r["d_new"]

    r["reappeared_from"] = reappeared_from

    jsonl_path = os.path.join(TRACK_CRYPTO, "data", source, "events.jsonl")
    fresh = write_events(jsonl_path, new_events, seen)
    seen.update((e["date"], e["source"], e["group"], e["key"], e["event"]) for e in fresh)

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
        if judged == "NORMAL":
            removed_cell = str(len(r["removed_keys"]))
            added_cell = str(len(r["added_keys"]))
            if reappeared_from:
                added_cell += "（含 %d 筆重新出現）" % len(reappeared_from)
        else:
            tag = "不判定" if judged == "GATE_FAIL" else "熔斷"
            removed_cell = "%d（%s）" % (len(r["removed_keys"]), tag)
            added_cell = "%d（%s）" % (len(r["added_keys"]), tag)
        entries_for_index.append(
            "| %s | `track-crypto/%s` | %s | %s | %s | [紀錄](changes/%s/%s.md) |"
            % (r["d_new"], source, EMDASH, removed_cell, added_cell, source, r["d_new"]))

    if judged == "GATE_FAIL":
        # 記錄 GATE_FAIL 事實供 healthcheck.py 告警用（specs/SPEC-gate-dedup.md）。
        # reason 文字直接沿用 completeness() 算出的 reason_old／reason_new，不重新
        # 詮釋（比照 scripts/healthcheck.py 的 check_cex_gate_skips() 對
        # gate_skips.jsonl reason 欄位的既有處理原則）。
        reasons = []
        if r["reason_old"] != "total_match":
            reasons.append("前日(%s)：%s（total=%r, len(items)=%r）"
                            % (r["d_old"], r["reason_old"], r["total_old"], r["n_old"]))
        if r["reason_new"] != "total_match":
            reasons.append("當日(%s)：%s（total=%r, len(items)=%r）"
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
            "",
            ("本日 `%s` 的「自清單消失」判定已**暫停**，未寫入 "
             "`data/%s/events.jsonl`。removed 率超過日常區間"
             "（1.8%%~3.7%%），可能是抓取異常，也可能是真的有大量 resource 同時"
             "自清單消失，詳見 `changes/%s/%s.md`。人工確認後可手動處理"
             "（本程式不會自動重放此區間）。"
             % (source, source, source, r["d_new"])),
        ]
        alert_written = write_alert_block(source, r["d_new"], lines)

    return judged, r, fresh, entries_for_index, alert_written


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
            else:
                normal_days += 1
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
            g_total_listed += n_listed
            g_total_delisted += n_delisted
            g_total_reappeared += n_reappeared
            g_total_status += n_status
            judged_summary = ",".join("%s=%s" % (g, gr["judged"]) for g, gr in group_results.items())
            for gr in group_results.values():
                if gr["judged"] == "GATE_FAIL":
                    g_gate_fail += 1
                elif gr["judged"] == "BREAKER":
                    g_breaker += 1
                else:
                    g_normal += 1
            print("%s: %s->%s [%s] 新事件 listed=%d delisted=%d reappeared=%d status_changed=%d%s"
                  % (source, d_old, d_new, judged_summary, n_listed, n_delisted, n_reappeared, n_status,
                     "  [ALERT-DELIST.md 已寫入]" if alert_written else ""))
            all_index_entries.extend(entries)

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
    return 0


if __name__ == "__main__":
    sys.exit(main())
