# -*- coding: utf-8 -*-
"""cex_symbols：7 家 CEX 交易對／幣種狀態快照 adapter。

抓取邏輯原樣搬移自既有 track-crypto/scripts/snap_crypto.py 的 src_cex()：
排除 Binance（既有實作記錄：robots 全站 Disallow）；7 家各打 1 次請求；
單一交易所失敗不可讓整個來源失敗，記進 errors 即可（既有行為）。
"""
import json
import time

KEY = "cex_symbols"
DESC = "7 家 CEX 交易對／幣種狀態（Bybit／OKX／Bitget／HTX／Gate／KuCoin／MEXC）"
SOURCE_HOME = (
    "https://api.bybit.com/v5/market/instruments-info?category=spot ; "
    "https://www.okx.com/api/v5/public/instruments?instType=SPOT ; "
    "https://api.bitget.com/api/v2/spot/public/symbols ; "
    "https://api.huobi.pro/v1/common/symbols ; "
    "https://api.gateio.ws/api/v4/spot/currency_pairs ; "
    "https://api.kucoin.com/api/v2/symbols ; "
    "https://api.mexc.com/api/v3/exchangeInfo"
)
ROBOTS_VERIFIED = (
    "2026-08-28 親驗：api.bybit.com/robots.txt HTTP 404（無限制）；"
    "www.okx.com/robots.txt HTTP 200，User-agent: * 的 Disallow 清單未涵蓋 "
    "/api/v5/public/instruments（允許）；api.bitget.com/robots.txt HTTP 403（略過，"
    "沿用既有實作已在抓取的行為，未變更）；api.huobi.pro/robots.txt HTTP 404（無限制）；"
    "api.gateio.ws/robots.txt HTTP 404（無限制）；api.kucoin.com/robots.txt HTTP 404（無限制）；"
    "api.mexc.com/robots.txt HTTP 404（無限制）。Binance 沿用既有實作排除（既有程式碼註記：robots "
    "全站 Disallow），本輪未重新驗證 Binance，維持既有排除決定"
)
PARSER_VERSION = 1

ENDPOINTS = {
    "bybit":  "https://api.bybit.com/v5/market/instruments-info?category=spot",
    "okx":    "https://www.okx.com/api/v5/public/instruments?instType=SPOT",
    "bitget": "https://api.bitget.com/api/v2/spot/public/symbols",
    "htx":    "https://api.huobi.pro/v1/common/symbols",
    "gateio": "https://api.gateio.ws/api/v4/spot/currency_pairs",
    "kucoin": "https://api.kucoin.com/api/v2/symbols",
    "mexc":   "https://api.mexc.com/api/v3/exchangeInfo",
}


def collect(fetch) -> dict:
    """回傳 dict：{"exchanges": {name: <各家原始 JSON>}, "errors": {name: 錯誤訊息}}
    單一交易所失敗不可讓整個來源失敗（既有行為）；7 家全部失敗才 raise。
    """
    out, errs = {}, {}
    for name, u in ENDPOINTS.items():
        try:
            raw = fetch(u)
            out[name] = json.loads(raw)
        except Exception as e:
            errs[name] = "%s: %s" % (type(e).__name__, e)
        time.sleep(1)
    if not out:
        raise RuntimeError("7 家交易所全部失敗: %r" % errs)
    return {"exchanges": out, "errors": errs}
