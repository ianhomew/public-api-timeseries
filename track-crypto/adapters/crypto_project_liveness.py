# -*- coding: utf-8 -*-
"""crypto_project_liveness：DefiLlama 駭客事件清單（死亡監控資料面）。

對應規格：/Users/monica/Documents/temp/終端機/vps-161.97.82.83/adapters-wip/specs/batch4.md 4-B（A21）

**範疇裁示（本輪自行決定，見下方說明）**：
    規格書 4-B 明確指出 A21 本質上是兩件不同的工作：
    (1) `/hacks` 端點——現成、單次請求即可拿到的資料，本 adapter 已實作。
    (2) 「死亡證明監控」（逐日對一份自建的加密專案網域清單做 DNS/HTTP 存活檢測）——
        規格書明文表示這需要「使用者或後續研究先確認要監控哪些網域、幾個、清單來源」，
        本規格書本身**沒有**提供具體網域清單。

    本輪決定：**只實作 (1)，不擅自捏造網域清單去做 (2)**。理由：
    - 規格書已明確把 (2) 列為「附加工作」且明講範疇未定，不是本批次的必要交付物。
    - 隨意挑選幾個「聽起來很像已死掉的專案」網域來源沒有事實根據，一旦誤判存活狀態
      （例如域名被轉手重新啟用、或本輪選的域名根本不是規格書原意指的那個），
      反而會製造品質更差的假資料，风险大於留白。
    - 已在下方提供 `check_domain_liveness()` 這個獨立、隨時可用的工具函式（DNS 查詢 + HTTP
      HEAD，只用標準函式庫），一旦未來確定監控清單，可直接接上使用，不需要重新設計。

只用 Python 標準函式庫。
"""
import socket
import time
import urllib.error
import urllib.request

import json

KEY = "crypto_project_liveness"
DESC = "DefiLlama 駭客事件清單（死亡監控資料面；網域存活監控面本輪列為未實作，見模組說明）"
SOURCE_HOME = "https://api.llama.fi/hacks"
ROBOTS_VERIFIED = "2026-08-28 親驗 https://api.llama.fi/robots.txt：HTTP 404（無 robots.txt，視為無限制）"
PARSER_VERSION = 1

MIN_ITEMS = 300


def _json(resp):
    """相容 fetch() 回傳 str（未解析）或 dict/list（已解析）兩種情況。"""
    return resp if isinstance(resp, (dict, list)) else json.loads(resp)


def collect(fetch) -> dict:
    """抓取 DefiLlama 駭客事件清單。

    fetch(url) 回傳原始回應內文（str）或已解析的 dict/list 皆可，
    本函式內部用 _json() 統一處理。失敗一律讓例外往上拋，不吞例外、不回傳空資料。
    """
    j = _json(fetch(SOURCE_HOME))
    if not isinstance(j, list) or len(j) < MIN_ITEMS:
        got = len(j) if isinstance(j, list) else 0
        raise RuntimeError(
            f"crypto_project_liveness：僅取得 {got} 筆，低於驗收下限 {MIN_ITEMS}，視為失敗"
        )

    for row in j:
        if not isinstance(row, dict) or "name" not in row or "date" not in row:
            raise RuntimeError(f"crypto_project_liveness：有筆缺 name 或 date 欄位：{row!r}")

    return {
        "count": len(j),
        "hacks": j,
        "domain_liveness": {
            "status": "not_implemented",
            "reason": (
                "規格書 4-B 明確指出監控網域清單範疇未定，需使用者或後續研究先確認要監控"
                "哪些網域，本輪不擅自捏造清單；check_domain_liveness() 工具函式已備妥可直接接用。"
            ),
        },
    }


def check_domain_liveness(domain, timeout=10):
    """對單一網域做「死亡證明」檢測：DNS 是否可解析、HTTP HEAD 是否可連線。

    這是給未來監控清單使用的獨立工具函式，本輪 collect() 未呼叫它（見模組說明）。
    只用標準函式庫（socket + urllib），呼叫端需自行在每個網域之間 time.sleep(1)。

    回傳 dict：{"domain", "checked_at", "dns_resolved", "http_status"}
    dns_resolved 為 False 或 http_status 為 None 都代表該網域疑似已死。
    """
    from datetime import datetime, timezone

    result = {
        "domain": domain,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "dns_resolved": False,
        "http_status": None,
    }
    try:
        socket.gethostbyname(domain)
        result["dns_resolved"] = True
    except socket.gaierror:
        return result

    for scheme in ("https://", "http://"):
        try:
            req = urllib.request.Request(scheme + domain, method="HEAD")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                result["http_status"] = r.status
                return result
        except urllib.error.HTTPError as e:
            result["http_status"] = e.code
            return result
        except Exception:
            continue
    return result
