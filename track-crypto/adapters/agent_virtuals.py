# -*- coding: utf-8 -*-
"""agent_virtuals：Virtuals Protocol agent 清單快照 adapter（api.virtuals.io）。

批次：Batch 3（MCP／agent 生態目錄）。
只用標準函式庫。每次 HTTP 請求後 time.sleep(1)。

【父代理裁示】採「精簡欄位」方案（約每日 4–5 MB，而非全量約 68 MB）。
本輪重驗（2026-08-28）total=82,095（相近於規格書記載的 82,093，屬呼叫間自然變動）。
精簡欄位需足以偵測「代幣消失／狀態變更／價格條件改變」，故保留
id/virtualId/name/symbol/status/tokenAddress/category/totalValueLocked/createdAt，
捨棄 description（長文字）、socials（巢狀連結/縮圖 URL）等高體積低邊際資訊欄位。

【Batch 3 修正（B3_FIX_SPEC.md，2026-08-2x）】
VPS 隔離環境實測：165 頁全跑完耗時 1,565.8 秒（約 26 分鐘），且執行期間完全無輸出，
父代理因此誤判為卡死。修正重點：
1. 分頁硬上限維持保守值 MAX_PAGES=200（略高於實測 pageCount=165，非無限翻頁）。
2. 每請求逾時 REQUEST_TIMEOUT=30 秒（fetch(url, timeout=30)），不使用預設逾時。
3. 每抓 PROGRESS_EVERY=20 頁印一行進度到 stdout（flush=True），
   讓外部觀察者可分辨「正常工作中」與「卡死」。
4. 總時間預算 TIME_BUDGET_SECS=600 秒：超過即停止翻頁，回傳已取得資料並標記
   truncated=True、pages_fetched=N（有總比沒有好，但誠實告知下游是截斷結果）。
   截斷情況下不套用 50,000 筆下限（該下限只用來偵測「非截斷情況下」API 明顯縮水
   或分頁邏輯失效；截斷是預期中的正常降級行為，不應被判定為失敗）。
"""
import json
import time

KEY = "agent_virtuals"
DESC = "Virtuals Protocol agent 清單（精簡欄位：id/status/tokenAddress 等，用於偵測代幣消失與狀態變更）"
SOURCE_HOME = "https://api.virtuals.io/api/virtuals?pagination[page]=N&pagination[pageSize]=500"
ROBOTS_VERIFIED = (
    "2026-08-28 親驗 https://api.virtuals.io/robots.txt：Content-Signal 格式，"
    "search=yes（預設）, ai-train=no；User-agent: * 未見路徑 Disallow"
)
PARSER_VERSION = 2

BASE = "https://api.virtuals.io/api/virtuals"
PAGE_SIZE = 500
MAX_PAGES = 200  # 硬上限（本輪實測 pageCount=165），不無限翻頁
REQUEST_TIMEOUT = 30  # 每請求逾時秒數，不用預設值等到天荒地老
PROGRESS_EVERY = 20  # 每 N 頁印一次進度
TIME_BUDGET_SECS = 600  # 總時間預算，超過即停止翻頁並標記 truncated
FULL_RUN_MIN_ITEMS = 50000  # 僅在「未截斷」情況下才用此下限判斷是否異常縮水

# 精簡欄位清單：只保留足以偵測「代幣消失／狀態變更／存續判斷」的欄位
KEEP_FIELDS = (
    "id", "virtualId", "name", "symbol", "status",
    "tokenAddress", "category", "totalValueLocked", "createdAt",
)
DROPPED_FIELDS_NOTE = (
    "已捨棄欄位（依父代理裁示，精簡欄位方案，理由：長文字/連結類欄位逐日重複儲存邊際資訊很低）："
    "description、socials、uid、walletAddress、image、roadmap、tokenomics 等其餘全部原始欄位"
    "（僅保留 KEEP_FIELDS 常數所列 9 個欄位）"
)


def collect(fetch) -> dict:
    """回傳 dict：
    {"items": [<精簡欄位>], "total_returned": N, "total_reported": M,
     "dropped_fields_note": "...", "truncated": bool, "pages_fetched": N,
     "avg_bytes_per_item": float}
    以 id 去重。
    - 未截斷時，驗收下限 50,000 筆（用來偵測 API 是否明顯縮水或分頁邏輯失效）。
    - 截斷時（超過 MAX_PAGES 或 TIME_BUDGET_SECS）不套用該下限，只要求非空，
      並誠實標記 truncated=True，讓下游知道這是部分資料。
    """
    t0 = time.time()
    items = []
    seen = set()
    total_reported = None
    page = 1
    pages_fetched = 0
    truncated = False

    while page <= MAX_PAGES:
        elapsed = time.time() - t0
        if elapsed > TIME_BUDGET_SECS:
            truncated = True
            print(
                "agent_virtuals: 總時間預算 %ds 已用盡，於第 %d 頁停止，已取得 %d 筆"
                % (TIME_BUDGET_SECS, page - 1, len(items)),
                flush=True,
            )
            break

        url = "%s?pagination[page]=%d&pagination[pageSize]=%d" % (BASE, page, PAGE_SIZE)
        raw = fetch(url, timeout=REQUEST_TIMEOUT)
        pages_fetched += 1
        time.sleep(1)
        j = json.loads(raw)
        batch = j.get("data", []) or []
        meta = (j.get("meta", {}) or {}).get("pagination", {}) or {}
        if total_reported is None:
            total_reported = meta.get("total")
        if not batch:
            break
        for d in batch:
            rid = d.get("id")
            if rid is None or rid in seen:
                continue
            seen.add(rid)
            items.append({k: d.get(k) for k in KEEP_FIELDS})

        if page % PROGRESS_EVERY == 0:
            page_count_hint = meta.get("pageCount")
            print(
                "agent_virtuals: 第 %d/%s 頁，已取得 %d 筆"
                % (page, page_count_hint if page_count_hint is not None else "?", len(items)),
                flush=True,
            )

        page_count = meta.get("pageCount")
        if page_count is not None and page >= page_count:
            break
        if page >= MAX_PAGES:
            truncated = True
            print(
                "agent_virtuals: 已達分頁硬上限 MAX_PAGES=%d，停止翻頁，已取得 %d 筆"
                % (MAX_PAGES, len(items)),
                flush=True,
            )
            break
        page += 1

    if not truncated and len(items) < FULL_RUN_MIN_ITEMS:
        raise RuntimeError(
            "agent_virtuals：僅取得 %d 筆（去重後），低於驗收下限 %d 筆"
            % (len(items), FULL_RUN_MIN_ITEMS)
        )
    if truncated and len(items) == 0:
        raise RuntimeError("agent_virtuals：截斷後仍取得 0 筆，判定為異常")
    for it in items:
        if it.get("id") is None or it.get("status") is None:
            raise RuntimeError("agent_virtuals：回應筆缺少必要欄位 id/status")

    items_bytes = len(json.dumps(items, ensure_ascii=False).encode("utf-8"))
    avg_bytes_per_item = (items_bytes / len(items)) if items else 0.0
    total_secs = time.time() - t0
    print(
        "agent_virtuals: 完成，共 %d 頁、%d 筆，耗時 %.1fs，平均 %.1f B/筆，truncated=%s"
        % (pages_fetched, len(items), total_secs, avg_bytes_per_item, truncated),
        flush=True,
    )

    return {
        "items": items,
        "total_returned": len(items),
        "total_reported": total_reported,
        "dropped_fields_note": DROPPED_FIELDS_NOTE,
        "truncated": truncated,
        "pages_fetched": pages_fetched,
        "avg_bytes_per_item": avg_bytes_per_item,
    }
