# -*- coding: utf-8 -*-
"""mcp_smithery：Smithery MCP 註冊表快照 adapter（registry.smithery.ai）。

批次：Batch 3（MCP／agent 生態目錄）。
只用標準函式庫。每次 HTTP 請求後 time.sleep(1)。

【已知硬限制，實作前必讀】
本輪重驗（2026-08-28）證實：無論 pageSize 為何，最多只能翻到「第 5 頁」
（pageSize=100 時 page=6 已回 0 筆，即使 pagination.totalCount 仍誠實回報
全量約 10,916 筆）。用 q= 做字母分片查詢也不可靠（q=a/e/x 分別回 196/182/195
筆，幾乎不隨字母常見度變化，顯示是模糊搜尋而非前綴比對，無法用來拼出全量）。
父代理裁示：先實作 500 筆上限的可靠版本，在 _meta 誠實標示「非全量」。

【Batch 3 修正（B3_FIX_SPEC.md）：驗收下限誤判，已用實測數據重新校準】
VPS 隔離環境實測：page1-5（pageSize=100）去重後僅 271 筆，觸發舊版 500 筆下限
的 `raise`。已實際打端點逐頁核對，證實這**不是分頁邏輯寫錯**，而是端點本身的
排序在跨頁請求之間會漂移（很可能依 useCount 即時排序，非穩定分頁快照），
導致同一筆資料在不同頁反覆出現：
    page=1 n=100 dup_with_prev=0
    page=2 n=100 dup_with_prev=38
    page=3 n=100 dup_with_prev=57
    page=4 n=100 dup_with_prev=62
    page=5 n=100 dup_with_prev=72
    page=6 n=0（硬性翻頁上限重測仍成立）
    去重後總計 271 筆（實測時間點；totalCount 同時段自報 10,916~10,924，會自然變動）
即使把 5 頁的 500 筆原始資料全部去重，能拿到的「新」資料上限就是 271 筆左右，
不是 API 端限量成 271，而是**排序漂移造成的必然重疊上限**，屬端點本身特性。
因此「500 筆」這個舊下限本來就不可能達成，是拍腦袋數字，不是實測值。
新下限依父代理指示改為「實測值的 80%」：271 * 0.8 ≈ 216.8，取整數 200
（用來偵測「大幅掉量／端點行為改變」，不是用來否定 271 這個正常結果）。
覆蓋率誠實標示於 DESC：實得約 271 筆 / 官方宣稱總數約 10,916 筆（約 2.5%）。
"""
import json
import time

KEY = "mcp_smithery"
DESC = (
    "Smithery MCP 註冊表（依 API 預設排序前段可見範圍，非全量；"
    "覆蓋率實測約 271 筆 / 官方宣稱總數約 10,916 筆，約 2.5%。"
    "API 硬性只能翻到第 5 頁，且跨頁排序會漂移造成大量重疊，"
    "271 筆左右是去重後可拿到的實際上限，非人為限量）"
)
SOURCE_HOME = "https://registry.smithery.ai/servers?page=N&pageSize=100"
ROBOTS_VERIFIED = (
    "2026-08-28 親驗 https://registry.smithery.ai/robots.txt：Content-Signal 格式，"
    "User-agent: * 未見 Disallow（一般語意為 Allow: /），"
    "僅具名爬蟲黑名單（ClaudeBot/GPTBot/CCBot 等 token）才會被排除；"
    "本 adapter 使用的 UA 字串不含這些具名 token"
)
PARSER_VERSION = 2

BASE = "https://registry.smithery.ai/servers"
PAGE_SIZE = 100
MAX_PAGE = 5  # 硬性上限：本輪實測 page=6 恆回 0 筆（API 本身的翻頁深度上限）
REQUEST_TIMEOUT = 30

# 驗收下限依實測值 271 校準（271 * 0.8 ≈ 216.8 → 取 200），用來偵測「大幅掉量」，
# 不是拍腦袋寫死的 500。若日後實測穩定值明顯不同，應重新校準此常數。
MIN_ITEMS = 200


def collect(fetch) -> dict:
    """回傳 dict：
    {"servers": [...], "total_returned": N, "total_count_reported": M,
     "is_full": False, "coverage_note": "..."}
    servers 以 id 去重；is_full 恆為 False（本 API 已知無法取得全量），
    誠實標示覆蓋率限制，不謊稱是全量快照。
    """
    servers = []
    seen = set()
    total_count_reported = None
    for page in range(1, MAX_PAGE + 1):
        url = "%s?page=%d&pageSize=%d" % (BASE, page, PAGE_SIZE)
        raw = fetch(url, timeout=REQUEST_TIMEOUT)
        time.sleep(1)
        j = json.loads(raw)
        batch = j.get("servers", []) or []
        pagination = j.get("pagination", {}) or {}
        if total_count_reported is None:
            total_count_reported = pagination.get("totalCount")
        if not batch:
            break
        for s in batch:
            sid = s.get("id")
            if sid is None or sid in seen:
                continue
            seen.add(sid)
            servers.append(s)

    if len(servers) < MIN_ITEMS:
        raise RuntimeError(
            "mcp_smithery：僅取得 %d 筆（去重後），低於驗收下限 %d 筆"
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
    return {
        "servers": servers,
        "total_returned": len(servers),
        "total_count_reported": total_count_reported,
        "is_full": False,
        "coverage_note": (
            "API 硬性限制最多翻到第 %d 頁（pageSize=%d），且跨頁排序會漂移造成大量重疊，"
            "去重後僅得約 %d 筆（覆蓋率約 %s%%），非人為限量而是端點本身特性。"
            "q= 分片查詢經實測不可靠（不同字母命中數幾乎不變），未採用。"
            "逐日比較需以 id 對齊，不可假設同一名次是同一 server。"
            % (
                MAX_PAGE,
                PAGE_SIZE,
                len(servers),
                ("%.1f" % coverage_pct) if coverage_pct is not None else "未知",
            )
        ),
    }
