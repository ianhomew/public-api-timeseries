# -*- coding: utf-8 -*-
"""擴充 cex_symbols：新增 Kraken／Coinbase Exchange／Upbit 三家交易所的交易對清單快照 adapter。

對應規格：/Users/monica/Documents/temp/終端機/vps-161.97.82.83/adapters-wip/specs/batch1.md 1-A（A6）
"""
import json
import time

KEY = "cex_symbols_ext"
DESC = "新增 3 家交易所（Kraken／Coinbase Exchange／Upbit）交易對清單，擴充既有 cex_symbols"
SOURCE_HOME = "https://api.kraken.com/0/public/AssetPairs ; https://api.exchange.coinbase.com/products ; https://api.upbit.com/v1/market/all"
ROBOTS_VERIFIED = (
    "2026-08-28 親驗：Kraken api.kraken.com/robots.txt 無限制；"
    "Coinbase Exchange api.exchange.coinbase.com/robots.txt 回 401 Unauthorized（不尋常，"
    "但資料端點 /products 本身本輪實測不需認證、正常回 200，每次改版建議重新確認）；"
    "Upbit api.upbit.com/robots.txt 未見 Disallow（該站另一子網域 api-manager.upbit.com 對高頻請求會回 429，"
    "已於本 adapter 對 Upbit 使用較保守的 sleep）"
)
PARSER_VERSION = 1

KRAKEN_URL = "https://api.kraken.com/0/public/AssetPairs"
COINBASE_URL = "https://api.exchange.coinbase.com/products"
UPBIT_URL = "https://api.upbit.com/v1/market/all"

MIN_KRAKEN = 1000
MIN_COINBASE = 500
MIN_UPBIT = 500


def _collect_kraken(fetch):
    raw = fetch(KRAKEN_URL)
    data = json.loads(raw)
    if data.get("error"):
        raise RuntimeError("cex_symbols_ext(kraken)：API 回傳 error：%r" % (data["error"],))
    result = data.get("result")
    if not isinstance(result, dict) or not result:
        raise RuntimeError("cex_symbols_ext(kraken)：result 為空或格式不對")
    if len(result) < MIN_KRAKEN:
        raise RuntimeError("cex_symbols_ext(kraken)：筆數 %d 低於下限 %d" % (len(result), MIN_KRAKEN))
    for code, row in result.items():
        if "status" not in row:
            raise RuntimeError("cex_symbols_ext(kraken)：交易對 %s 缺少 status 欄位" % code)
    # dict key 天然唯一，不需額外去重檢查
    return result


def _collect_coinbase(fetch):
    raw = fetch(COINBASE_URL)
    data = json.loads(raw)
    if not isinstance(data, list) or not data:
        raise RuntimeError("cex_symbols_ext(coinbase)：回傳非陣列或為空")
    if len(data) < MIN_COINBASE:
        raise RuntimeError("cex_symbols_ext(coinbase)：筆數 %d 低於下限 %d" % (len(data), MIN_COINBASE))
    seen = set()
    for row in data:
        if "id" not in row or "status" not in row:
            raise RuntimeError("cex_symbols_ext(coinbase)：某筆缺少 id 或 status 欄位")
        if row["id"] in seen:
            raise RuntimeError("cex_symbols_ext(coinbase)：id 重複 %r" % row["id"])
        seen.add(row["id"])
    return data


def _collect_upbit(fetch):
    raw = fetch(UPBIT_URL)
    data = json.loads(raw)
    if not isinstance(data, list) or not data:
        raise RuntimeError("cex_symbols_ext(upbit)：回傳非陣列或為空")
    if len(data) < MIN_UPBIT:
        raise RuntimeError("cex_symbols_ext(upbit)：筆數 %d 低於下限 %d" % (len(data), MIN_UPBIT))
    seen = set()
    for row in data:
        if "market" not in row:
            raise RuntimeError("cex_symbols_ext(upbit)：某筆缺少 market 欄位")
        if row["market"] in seen:
            raise RuntimeError("cex_symbols_ext(upbit)：market 重複 %r" % row["market"])
        seen.add(row["market"])
    return data


def collect(fetch):
    """回傳 dict：{"kraken": {...}, "coinbase": [...], "upbit": [...]}
    三家皆為必要來源（規格未列允許部分失敗），任一失敗即整體 raise。
    """
    kraken = _collect_kraken(fetch)
    time.sleep(1)
    coinbase = _collect_coinbase(fetch)
    time.sleep(1)
    # Upbit 對高頻請求較敏感，採更保守間隔（規格建議 2-3 秒，此處已在上一次 sleep(1) 之後再補 1.5 秒）
    time.sleep(1.5)
    upbit = _collect_upbit(fetch)
    return {
        "kraken": kraken,
        "coinbase": coinbase,
        "upbit": upbit,
    }
