# -*- coding: utf-8 -*-
"""vast_gpu：Vast.ai GPU 租賃市場報價快照 adapter（on-demand bundles）。

抓取邏輯原樣搬移自既有 track-crypto/scripts/snap_crypto.py 的 src_vast()：
limit=10000、type=on-demand、依 dph_total 由低到高排序；從 ~/snap/.env
讀 VAST_API_KEY 並帶 Bearer 認證（無金鑰時仍可匿名抓取，_authenticated
記為 False，與既有行為一致）；逾時設 90 秒（其他來源預設 45 秒）。
"""
import json
import os
import urllib.parse

KEY = "vast_gpu"
DESC = "Vast.ai GPU 租賃市場報價（on-demand bundles，依 dph_total 由低到高排序）"
SOURCE_HOME = "https://console.vast.ai/api/v0/bundles/"
ROBOTS_VERIFIED = (
    "2026-08-28 親驗 https://console.vast.ai/robots.txt：HTTP 200，"
    "User-agent: * / Allow: /（全站無 Disallow）"
)
PARSER_VERSION = 1

TIMEOUT = 90


def _load_env():
    """讀取 ~/snap/.env（與既有 track-crypto/scripts/snap_crypto.py 的
    load_env() 指向同一份檔案：track-crypto 的上上層目錄，即 ~/snap/.env）。
    金鑰讀不到時回傳空 dict，不視為錯誤（既有行為：允許匿名抓取）。
    """
    path = os.path.expanduser("~/snap/.env")
    env = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k] = v
    return env


def collect(fetch) -> dict:
    """回傳 Vast.ai bundles API 的原始 JSON，外加 _authenticated 欄位
    （既有既有欄位，標示本次抓取是否帶了金鑰）。
    """
    q = json.dumps({"limit": 10000, "type": "on-demand", "order": [["dph_total", "asc"]]})
    url = SOURCE_HOME + "?q=" + urllib.parse.quote(q)
    key = _load_env().get("VAST_API_KEY")
    hdr = {}
    if key:
        hdr["Authorization"] = "Bearer " + key
    raw = fetch(url, headers=hdr or None, timeout=TIMEOUT)
    j = json.loads(raw)
    j["_authenticated"] = bool(key)
    return j
