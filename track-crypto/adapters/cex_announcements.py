# -*- coding: utf-8 -*-
"""cex_announcements：交易所公告（新幣上架等）快照 adapter（Binance／Bybit／OKX／Upbit）。

對應規格：/Users/monica/Documents/temp/終端機/vps-161.97.82.83/adapters-wip/specs/batch1.md 1-D（A8）

規格要求：四家至少 3 家成功才視為本次抓取成功；Upbit 因本輪撞到 429、結構未知，允許暫時性失敗，
但需在 errors 欄位誠實記錄。
只存「標題＋URL＋時間＋分類＋內文 SHA256」，不落地存公告全文（著作權考量，規格已明文要求）。
"""
import hashlib
import json
import time

KEY = "cex_announcements"
DESC = "交易所公告（新幣上架等分類），僅存標題/URL/時間/分類，不存全文"
SOURCE_HOME = (
    "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query ; "
    "https://api.bybit.com/v5/announcements/index ; "
    "https://www.okx.com/api/v5/support/announcements ; "
    "https://api-manager.upbit.com/api/v1/announcements"
)
ROBOTS_VERIFIED = (
    "2026-08-28 沿用規格書實測結論：www.binance.com 此 API 路徑本輪未被 WAF 攔截（但主機同時存在會被 WAF 擋的頁面，"
    "每次改版須重新確認）；api.bybit.com、www.okx.com 本輪正常回應；api-manager.upbit.com 本輪撞到 HTTP 429，"
    "限流比 api.upbit.com 更嚴格，未親驗 robots.txt 內容（見已知的坑）"
)
PARSER_VERSION = 1

BINANCE_URL = (
    "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
    "?type=1&catalogId=48&pageNo=1&pageSize=20"
)
BYBIT_URL = "https://api.bybit.com/v5/announcements/index?locale=en-US"
OKX_URL = "https://www.okx.com/api/v5/support/announcements"
UPBIT_URL = "https://api-manager.upbit.com/api/v1/announcements?os=web&page=1&per_page=20"

MIN_SUCCESS = 3
TOTAL_SOURCES = 4
# Upbit 主機對高頻請求特別敏感（規格書已實測撞到 429），本 adapter 對它使用更保守的間隔
UPBIT_SLEEP = 3


def _sha256(text):
    return hashlib.sha256((text or "").encode("utf-8", "ignore")).hexdigest()


def _collect_binance(fetch):
    raw = fetch(BINANCE_URL)
    data = json.loads(raw)
    catalogs = (data.get("data") or {}).get("catalogs") or []
    items = []
    seen = set()
    for cat in catalogs:
        for art in cat.get("articles") or []:
            aid = art.get("id")
            if aid is None or aid in seen:
                continue
            seen.add(aid)
            items.append({
                "id": aid,
                "code": art.get("code"),
                "title": art.get("title"),
                "type": art.get("type"),
                "release_date": art.get("releaseDate"),
                "url": "https://www.binance.com/en/support/announcement/%s" % (art.get("code") or aid),
                "body_sha256": _sha256(art.get("title")),
            })
    if not items:
        raise RuntimeError("cex_announcements(binance)：清單為空，版型可能已改")
    return items


def _collect_bybit(fetch):
    raw = fetch(BYBIT_URL)
    data = json.loads(raw)
    rows = ((data.get("result") or {}).get("list")) or []
    items = []
    seen = set()
    for row in rows:
        url = row.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        type_info = row.get("type") or {}
        items.append({
            "title": row.get("title"),
            "url": url,
            "type_key": type_info.get("key"),
            "type_title": type_info.get("title"),
            "tags": row.get("tags"),
            "publish_time": row.get("publishTime") or row.get("dateTimestamp"),
            "body_sha256": _sha256(row.get("description") or row.get("title")),
        })
    if not items:
        raise RuntimeError("cex_announcements(bybit)：清單為空，版型可能已改")
    return items


def _collect_okx(fetch):
    raw = fetch(OKX_URL)
    data = json.loads(raw)
    blocks = data.get("data") or []
    items = []
    seen = set()
    for block in blocks:
        for row in block.get("details") or []:
            url = row.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            items.append({
                "title": row.get("title"),
                "url": url,
                "ann_type": row.get("annType"),
                "p_time": row.get("pTime"),
                "business_p_time": row.get("businessPTime"),
                "body_sha256": _sha256(row.get("title")),
            })
    if not items:
        raise RuntimeError("cex_announcements(okx)：清單為空，版型可能已改")
    return items


def _collect_upbit(fetch):
    raw = fetch(UPBIT_URL)
    data = json.loads(raw)
    # 結構未經本輪實測驗證（規格書撞到 429），採寬鬆解析：優先找常見鍵名，找不到就整包回傳交由下游人工檢視
    rows = None
    if isinstance(data, dict):
        for key in ("notices", "data", "list", "result"):
            val = data.get(key)
            if isinstance(val, list):
                rows = val
                break
            if isinstance(val, dict) and isinstance(val.get("notices"), list):
                rows = val["notices"]
                break
    elif isinstance(data, list):
        rows = data
    if not rows:
        raise RuntimeError("cex_announcements(upbit)：無法從回應解析出清單，結構未知或本次仍被限流")
    items = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = row.get("title") or row.get("name")
        url = row.get("url") or row.get("id")
        items.append({
            "raw_keys": sorted(row.keys()),
            "title": title,
            "url": url,
            "body_sha256": _sha256(json.dumps(row, ensure_ascii=False, sort_keys=True)),
        })
    if not items:
        raise RuntimeError("cex_announcements(upbit)：解析出的清單為空")
    return items


def collect(fetch):
    """回傳 dict：{"binance": [...], "bybit": [...], "okx": [...], "upbit": [...]（可能缺席）,
    "errors": {來源: 錯誤訊息}}
    四家至少 3 家成功才算整體成功，否則 raise；失敗的來源記錄在 errors，不讓下游誤判為空資料。
    """
    result = {}
    errors = {}

    try:
        result["binance"] = _collect_binance(fetch)
    except Exception as exc:  # noqa: BLE001 - 個別來源失敗需被容忍並記錄
        errors["binance"] = str(exc)
    time.sleep(1)

    try:
        result["bybit"] = _collect_bybit(fetch)
    except Exception as exc:  # noqa: BLE001
        errors["bybit"] = str(exc)
    time.sleep(1)

    try:
        result["okx"] = _collect_okx(fetch)
    except Exception as exc:  # noqa: BLE001
        errors["okx"] = str(exc)
    time.sleep(1)

    try:
        time.sleep(UPBIT_SLEEP)
        result["upbit"] = _collect_upbit(fetch)
    except Exception as exc:  # noqa: BLE001
        errors["upbit"] = str(exc)

    if len(result) < MIN_SUCCESS:
        raise RuntimeError(
            "cex_announcements：成功來源數 %d 低於下限 %d（共 %d 家），errors=%r"
            % (len(result), MIN_SUCCESS, TOTAL_SOURCES, errors)
        )

    result["errors"] = errors
    return result
