# -*- coding: utf-8 -*-
"""defi_yield_rates：LST/LRT 質押與 DeFi 借貸利率快照 adapter
（Lido stETH／Rocket Pool rETH／Ethena sUSDe／Sky 整體指標，合併四個小端點）。

對應規格：/Users/monica/Documents/temp/終端機/vps-161.97.82.83/adapters-wip/specs/batch2.md 2-B（A13＋A14）

已知的坑（規格書已標明，實作時沿用）：
1. 四個來源合計四種完全不同的 JSON 形狀，不強行統一欄位名稱，各自一個子 key 存放原始回應。
2. Sky 的回應是「陣列包多個小 dict」而非單一大 dict，第一個元素才是主要指標，其餘元素是個別幣價，
   同一次查詢裡的不同維度，不是逐日累積的歷史記錄，原樣整包存放即可，不逐一拆解。
3. A14（Sky）本身低獨佔性但成本趨近於零（本輪實測 1,084 bytes），仍列入本批。
"""
import json
import time

KEY = "defi_yield_rates"
DESC = "LST/LRT 質押與 DeFi 借貸利率（Lido／Rocket Pool／Ethena／Sky，四個原始回應各自一個子 key）"
SOURCE_HOME = (
    "https://eth-api.lido.fi/v1/protocol/steth/apr/last ; "
    "https://api.rocketpool.net/api/mainnet/payload ; "
    "https://app.ethena.fi/api/yields/protocol-and-staking-yield ; "
    "https://info-sky.blockanalitica.com/api/v1/overall/"
)
ROBOTS_VERIFIED = (
    "2026-08-28 沿用規格書重驗結論：四個端點本輪皆正常回應 200"
    "（Lido 137B／Rocket Pool 1,379B／Ethena 448B／Sky 1,084B），本 adapter 實作時另行親驗 robots.txt。"
)
PARSER_VERSION = 1

LIDO_URL = "https://eth-api.lido.fi/v1/protocol/steth/apr/last"
ROCKETPOOL_URL = "https://api.rocketpool.net/api/mainnet/payload"
ETHENA_URL = "https://app.ethena.fi/api/yields/protocol-and-staking-yield"
SKY_URL = "https://info-sky.blockanalitica.com/api/v1/overall/"

# 規格：四者合計至少 3 個成功視為本次抓取成功
MIN_SUCCESS = 3
TOTAL_SOURCES = 4


def _parse(raw):
    if isinstance(raw, (dict, list)):
        return raw
    return json.loads(raw)


def _collect_lido(fetch):
    data = _parse(fetch(LIDO_URL))
    if not isinstance(data, dict) or "data" not in data or "apr" not in (data.get("data") or {}):
        raise RuntimeError("defi_yield_rates(lido)：缺少 data.apr 欄位：%r" % (data,))
    return data


def _collect_rocketpool(fetch):
    data = _parse(fetch(ROCKETPOOL_URL))
    if not isinstance(data, dict) or "rethAPR" not in data or "stats" not in data:
        raise RuntimeError("defi_yield_rates(rocketpool)：缺少 rethAPR 或 stats 欄位：%r" % (data,))
    return data


def _collect_ethena(fetch):
    data = _parse(fetch(ETHENA_URL))
    if not isinstance(data, dict) or "avg30dSusdeYield" not in data:
        raise RuntimeError("defi_yield_rates(ethena)：缺少 avg30dSusdeYield 欄位：%r" % (data,))
    return data


def _collect_sky(fetch):
    data = _parse(fetch(SKY_URL))
    if not isinstance(data, list) or not data:
        raise RuntimeError("defi_yield_rates(sky)：回傳非陣列或為空：%r" % (data,))
    first = data[0]
    if not isinstance(first, dict) or "sky_savings_rate_apy" not in first:
        raise RuntimeError("defi_yield_rates(sky)：第一個元素缺少 sky_savings_rate_apy 欄位：%r" % (first,))
    return data


def collect(fetch) -> dict:
    """回傳 {"lido": {...}, "rocketpool": {...}, "ethena": {...}, "sky": [...],
    "_errors": {"<name>": "<原因>"}（若有失敗）}。
    四者合計至少 MIN_SUCCESS 個成功才視為整體成功，否則 raise。
    """
    fns = [
        ("lido", _collect_lido),
        ("rocketpool", _collect_rocketpool),
        ("ethena", _collect_ethena),
        ("sky", _collect_sky),
    ]
    out = {}
    errors = {}
    for i, (name, fn) in enumerate(fns):
        if i > 0:
            time.sleep(1)
        try:
            out[name] = fn(fetch)
        except Exception as e:
            errors[name] = repr(e)

    ok_count = TOTAL_SOURCES - len(errors)
    if ok_count < MIN_SUCCESS:
        raise RuntimeError(
            "defi_yield_rates：僅 %d/%d 個來源成功，低於下限 %d，視為整體失敗，errors=%r"
            % (ok_count, TOTAL_SOURCES, MIN_SUCCESS, errors)
        )
    if errors:
        out["_errors"] = errors
    return out
