#!/usr/bin/env python3
"""OpenRouter 供應商清單 adapter（track-crypto，batch5／C8）。

只用 Python 標準函式庫。與 openrouter_models 同一主機，規格書建議可在
同一支排程內依序呼叫（先 /v1/models 再 sleep(1) 後打 /v1/providers），
但依 track-gov 慣例每個 KEY 各自一支獨立 adapter 檔，排程器可自行決定
是否共用同一次連線窗口。
"""

import json

KEY = "openrouter_providers"
DESC = "OpenRouter 供應商清單（隱私政策 / 服務條款 / 資料中心地點等）"
PARSER_VERSION = 1
SOURCE_HOME = "https://openrouter.ai/api/v1/providers"
ROBOTS_VERIFIED = (
    "2026-08-28 親驗 https://openrouter.ai/robots.txt：HTTP 200，"
    "User-Agent: * / Allow: / / Disallow: /seo/ （同 openrouter_models，同一主機）"
)

# 本輪重驗（2026-08-28，VPS）：全量 103 筆供應商，24,067B，name/slug 皆全數唯一。
MIN_PROVIDERS = 10


def _json(resp):
    """相容 fetch() 回傳 str（未解析）或 dict/list（已解析）兩種情況。"""
    return resp if isinstance(resp, (dict, list)) else json.loads(resp)


def collect(fetch) -> dict:
    """抓取 OpenRouter 供應商清單。

    fetch(url) 回傳原始回應內文（str）或已解析的 dict/list 皆可，
    本函式內部用 _json() 統一處理。失敗一律讓例外往上拋，不吞例外、不回傳空資料。
    """
    j = _json(fetch(SOURCE_HOME))
    providers = j.get("data") if isinstance(j, dict) else None
    if not isinstance(providers, list) or len(providers) < MIN_PROVIDERS:
        got = len(providers) if isinstance(providers, list) else 0
        raise RuntimeError(
            f"openrouter_providers：僅取得 {got} 筆，低於驗收下限 {MIN_PROVIDERS}，視為失敗"
        )

    slugs = set()
    for p in providers:
        if not isinstance(p, dict) or not (p.get("slug") or p.get("name")):
            raise RuntimeError(f"openrouter_providers：有筆缺 slug/name 欄位：{p!r}")
        slugs.add(p.get("slug") or p.get("name"))
    if len(slugs) != len(providers):
        raise RuntimeError(
            f"openrouter_providers：slug/name 有重複（{len(providers)} 筆僅 "
            f"{len(slugs)} 個唯一值）"
        )

    return {"count": len(providers), "providers": providers}
