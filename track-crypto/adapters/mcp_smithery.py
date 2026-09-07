# -*- coding: utf-8 -*-
"""mcp_smithery：Smithery MCP 註冊表快照 adapter（registry.smithery.ai）。

批次：Batch 3（MCP／agent 生態目錄）。
只用標準函式庫。每次 HTTP 請求後 time.sleep(REQUEST_DELAY)。

═══════════════════════════════════════════════════════════════════════════
【2026-09-07 根因修正：推翻「API 有 500 筆硬上限、無法取得全量」的舊結論】
═══════════════════════════════════════════════════════════════════════════
舊版寫死 MAX_PAGE = 5、is_full = False，只取得 272 / 11,811 筆（2.3%），
並在交接文件記為「端點分頁上限造成的結構性限制，無法用分頁抓全量」。
本輪實測證明**該結論是錯的**，真正的根因是「未帶 seed 參數」：

  1. 不帶 seed：端點走「相關性／向量排序的 browse 模式」。
     - pagination.totalPages 被夾在 500/pageSize（pageSize=1→500 頁、
       10→50 頁、50→10 頁、100→5 頁，乘積恆為 500），page=6 回 200 + 空陣列。
     - 跨頁排序不穩定，5 頁 500 筆原始資料重複率 46%，去重後只剩 271~272 筆。
     - useCount 在頁內與跨頁都不是單調遞減（page=4 首筆 9002 > page=1 末筆 6583）。
  2. 帶任意整數 seed（值不影響結果，seed=1 與 seed=42 回傳完全相同的順序）：
     端點改走「確定性排序路徑（useCount DESC）」。
     - pagination.totalPages 變成 ceil(totalCount / pageSize) = 119，**500 窗口解除**。
     - 跨頁重複率 0%，120 頁掃完得 11,814 筆唯一，覆蓋率 100.0%。
     - 耗時 214 秒（含每頁 1 秒禮貌延遲），下載 9.64 MB（gzip 後 2.69 MB）。

實測佐證（2026-09-07，完整請求／回應存於
docs/0907-A-smithery-evidence/）：
    無 seed：page=1..5 各 100 筆，dup=0/37/57/62/73 → 去重 271 筆；page=6 空陣列
    有 seed：page=1..119 各 100 筆，dup 全為 0；page=120 空陣列 → 11,814 筆
另：舊版取得的 271 筆連「useCount 前 272 名」都不是（漏掉其中 78 個，29%），
證明未帶 seed 時取回的並非「前 500 名」，而是排序不穩定下的任意子集。

官方 OpenAPI 3.1 規格（app.stainless.com/api/spec/documented/smithery/
openapi.documented.yml）確有 seed 參數；CHANGELOG 0.55.0 說明其用途為
"duplicate-free browse pagination"。規格中「hard cap of 500」是綁在 topK
（語意搜尋的候選數）上，不是綁在分頁深度上——舊結論把兩者混為一談。

【資料使用限制】registry.smithery.ai/robots.txt 的 Content-Signal 為
search=yes, ai-train=no, use=reference。本專案用途為快照存檔與時序比對
（reference），**不得將本資料用於訓練或微調 AI 模型**。
"""
import json
import time

KEY = "mcp_smithery"
DESC = (
    "Smithery MCP 註冊表全量清單（registry.smithery.ai/servers，帶 seed 參數走"
    "確定性 useCount DESC 排序，逐頁抓到空陣列為止）。"
    "2026-09-07 實測覆蓋率 11,814 / 自報總數 11,813 = 100%，跨頁重複率 0%。"
)
SOURCE_HOME = "https://registry.smithery.ai/servers?page=N&pageSize=100&seed=1"
ROBOTS_VERIFIED = (
    "2026-09-07 親驗 https://registry.smithery.ai/robots.txt：Content-Signal 格式，"
    "User-agent: * → Allow: /（明文允許）；僅具名爬蟲黑名單"
    "（Amazonbot/Applebot-Extended/Bytespider/CCBot/ClaudeBot/"
    "CloudflareBrowserRenderingCrawler/Google-Extended/GPTBot/meta-externalagent）"
    "被 Disallow: /，本 adapter 使用的 UA 字串不含這些 token。"
    "Content-Signal: search=yes,ai-train=no,use=reference —— 本專案屬 reference 用途，"
    "不得用於 AI 訓練。"
)
# v2 → v3：改帶 seed 參數解除 500 筆窗口，筆數由 272 變為約 11,800。
# 這是解析／抓取邏輯的重大變更，必須遞增，讓 detect_changes.py 的
# 「parser_version 不同就跳過下架判定」保護生效，避免 11,542 筆新 id
# 被誤判為大規模上架／下架事件。
PARSER_VERSION = 3

BASE = "https://registry.smithery.ai/servers"
PAGE_SIZE = 100          # 官方 schema 上限，pageSize=101 直接回 400
SEED = 1                 # 任意整數即可；實測 seed 值不影響回傳內容與順序，
                         # 但「有沒有帶」決定走不走確定性排序路徑（見檔頭說明）。
                         # 固定值可讓逐日排序穩定，縮小逐日 diff。
MAX_PAGES = 400          # 安全上限。目前實際約 119 頁；設 400 是為了在端點筆數
                         # 成長時仍能抓滿，同時防止端點行為改變導致無限迴圈。
DEADLINE_SECS = 900      # 本 adapter 自身的時間預算（15 分鐘）。實測 214 秒，
                         # 留約 4 倍餘裕。超時就停止翻頁並誠實標示未取得全量。
REQUEST_DELAY = 1.0      # 每次請求後的禮貌延遲
REQUEST_TIMEOUT = 30

# 驗收下限：2026-09-07 實測 11,814 筆。取實測值的 70%（約 8,270）→ 取整 8000。
# 用來偵測「大幅掉量／端點行為改變（例如 seed 參數被移除、又退回 500 窗口）」，
# 不是用來否定正常的自然增減。若日後穩定值明顯不同，應重新校準此常數。
MIN_ITEMS = 8000

# is_full 判定容差：抓取過程約 3.5 分鐘，期間 totalCount 會自然增減
# （實測同一輪內在 11,803~11,814 之間漂移），因此不要求恰好相等。
COVERAGE_TOLERANCE_PCT = 2.0


def collect(fetch) -> dict:
    """回傳 dict：
    {"servers": [...], "total_returned": N, "total_count_reported": M,
     "pages_fetched": P, "dup_skipped": D, "is_full": bool, "coverage_note": "..."}

    servers 以 id 去重（帶 seed 時實測重複率 0%，去重只是防禦性保留）。
    is_full 依「實得筆數 vs 端點自報 totalCount」實際計算，不再寫死 False：
    只有在覆蓋率達標且未因安全上限／時間預算提前中止時才為 True。
    """
    t0 = time.time()
    servers = []
    seen = set()
    total_count_reported = None
    dup_skipped = 0
    pages_fetched = 0
    stop_reason = "exhausted"

    for page in range(1, MAX_PAGES + 1):
        if time.time() - t0 > DEADLINE_SECS:
            stop_reason = "deadline"
            break
        url = "%s?page=%d&pageSize=%d&seed=%d" % (BASE, page, PAGE_SIZE, SEED)
        raw = fetch(url, timeout=REQUEST_TIMEOUT)
        time.sleep(REQUEST_DELAY)
        pages_fetched += 1
        j = json.loads(raw)
        batch = j.get("servers", []) or []
        pagination = j.get("pagination", {}) or {}
        # 每頁都覆寫：取最後一頁看到的值，最貼近抓取結束當下的真實總數
        if pagination.get("totalCount") is not None:
            total_count_reported = pagination.get("totalCount")
        if not batch:
            break
        for s in batch:
            sid = s.get("id")
            if sid is None:
                raise RuntimeError("mcp_smithery：回應筆缺少 id 欄位，無法去重")
            if sid in seen:
                dup_skipped += 1
                continue
            seen.add(sid)
            servers.append(s)
    else:
        # for 迴圈跑滿 MAX_PAGES 都沒遇到空陣列 → 可能還有資料沒抓完
        stop_reason = "max_pages"

    if len(servers) < MIN_ITEMS:
        raise RuntimeError(
            "mcp_smithery：僅取得 %d 筆（去重後），低於驗收下限 %d 筆。"
            "常見原因：端點移除 seed 參數支援而退回 500 筆窗口模式，"
            "或端點結構改變。請重新驗證分頁契約後再校準本常數。"
            % (len(servers), MIN_ITEMS)
        )
    for s in servers:
        if "id" not in s or "qualifiedName" not in s or "useCount" not in s:
            raise RuntimeError("mcp_smithery：回應筆缺少必要欄位 id/qualifiedName/useCount")

    coverage_pct = (
        (len(servers) / total_count_reported * 100.0)
        if total_count_reported
        else None
    )
    is_full = bool(
        stop_reason == "exhausted"
        and coverage_pct is not None
        and coverage_pct >= (100.0 - COVERAGE_TOLERANCE_PCT)
    )
    return {
        "servers": servers,
        "total_returned": len(servers),
        "total_count_reported": total_count_reported,
        "pages_fetched": pages_fetched,
        "dup_skipped": dup_skipped,
        "stop_reason": stop_reason,
        "is_full": is_full,
        "coverage_note": (
            "帶 seed=%d 走確定性 useCount DESC 排序，逐頁抓到空陣列為止："
            "共 %d 頁、去重後 %d 筆、跨頁重複 %d 筆，"
            "端點自報總數 %s，覆蓋率 %s%%，中止原因 %s。"
            "（不帶 seed 時端點只開放 500 筆窗口且跨頁重複率 46%%，"
            "去重後僅得約 271 筆——這是 2026-09-07 之前的舊行為，已修正。）"
            % (
                SEED,
                pages_fetched,
                len(servers),
                dup_skipped,
                total_count_reported,
                ("%.1f" % coverage_pct) if coverage_pct is not None else "未知",
                stop_reason,
            )
        ),
    }
