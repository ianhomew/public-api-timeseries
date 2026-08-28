# -*- coding: utf-8 -*-
"""eth_validator_queue：以太坊驗證者進出隊列（各 status 筆數）快照 adapter。

對應規格：/Users/monica/Documents/temp/終端機/vps-161.97.82.83/adapters-wip/specs/batch2.md 2-C（A16）

已知的坑（規格書明文要求，實作時遵守）：
    候選文件的原意只是要「隊列人數與等待天數」這種數字，不是要存整個 validator 清單。
    本輪實測 `exited_unslashed` 一個 status 就有 655,100 bytes（1,424 筆完整 validator 物件，
    每筆含公鑰十六進位字串等），4 個 status 若都存整包，一天可能超過 1MB，且絕大部分是
    不會再變動的歷史驗證者公鑰。**本 adapter 只存每個 status 的筆數（len(data)），
    不存個別 validator 的公鑰/餘額**，把每日資料量壓到幾乎可忽略。
    publicnode.com 是共用的公開節點服務，沒有 SLA，timeout 設 30 秒，單一 status 失敗
    不視為致命錯誤（規格允許 4 個 status 至少 3 個成功即可）。
"""
import json
import time

KEY = "eth_validator_queue"
DESC = "以太坊驗證者進出隊列各狀態筆數（pending_queued／pending_initialized／active_exiting／exited_unslashed），僅存計數不存個別公鑰"
SOURCE_HOME = "https://ethereum-beacon-api.publicnode.com/eth/v1/beacon/states/head/validators?status={status}"
ROBOTS_VERIFIED = (
    "2026-08-28 沿用規格書重驗結論：ethereum-beacon-api.publicnode.com 本輪 4 個 status 皆正常回應 200，"
    "本 adapter 實作時另行親驗 robots.txt。"
)
PARSER_VERSION = 1

BASE_URL = "https://ethereum-beacon-api.publicnode.com/eth/v1/beacon/states/head/validators?status={}"
STATUSES = ["pending_queued", "pending_initialized", "active_exiting", "exited_unslashed"]

MIN_SUCCESS = 3
TOTAL_SOURCES = len(STATUSES)
# 單日暴增/暴減超過此倍率應視為異常（供下游告警參考，本 adapter 只記錄數值不主動比對歷史）
ANOMALY_RATIO = 10


def _parse(raw):
    if isinstance(raw, (dict, list)):
        return raw
    return json.loads(raw)


def collect(fetch) -> dict:
    """回傳 {"counts": {"<status>": <int>}, "_errors": {"<status>": "<原因>"}（若有失敗）}。
    只存每個 status 的驗證者筆數，不存個別 validator 物件（見模組說明的坑）。
    """
    counts = {}
    errors = {}
    for i, status in enumerate(STATUSES):
        if i > 0:
            time.sleep(1)
        url = BASE_URL.format(status)
        try:
            data = _parse(fetch(url))
            arr = data.get("data") if isinstance(data, dict) else None
            if not isinstance(arr, list):
                raise RuntimeError("回傳 data 欄位非陣列：%r" % (type(arr),))
            n = len(arr)
            if n < 0:
                raise RuntimeError("筆數為負，不合理：%r" % (n,))
            counts[status] = n
        except Exception as e:
            errors[status] = repr(e)

    ok_count = TOTAL_SOURCES - len(errors)
    if ok_count < MIN_SUCCESS:
        raise RuntimeError(
            "eth_validator_queue：僅 %d/%d 個 status 成功，低於下限 %d，視為整體失敗，errors=%r"
            % (ok_count, TOTAL_SOURCES, MIN_SUCCESS, errors)
        )
    out = {"counts": counts}
    if errors:
        out["_errors"] = errors
    return out
