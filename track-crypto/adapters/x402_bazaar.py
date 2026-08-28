# -*- coding: utf-8 -*-
"""x402_bazaar：x402 Bazaar 全量掛牌快照 adapter（Coinbase CDP x402 discovery API）。

抓取邏輯原樣搬移自既有 track-crypto/scripts/snap_crypto.py 的 src_x402()：
limit=1000 + offset 分頁，直到某頁為空、offset 超過 pagination.total、
或 offset 超過 100000（保險上限）為止；約 16 次請求。
"""
import json
import time

KEY = "x402_bazaar"
DESC = "x402 Bazaar 全量掛牌（Coinbase CDP x402 discovery API，分頁抓完）"
SOURCE_HOME = "https://api.cdp.coinbase.com/platform/v2/x402/discovery/resources"
ROBOTS_VERIFIED = (
    "2026-08-28 親驗 https://api.cdp.coinbase.com/robots.txt：HTTP 404（無 robots.txt，"
    "視為無限制；與既有 track-crypto/scripts/snap_crypto.py 沿用至今的抓取行為一致）"
)
PARSER_VERSION = 1

LIMIT = 1000
MAX_OFFSET = 100000


def collect(fetch) -> dict:
    """回傳 dict：{"x402Version": ..., "total": ..., "items": [...]}
    與既有快照格式完全相同，只是把「原本 fetch() 內建的 json.loads」
    改成由本 adapter 自行對 fetch() 回傳的原始字串呼叫 json.loads()
    （驅動程式的 fetch() 一律回傳未解析字串，介面統一）。
    """
    items, offset, j = [], 0, None
    while True:
        url = "%s?limit=%d&offset=%d" % (SOURCE_HOME, LIMIT, offset)
        raw = fetch(url)
        j = json.loads(raw)
        batch = j.get("items", [])
        items.extend(batch)
        pg = j.get("pagination", {}) or {}
        total = pg.get("total")
        offset += LIMIT
        if not batch or (total is not None and offset >= total) or offset > MAX_OFFSET:
            break
        time.sleep(1)
    return {"x402Version": (j or {}).get("x402Version"), "total": len(items), "items": items}
