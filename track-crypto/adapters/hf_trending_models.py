#!/usr/bin/env python3
"""HuggingFace trending 模型清單 adapter（track-crypto，batch5／C9）。

只用 Python 標準函式庫。

已知的坑（2026-08-28 VPS 實測發現，推翻規格書假設）：
    HuggingFace `/api/models` 的 `limit` 參數實測上限固定為 **1000**，
    不論帶 limit=2000 或 limit=5000，回應都只有 1000 筆、位元組數完全相同
    （531,731B）。規格書原先建議「top 2000-5000」在此端點做不到，
    故本 adapter 固定使用 limit=1000（即該端點目前可取得的全量上限）。
    `likes`／`downloads`／`trendingScore` 為累計計數器（含近期加權，
    演算法未公開），依規格書指示**保留**這些欄位供下游追蹤，不視為
    需濾除的揮發性欄位；但逐日比較「內容是否改變」時，若要排除雜訊，
    下游需自行決定是否忽略 trendingScore 的微幅跳動。
"""

import json

KEY = "hf_trending_models"
DESC = "HuggingFace trending 模型清單（id / likes / downloads / trendingScore 等）"
PARSER_VERSION = 1
SOURCE_HOME = "https://huggingface.co/api/models?sort=trendingScore&limit=1000"
ROBOTS_VERIFIED = (
    "2026-08-28 親驗 https://huggingface.co/robots.txt：HTTP 200，"
    "User-Agent: * / Allow: / （全站無 Disallow）"
)

# 端點實測上限即為 1000（見上方模組說明），此常數即為分頁上限寫死值。
LIMIT = 1000
MIN_ITEMS = 500


def _json(resp):
    """相容 fetch() 回傳 str（未解析）或 dict/list（已解析）兩種情況。"""
    return resp if isinstance(resp, (dict, list)) else json.loads(resp)


def collect(fetch) -> dict:
    """抓取 HuggingFace trending 模型清單。

    fetch(url) 回傳原始回應內文（str）或已解析的 dict/list 皆可，
    本函式內部用 _json() 統一處理。失敗一律讓例外往上拋，不吞例外、不回傳空資料。
    """
    url = f"https://huggingface.co/api/models?sort=trendingScore&limit={LIMIT}"
    j = _json(fetch(url))
    if not isinstance(j, list) or len(j) < MIN_ITEMS:
        got = len(j) if isinstance(j, list) else 0
        raise RuntimeError(
            f"hf_trending_models：僅取得 {got} 筆，低於驗收下限 {MIN_ITEMS}，視為失敗"
        )

    mids = set()
    for m in j:
        mid = m.get("id") or m.get("modelId") if isinstance(m, dict) else None
        if not mid:
            raise RuntimeError(f"hf_trending_models：有筆缺 id/modelId 欄位：{m!r}")
        mids.add(mid)
    if len(mids) != len(j):
        raise RuntimeError(
            f"hf_trending_models：id 有重複（{len(j)} 筆僅 {len(mids)} 個唯一 id）"
        )

    return {"count": len(j), "models": j}
