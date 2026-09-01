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


def process_pair(source, cfg, f_old, f_new, seen, last_delisted):
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
    total_listed = total_delisted = total_reappeared = 0
    normal_days = gate_fail_days = breaker_days = 0
    all_index_entries = []
    any_source = False
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
            judged, r, fresh, entries, alert_written = process_pair(source, cfg, f_old, f_new, seen, last_delisted)
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
    if not any_source:
        print("FATAL 白名單 SOURCES 為空", file=sys.stderr)
        return 1
    if all_index_entries:
        update_index(all_index_entries)
    print("SUMMARY listed=%d delisted=%d reappeared=%d normal_days=%d gate_fail_days=%d breaker_days=%d"
          % (total_listed, total_delisted, total_reappeared, normal_days, gate_fail_days, breaker_days))
    return 0


if __name__ == "__main__":
    sys.exit(main())
