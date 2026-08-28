# -*- coding: utf-8 -*-
"""cex_currency_status：交易所幣種層級的狀態旗標快照 adapter（Gate／Coinbase Exchange）。

HTX（火幣）不需新請求：既有 cex_symbols 的 v1/common/symbols 已含 state 欄位，沿用既有資料，
本 adapter 不重複抓取，僅在報告中註記。

對應規格：/Users/monica/Documents/temp/終端機/vps-161.97.82.83/adapters-wip/specs/batch1.md 1-B（A7）
"""
import json
import time

KEY = "cex_currency_status"
DESC = "交易所幣種層級狀態旗標（Gate delisted／Coinbase status），HTX 沿用既有 cex_symbols 欄位"
SOURCE_HOME = "https://api.gateio.ws/api/v4/spot/currencies ; https://api.exchange.coinbase.com/currencies"
ROBOTS_VERIFIED = (
    "2026-08-28 親驗：Gate api.gateio.ws/robots.txt 未見 Disallow；"
    "Coinbase Exchange api.exchange.coinbase.com/robots.txt 回 401 Unauthorized（與 A6 相同的不尋常行為，"
    "但 /currencies 資料端點本輪實測不需認證、正常回 200）"
)
PARSER_VERSION = 1

GATE_URL = "https://api.gateio.ws/api/v4/spot/currencies"
COINBASE_URL = "https://api.exchange.coinbase.com/currencies"

MIN_GATE = 3000
MIN_COINBASE = 300

# Gate 這個端點實測回應偏慢（5-6 秒），fetch() 的 timeout 需由呼叫端設較寬（建議 30-45 秒）


def _collect_gate(fetch):
    raw = fetch(GATE_URL)
    data = json.loads(raw)
    if not isinstance(data, list) or not data:
        raise RuntimeError("cex_currency_status(gate)：回傳非陣列或為空")
    if len(data) < MIN_GATE:
        raise RuntimeError("cex_currency_status(gate)：筆數 %d 低於下限 %d" % (len(data), MIN_GATE))
    seen = set()
    for row in data:
        if "currency" not in row or "delisted" not in row:
            raise RuntimeError("cex_currency_status(gate)：某筆缺少 currency 或 delisted 欄位")
        if row["currency"] in seen:
            raise RuntimeError("cex_currency_status(gate)：currency 重複 %r" % row["currency"])
        seen.add(row["currency"])
    return data


def _collect_coinbase(fetch):
    raw = fetch(COINBASE_URL)
    data = json.loads(raw)
    if not isinstance(data, list) or not data:
        raise RuntimeError("cex_currency_status(coinbase)：回傳非陣列或為空")
    if len(data) < MIN_COINBASE:
        raise RuntimeError("cex_currency_status(coinbase)：筆數 %d 低於下限 %d" % (len(data), MIN_COINBASE))
    seen = set()
    for row in data:
        if "id" not in row or "status" not in row:
            raise RuntimeError("cex_currency_status(coinbase)：某筆缺少 id 或 status 欄位")
        if row["id"] in seen:
            raise RuntimeError("cex_currency_status(coinbase)：id 重複 %r" % row["id"])
        seen.add(row["id"])
    return data


def collect(fetch):
    """回傳 dict：{"gate": [...], "coinbase": [...]}
    HTX 不在此 adapter 內處理（沿用既有 cex_symbols 欄位，見 DESC 說明）。
    """
    gate = _collect_gate(fetch)
    time.sleep(1)
    coinbase = _collect_coinbase(fetch)
    return {
        "gate": gate,
        "coinbase": coinbase,
    }
