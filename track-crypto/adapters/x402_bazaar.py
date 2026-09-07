# -*- coding: utf-8 -*-
"""x402_bazaar：x402 Bazaar 全量掛牌快照 adapter（Coinbase CDP x402 discovery API）。

抓取邏輯原樣搬移自既有 track-crypto/scripts/snap_crypto.py 的 src_x402()：
limit=1000 + offset 分頁，直到某頁為空、offset 超過 pagination.total、
或 offset 超過 100000（保險上限）為止；約 16 次請求。

============================================================================
2026-09-07 變更（SPEC：修掉恆真式完整性守門，見本機 docs/0907-D-x402-gate-report.md）：

【問題】本 adapter 原本回傳 {"x402Version", "total": len(items), "items"}，
其中 data.total 是 **adapter 自己算的 len(items)**，不是上游回報的總數。
而 track-crypto/scripts/detect_delistings.py 的 completeness() 守門做的是
「data.total 是否等於 len(items)」——被檢查的數字與自報的數字是同一個，
所以這個 total_match 守門 **恆為真**，對分頁截斷零防護力
（13 份歷史快照全部 total == len(items)，實證見 docs/0907-events-audit-0904-0907.md §8.1）。

【查證】2026-09-07 親打上游 API 確認：回應頂層有 pagination 物件，
內含 {"limit", "offset", "total"} 三個欄位，total 是 **上游自報的目錄總數**
（本輪兩次全量分頁實測 total 分別為 14698／14699，逐頁穩定不變）。
原 collect() 讀了 pg.get("total") 只拿來當迴圈終止條件，**沒有保存**，
所以這個真正有鑑別力的數字在寫入快照前就被丟掉了。

【修法】改為保存上游原始總數，並自報本次分頁是否完整：
  - "reported_total"：上游 pagination.total（取最後一頁讀到的值；找不到時 None）。
    這才是「獨立於 len(items)」的自報總數，供 detect_delistings.completeness() 比對。
  - "truncated"：本次**分頁迴圈**有沒有正常跑完（fail-closed：上游沒給 total、
    撞 MAX_OFFSET、或還沒抓滿就遇到空頁都算 True）。**不含**「筆數對不對得上」，
    那由 detect_delistings.completeness() 的容忍度檢查負責（見 collect() 內註解）。
    語意與 agent_virtuals／vast_gpu 的 data.truncated 一致，因此
    snap_crypto.py 的 _find_truncated_flag() 與 healthcheck.py 的
    check_truncation_streak() 不必修改就能涵蓋本來源。
  - "pagination"：逐頁稽核中繼資料（每頁筆數、每頁上游自報 total、停止原因），
    供日後診斷「哪一頁開始不對」。純量陣列不含 dict，因此
    snap_crypto._explore_subsets()（只收「元素為 dict 的 list」與 dict-of-dict）
    不會把它誤算進 manifest 的 n。

  - "total"：**保留不動**（仍是 len(items)）。理由：scripts/daily_report.py
    第 434／440 行與 scripts/explore.py 第 120／181 行都會讀軌一快照的
    data.total 當「本份快照有幾筆」，拿掉會直接弄壞這兩支程式；
    它作為「本次抓到幾筆」是誠實的，只是**不可以拿它自我比對當完整性守門**。

【抓取行為完全不變】分頁的 URL、limit、offset 步進、sleep(1)、以及三個終止條件
（本頁為空／offset >= 上游 total／offset > MAX_OFFSET）的**判斷順序與結果逐字元等價**，
只是把原本寫在同一個 or 運算式裡的三個條件拆成三個 if 以便記錄 stop_reason。
items 內容、筆數、順序皆與改動前完全相同。

【PARSER_VERSION 1 -> 2】輸出 schema 新增三個鍵，依 snap_crypto.py 檔頭
「PARSER_VERSION：解析邏輯版本號，變動時遞增，供 manifest 追蹤」的既有慣例遞增。
已查證影響範圍（證據見報告 §5）：
  - track-crypto/scripts/detect_delistings.py（下架偵測）**完全沒有** parser_version
    豁免機制（全檔 0 次出現），所以升版**不會**觸發任何下架判定的豁免／跳過。
  - scripts/detect_changes.py 的 parser_version 跳過機制**只作用於軌二 track-gov**，
    與本來源無關。
  - scripts/healthcheck.py 的 check_volume() 會在比較視窗（最多 7 天）內偵測到
    parser_version 改變而**暫時跳過體積異常判定**，只印 NOTICE、不寫 ALERT.md，
    視窗內全部變成新版本後自動恢復（該函式第 219~228 行）。這是一段有界、
    可自癒、不需人工白名單的副作用；期間 5% 熔斷與本次新增的 reported_total
    守門都照常運作。
============================================================================
"""
import json
import time

KEY = "x402_bazaar"
DESC = "x402 Bazaar 全量掛牌（Coinbase CDP x402 discovery API，分頁抓完）"
SOURCE_HOME = "https://api.cdp.coinbase.com/platform/v2/x402/discovery/resources"
ROBOTS_VERIFIED = (
    "2026-08-28 親驗 https://api.cdp.coinbase.com/robots.txt：HTTP 404（無 robots.txt，"
    "視為無限制；與既有 track-crypto/scripts/snap_crypto.py 沿用至今的抓取行為一致）；"
    "2026-09-07 再次親驗仍為 HTTP 404，另查 https://docs.cdp.coinbase.com/robots.txt "
    "為 200 且只 Disallow /cdn-cgi/ 與 /_next/（不含本 API 路徑）"
)
PARSER_VERSION = 2

LIMIT = 1000
MAX_OFFSET = 100000


def collect(fetch) -> dict:
    """回傳 dict：
    {"x402Version", "total", "reported_total", "truncated", "pagination", "items"}

    "total"          = len(items)（本次實際抓到幾筆；既有欄位，語意與值都不變）
    "reported_total" = 上游 pagination.total（獨立於 len(items) 的自報總數；None 代表上游沒給）
    "truncated"      = 本次分頁是否沒抓完（fail-closed，見下方判定）
    "pagination"     = 逐頁稽核中繼資料

    fetch() 一律回傳未解析字串，由本 adapter 自行 json.loads()（驅動程式介面統一）。
    """
    items, offset, j = [], 0, None
    page_counts = []   # 每一頁實得筆數
    page_totals = []   # 每一頁上游自報的 pagination.total（可能是 None）
    stop_reason = None
    while True:
        url = "%s?limit=%d&offset=%d" % (SOURCE_HOME, LIMIT, offset)
        raw = fetch(url)
        j = json.loads(raw)
        batch = j.get("items", [])
        items.extend(batch)
        pg = j.get("pagination", {}) or {}
        total = pg.get("total")
        page_counts.append(len(batch))
        page_totals.append(total)
        offset += LIMIT
        # 以下三個終止條件與改動前的
        #   if not batch or (total is not None and offset >= total) or offset > MAX_OFFSET: break
        # 判斷順序、短路行為、結果完全等價，只是拆開以記錄 stop_reason。
        if not batch:
            stop_reason = "empty_page"
            break
        if total is not None and offset >= total:
            stop_reason = "reached_reported_total"
            break
        if offset > MAX_OFFSET:
            stop_reason = "max_offset_guard"
            break
        time.sleep(1)

    # 上游自報總數：取最後一個「確實是整數」的 pagination.total。
    # 取最後一頁而非第一頁：最後一頁是本次分頁結束當下上游的最新視角，
    # 與 len(items) 的時間點最接近（本輪實測逐頁恆定，此選擇不影響現況，
    # 只是在上游中途變動時給出時間上最貼近的基準）。
    reported_total = None
    for t in reversed(page_totals):
        if isinstance(t, int) and not isinstance(t, bool):
            reported_total = t
            break

    # truncated 判定（fail-closed）。
    # 【語意界線，2026-09-07 沙盒實測後修正】truncated 只回報一件**結構性事實**：
    # 「分頁迴圈有沒有正常跑完」。它**不是**「筆數對不對得上」——後者是
    # detect_delistings.completeness() 的容忍度檢查負責的事，兩者不可混為一談。
    #   初版曾寫成 `truncated = len(items) < reported_total`，沙盒實跑立刻踩雷：
    #   當次上游 reported_total=14700、實得 14699（活的目錄在 45 秒分頁期間自然
    #   變動 1 筆），truncated 被誤設為 True -> 守門 fail-closed 直接 GATE_FAIL，
    #   而且會把 manifest 的 truncated 從 false 翻成 true（healthcheck.py 的
    #   check_truncation_streak() 連續 2 天就會告警）。差 1 筆是常態不是截斷，
    #   這種寫法會天天誤報。改成只看 stop_reason：
    #   1. 上游根本沒給總數 -> 無從證明抓完 -> True。
    #   2. 撞到 MAX_OFFSET 保險上限才停 -> 明確沒抓完 -> True。
    #   3. 還沒抓到上游宣稱的總數就遇到空頁 -> 中途斷掉 -> True。
    #   4. offset 正常追過上游總數而停（reached_reported_total）-> 迴圈跑完 -> False。
    #      此時筆數若與上游總數有小落差，交給 completeness() 的容忍度判斷，
    #      不在這裡改寫成「截斷」這個不同的語意。
    if reported_total is None:
        truncated = True
    elif stop_reason == "max_offset_guard":
        truncated = True
    elif stop_reason == "empty_page":
        truncated = len(items) < reported_total
    else:  # reached_reported_total
        truncated = False

    return {
        "x402Version": (j or {}).get("x402Version"),
        "total": len(items),
        "reported_total": reported_total,
        "truncated": truncated,
        "pagination": {
            "limit": LIMIT,
            "pages": len(page_counts),
            "page_counts": page_counts,
            "page_totals": page_totals,
            "stop_reason": stop_reason,
        },
        "items": items,
    }
