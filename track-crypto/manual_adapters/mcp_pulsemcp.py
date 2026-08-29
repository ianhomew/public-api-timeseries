# -*- coding: utf-8 -*-
"""mcp_pulsemcp：PulseMCP 註冊表快照 adapter（api.pulsemcp.com）。

批次：Batch 3（MCP／agent 生態目錄）。
只用標準函式庫。每次 HTTP 請求後 time.sleep(1)（本 adapter 僅發 1 次請求，無需迴圈）。

【已知不穩定來源，實作前必讀】
2026-08-28 本輪重驗直接證實候選文件所述「隨機讓請求失敗以推動下線」為真：
同一天、同一端點，前後 15 分鐘內一次 200、一次 410。本子代理本輪（08:xx UTC）
再次呼叫，回應為 HTTP 410，內文明確帶官方棄用時間表：
  {"error":{"code":"API_SUNSET","message":
    "The v0beta API is deprecated and being sunset. This request was randomly
     failed as part of the sunset process. Starting January 2026: 1% of
     requests fail. Starting April 2026: 10%. Starting June 2026: 50%.
     September 2026: Fully sunset (100%). ..."}}
即：撰寫本檔案當下（2026-08-28）官方排程的隨機失敗率已達 50%，且本 API 將於
2026-09（約 1 個月後）100% 完全停用。這不是暫時性錯誤，是官方主動棄用流程。

本 adapter 遵循專案基本規範第 3 條「抓取失敗一律 raise，絕不可回傳空資料」，
失敗時仍會 raise（不吞掉錯誤、不回傳空清單）。
但依規格書 3-C 節建議，**這個來源不應該用一般來源的「連續失敗觸發 ALERT.md」
判準**，因為它幾乎每天都有相當機率觸發失敗，且 9 月後將恆定 100% 失敗。
這需要在下游 healthcheck.py 的例外名單中把 KEY 加入「已知不穩定來源」清單，
使其失敗不觸發 /fail 死人開關 ping；**此為驅動程式/healthcheck.py 層級的變更，
不在本檔案（adapter 本體）範圍內，需在實作階段另外處理，本檔案僅在此註記**。
"""
import json
import time

KEY = "mcp_pulsemcp"
DESC = "PulseMCP MCP 伺服器清冊（官方已排程於 2026-09 完全停用 v0beta API，屬已知不穩定來源）"
SOURCE_HOME = "https://api.pulsemcp.com/v0beta/servers"
ROBOTS_VERIFIED = (
    "2026-08-28 親驗 https://api.pulsemcp.com/robots.txt：Content-Signal 格式，"
    "User-agent: * 未見路徑 Disallow"
)
PARSER_VERSION = 1

URL = "https://api.pulsemcp.com/v0beta/servers"


def collect(fetch) -> dict:
    """回傳 dict：{"servers": [...], "total": N}。

    若本次呼叫剛好命中官方排程的隨機失敗（如 410 API_SUNSET），一律 raise，
    交由上游 manifest 記錄 ok:false／status，不在 adapter 內部偽造空資料。
    """
    raw = fetch(URL)
    time.sleep(1)
    j = json.loads(raw)

    if isinstance(j, dict) and "servers" in j:
        servers = j.get("servers") or []
    elif isinstance(j, list):
        servers = j
    else:
        raise RuntimeError(
            "mcp_pulsemcp：非預期的回應結構（既非 {servers:[...]} 也非陣列）：%r"
            % (list(j.keys()) if isinstance(j, dict) else type(j))
        )

    if not servers:
        raise RuntimeError("mcp_pulsemcp：解析成功但清單為 0 筆，視為異常，不寫入快照")

    return {"servers": servers, "total": len(servers)}
