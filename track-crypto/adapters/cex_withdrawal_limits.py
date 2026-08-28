# -*- coding: utf-8 -*-
"""cex_withdrawal_limits：交易所提幣費／最低提幣額快照 adapter（KuCoin v3/currencies）。

對應規格：/Users/monica/Documents/temp/終端機/vps-161.97.82.83/adapters-wip/specs/batch1.md 1-C（A9）
Binance / OKX 的對應資料需要 API 金鑰，本輪不申請（沿用父代理裁示，見規格文件）。
"""
import json

KEY = "cex_withdrawal_limits"
DESC = "KuCoin 幣種提幣費與最低提幣額（含各鏈參數）"
SOURCE_HOME = "https://api.kucoin.com/api/v3/currencies"
ROBOTS_VERIFIED = "2026-08-28 親驗 https://api.kucoin.com/robots.txt：404（無 robots.txt，視為無限制）"
PARSER_VERSION = 1

KUCOIN_URL = "https://api.kucoin.com/api/v3/currencies"

MIN_ITEMS = 1500


def collect(fetch):
    """回傳 list[dict]，每筆為 KuCoin 原始幣種資料（含 chains 陣列）。"""
    raw = fetch(KUCOIN_URL)
    data = json.loads(raw)
    if isinstance(data, dict) and "data" in data:
        # KuCoin 標準回應包裝格式：{"code": "200000", "data": [...]}
        code = data.get("code")
        if code not in (None, "200000"):
            raise RuntimeError("cex_withdrawal_limits(kucoin)：API 回傳非成功碼 code=%r" % (code,))
        items = data["data"]
    else:
        items = data
    if not isinstance(items, list) or not items:
        raise RuntimeError("cex_withdrawal_limits(kucoin)：回傳非陣列或為空")
    if len(items) < MIN_ITEMS:
        raise RuntimeError("cex_withdrawal_limits(kucoin)：筆數 %d 低於下限 %d" % (len(items), MIN_ITEMS))
    seen = set()
    for row in items:
        if "currency" not in row or "chains" not in row:
            raise RuntimeError("cex_withdrawal_limits(kucoin)：某筆缺少 currency 或 chains 欄位")
        if row["currency"] in seen:
            raise RuntimeError("cex_withdrawal_limits(kucoin)：currency 重複 %r" % row["currency"])
        seen.add(row["currency"])
    return items
