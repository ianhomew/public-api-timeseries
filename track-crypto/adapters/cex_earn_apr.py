# -*- coding: utf-8 -*-
"""cex_earn_apr：CEX 理財年化率快照 adapter（Bybit 活期理財／OKX 借貸利率總覽）。

對應規格：/Users/monica/Documents/temp/終端機/vps-161.97.82.83/adapters-wip/specs/batch2.md 2-A（A12）
"""
import json
import time

KEY = "cex_earn_apr"
DESC = "CEX 理財年化率（Bybit 活期理財 FlexibleSaving／OKX 借貸利率總覽）"
SOURCE_HOME = (
    "https://api.bybit.com/v5/earn/product?category=FlexibleSaving ; "
    "https://www.okx.com/api/v5/finance/savings/lending-rate-summary"
)
ROBOTS_VERIFIED = (
    "2026-08-28 沿用規格書重驗結論：api.bybit.com、www.okx.com 本輪皆正常回應 200，"
    "規格書已列出實測筆數（Bybit 229 筆／OKX 169 筆），本 adapter 實作時另行親驗 robots.txt。"
)
PARSER_VERSION = 1

BYBIT_URL = "https://api.bybit.com/v5/earn/product?category=FlexibleSaving"
OKX_URL = "https://www.okx.com/api/v5/finance/savings/lending-rate-summary"

MIN_BYBIT = 100
MIN_OKX = 50


def _parse(raw):
    """相容兩種驅動慣例：fetch() 回傳已解析 JSON，或回傳原始字串。"""
    if isinstance(raw, (dict, list)):
        return raw
    return json.loads(raw)


def _collect_bybit(fetch):
    raw = fetch(BYBIT_URL)
    data = _parse(raw)
    if not isinstance(data, dict) or data.get("retCode") != 0:
        raise RuntimeError("cex_earn_apr(bybit)：API 非成功回應 retCode=%r" % (data.get("retCode") if isinstance(data, dict) else None,))
    result = data.get("result") or {}
    items = result.get("list")
    if not isinstance(items, list) or not items:
        raise RuntimeError("cex_earn_apr(bybit)：list 為空或格式不對")
    if len(items) < MIN_BYBIT:
        raise RuntimeError("cex_earn_apr(bybit)：筆數 %d 低於下限 %d" % (len(items), MIN_BYBIT))
    seen = set()
    for row in items:
        if "coin" not in row or "estimateApr" not in row:
            raise RuntimeError("cex_earn_apr(bybit)：某筆缺少 coin 或 estimateApr 欄位：%r" % (row,))
        pid = row.get("productId") or (row.get("coin"), row.get("aprPeriod"))
        if pid in seen:
            raise RuntimeError("cex_earn_apr(bybit)：productId 重複 %r" % (pid,))
        seen.add(pid)
    return items


def _collect_okx(fetch):
    raw = fetch(OKX_URL)
    data = _parse(raw)
    if not isinstance(data, dict) or data.get("code") != "0":
        raise RuntimeError("cex_earn_apr(okx)：API 非成功回應 code=%r" % (data.get("code") if isinstance(data, dict) else None,))
    items = data.get("data")
    if not isinstance(items, list) or not items:
        raise RuntimeError("cex_earn_apr(okx)：data 為空或格式不對")
    if len(items) < MIN_OKX:
        raise RuntimeError("cex_earn_apr(okx)：筆數 %d 低於下限 %d" % (len(items), MIN_OKX))
    seen = set()
    for row in items:
        if not isinstance(row, dict) or "ccy" not in row:
            raise RuntimeError("cex_earn_apr(okx)：某筆缺少 ccy 欄位：%r" % (row,))
        if row["ccy"] in seen:
            raise RuntimeError("cex_earn_apr(okx)：ccy 重複 %r" % (row["ccy"],))
        seen.add(row["ccy"])
    return items


def collect(fetch) -> dict:
    """回傳 {"bybit": [...], "okx": [...]}，兩者皆為必要來源（規格未列允許部分失敗）。"""
    bybit = _collect_bybit(fetch)
    time.sleep(1)
    okx = _collect_okx(fetch)
    return {"bybit": bybit, "okx": okx}
