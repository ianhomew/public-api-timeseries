# -*- coding: utf-8 -*-
"""oracle_feed_directory：Chainlink／Pyth 價格餵送目錄快照 adapter。

對應規格：/Users/monica/Documents/temp/終端機/vps-161.97.82.83/adapters-wip/specs/batch2.md 2-D（A18）

已知的坑（規格書明文提及，實作時遵守）：
1. Chainlink 端點托管在 vercel.app（第三方共用部署平台，非 chain.link 官方網域），
   比自架網域更脆弱，理論上有整個 Vercel 專案被下架或搬遷的風險。
2. 兩者都是「目錄」性質，逐日比對集合差集（contractAddress／id）才能判斷哪個餵送被下架，
   這件事由下游負責，本 adapter 只負責忠實存下每日快照。
"""
import json
import time

KEY = "oracle_feed_directory"
DESC = "Chainlink／Pyth 價格餵送目錄（目前存在哪些餵送，供下游逐日比對集合差集）"
SOURCE_HOME = (
    "https://reference-data-directory.vercel.app/feeds-mainnet.json ; "
    "https://hermes.pyth.network/v2/price_feeds"
)
ROBOTS_VERIFIED = (
    "2026-08-28 沿用規格書重驗結論：兩個托管網域的 robots.txt 皆為 404（視為無限制），"
    "本輪皆正常回應 200（Chainlink 292 筆／Pyth 1,843 筆），本 adapter 實作時另行親驗 robots.txt。"
)
PARSER_VERSION = 1

CHAINLINK_URL = "https://reference-data-directory.vercel.app/feeds-mainnet.json"
PYTH_URL = "https://hermes.pyth.network/v2/price_feeds"

MIN_CHAINLINK = 100
MIN_PYTH = 500


def _parse(raw):
    if isinstance(raw, (dict, list)):
        return raw
    return json.loads(raw)


def _collect_chainlink(fetch):
    data = _parse(fetch(CHAINLINK_URL))
    if not isinstance(data, list) or not data:
        raise RuntimeError("oracle_feed_directory(chainlink)：回傳非陣列或為空")
    if len(data) < MIN_CHAINLINK:
        raise RuntimeError("oracle_feed_directory(chainlink)：筆數 %d 低於下限 %d" % (len(data), MIN_CHAINLINK))
    seen = set()
    for row in data:
        if not isinstance(row, dict) or "contractAddress" not in row:
            raise RuntimeError("oracle_feed_directory(chainlink)：某筆缺少 contractAddress 欄位：%r" % (row,))
        addr = row["contractAddress"]
        if addr in seen:
            raise RuntimeError("oracle_feed_directory(chainlink)：contractAddress 重複 %r" % (addr,))
        seen.add(addr)
    return data


def _collect_pyth(fetch):
    data = _parse(fetch(PYTH_URL))
    if not isinstance(data, list) or not data:
        raise RuntimeError("oracle_feed_directory(pyth)：回傳非陣列或為空")
    if len(data) < MIN_PYTH:
        raise RuntimeError("oracle_feed_directory(pyth)：筆數 %d 低於下限 %d" % (len(data), MIN_PYTH))
    seen = set()
    for row in data:
        if not isinstance(row, dict) or "id" not in row:
            raise RuntimeError("oracle_feed_directory(pyth)：某筆缺少 id 欄位：%r" % (row,))
        if row["id"] in seen:
            raise RuntimeError("oracle_feed_directory(pyth)：id 重複 %r" % (row["id"],))
        seen.add(row["id"])
    return data


def collect(fetch) -> dict:
    """回傳 {"chainlink": [...], "pyth": [...]}，兩者皆為必要來源（規格未列允許部分失敗）。"""
    chainlink = _collect_chainlink(fetch)
    time.sleep(1)
    pyth = _collect_pyth(fetch)
    return {"chainlink": chainlink, "pyth": pyth}
