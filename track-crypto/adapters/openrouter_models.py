#!/usr/bin/env python3
"""OpenRouter 全模型清單與定價 adapter（track-crypto，batch5／C1）。

只用 Python 標準函式庫。呼叫方（父代理的排程器）負責在每次 fetch() 後
time.sleep(1)、負責寫檔（write_gz），本檔只回傳可 JSON 序列化的原始資料。
"""

import json

KEY = "openrouter_models"
DESC = "OpenRouter 全模型清單與定價（id / pricing / context_length 等）"
PARSER_VERSION = 1
SOURCE_HOME = "https://openrouter.ai/api/v1/models"
ROBOTS_VERIFIED = (
    "2026-08-28 親驗 https://openrouter.ai/robots.txt：HTTP 200，"
    "User-Agent: * / Allow: / / Disallow: /seo/ （只擋 /seo/，不影響 /api/v1/models）"
)

# 本輪重驗（2026-08-28，VPS）：全量 387 筆模型，638,332B，id 全數唯一。
# 驗收下限沿用規格書「筆數下限 200」（規格書標示的「本輪實測 200」係指 HTTP 200 狀態碼，
# 不是模型筆數；筆數以本次重驗的 387 為準）。
MIN_MODELS = 200


def _json(resp):
    """相容 fetch() 回傳 str（未解析）或 dict/list（已解析）兩種情況。"""
    return resp if isinstance(resp, (dict, list)) else json.loads(resp)


def collect(fetch) -> dict:
    """抓取 OpenRouter 全模型清單。

    fetch(url) 回傳原始回應內文（str）或已解析的 dict/list 皆可，
    本函式內部用 _json() 統一處理。失敗一律讓例外往上拋，不吞例外、不回傳空資料。
    """
    j = _json(fetch(SOURCE_HOME))
    models = j.get("data") if isinstance(j, dict) else None
    if not isinstance(models, list) or len(models) < MIN_MODELS:
        got = len(models) if isinstance(models, list) else 0
        raise RuntimeError(
            f"openrouter_models：僅取得 {got} 筆，低於驗收下限 {MIN_MODELS}，視為失敗"
        )

    ids = set()
    for m in models:
        if not isinstance(m, dict) or "id" not in m or "pricing" not in m:
            raise RuntimeError(f"openrouter_models：有筆缺 id 或 pricing 欄位：{m!r}")
        ids.add(m["id"])
    if len(ids) != len(models):
        raise RuntimeError(
            f"openrouter_models：id 有重複（{len(models)} 筆僅 {len(ids)} 個唯一 id）"
        )

    return {
        "count": len(models),
        "total_count": j.get("total_count"),
        "models": models,
    }
