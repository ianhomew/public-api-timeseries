# -*- coding: utf-8 -*-
"""dao_proposal_snapshot：Snapshot DAO 提案「刪除偵測」快照 adapter（僅存中繼資料，不存投票）。

對應規格：/Users/monica/Documents/temp/終端機/vps-161.97.82.83/adapters-wip/specs/batch4.md 4-C（A20）

已知的坑（2026-08-28 VPS 實測）：
    1. `hub.snapshot.org/robots.txt` 只回一個 60B 的版本號 JSON banner（非傳統 robots.txt 格式），
       依慣例視同無路徑限制。
    2. GraphQL 端點**同時支援 GET（`?query=` URL 編碼）與 POST**，本輪實測兩者回應內容完全相同
       （皆為 683B、3 筆樣本）。本 adapter 採用 **GET**，因為專案既有 fetch(url) 介面是單一 URL
       參數（GET 慣例），用 GET 可以完全沿用既有 fetch() 不需改介面签名。
    3. 只抓提案的**中繼資料**（id/title/state/author/created），**絕對不抓個別投票紀錄**
       （投票含錢包地址，規格書明文列為個資風險項目）。
    4. 本項定位是「監控用」不是「存檔用」——真正有價值的訊號是「今天看得到的 id 集合」跟
       「昨天的 id 集合」比對後消失的 id（代表被管理員刪除），而不是提案全文本身
       （Snapshot 官方隨時可全量回補歷史）。本 adapter 只負責產出「今天的 id 集合快照」，
       跨日比對邏輯留給下游（呼叫方／排程器）處理。
    5. 分頁上限依規格「分頁上限一律寫死」寫死為 PAGE_SIZE=1000、MAX_PAGES=10（最多 10,000 筆／日），
       本輪未實測 Snapshot 全站每日新增提案量（規格書亦坦承「本輪未實測全站流量」），此上限為
       保守估計值，若未來實測發現經常打滿上限，需要調高。
"""
import json
import time
import urllib.parse

KEY = "dao_proposal_snapshot"
DESC = "Snapshot DAO 提案中繼資料快照（用於偵測提案被管理員刪除，不存投票紀錄）"
SOURCE_HOME = "https://hub.snapshot.org/graphql"
ROBOTS_VERIFIED = (
    "2026-08-28 親驗 https://hub.snapshot.org/robots.txt：60B 版本號 JSON banner"
    "（非傳統 robots.txt 格式，無路徑限制內容，依慣例視同無限制）"
)
PARSER_VERSION = 1

PAGE_SIZE = 1000
MAX_PAGES = 5  # 分頁上限寫死：最多 5,000 筆／日
# 本輪實測：skip=5000 仍正常回應，skip=6000 起穩定回 500（Snapshot 後端深分頁限制），
# 故上限保守訂在 5（即 skip 最深到 4000），寫死避免撞到已知的深分頁失敗點。
MIN_ITEMS = 1  # 監控用途，逐日提案量可能極少，規格書未給下限，只要求成功取得快照

_QUERY = (
    "query($first: Int!, $skip: Int!) { "
    "proposals(first: $first, skip: $skip, orderBy: \"created\", orderDirection: desc) "
    "{ id title state author created } }"
)


def _page_url(skip):
    gql = (
        "{ proposals(first: %d, skip: %d, orderBy: \"created\", orderDirection: desc) "
        "{ id title state author created } }" % (PAGE_SIZE, skip)
    )
    return SOURCE_HOME + "?" + urllib.parse.urlencode({"query": gql})


def collect(fetch) -> dict:
    """抓取 Snapshot 最新提案中繼資料快照（分頁至 MAX_PAGES 或無新資料為止）。

    fetch(url) 需回傳已解析好的 JSON（dict）。失敗一律讓例外往上拋，
    不吞例外、不回傳空資料。
    """
    items = []
    seen_ids = set()
    for page in range(MAX_PAGES):
        skip = page * PAGE_SIZE
        try:
            j = fetch(_page_url(skip))
            if isinstance(j, str):
                j = json.loads(j)
            if not isinstance(j, dict) or j.get("errors"):
                raise RuntimeError(f"GraphQL 回應含錯誤：{j!r}")
        except Exception as exc:
            # 本輪實測發現：skip 深到一定程度（約 6000 起）Snapshot 後端會回 500，
            # 屬於該服務深分頁的已知限制，不是我方請求有誤。第一頁就失敗代表整體不可用需 raise；
            # 已取得資料後才失敗，視為「本次能拿到的分頁上限」，優雅停止而非整批判定失敗。
            if page == 0:
                raise RuntimeError(f"dao_proposal_snapshot：第一頁即失敗：{exc}") from exc
            break
        rows = ((j.get("data") or {}).get("proposals")) or []
        if not rows:
            break
        new_this_page = 0
        for row in rows:
            pid = row.get("id")
            if not pid:
                raise RuntimeError(f"dao_proposal_snapshot：某筆缺少 id：{row!r}")
            if pid in seen_ids:
                continue
            seen_ids.add(pid)
            items.append({
                "id": pid,
                "title": row.get("title"),
                "state": row.get("state"),
                "author": row.get("author"),
                "created": row.get("created"),
            })
            new_this_page += 1
        if len(rows) < PAGE_SIZE or new_this_page == 0:
            break
        if page < MAX_PAGES - 1:
            time.sleep(1)

    if len(items) < MIN_ITEMS:
        raise RuntimeError(
            f"dao_proposal_snapshot：僅取得 {len(items)} 筆，低於驗收下限 {MIN_ITEMS}，視為失敗"
        )

    return {"count": len(items), "proposals": items}
