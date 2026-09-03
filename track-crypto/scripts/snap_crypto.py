#!/usr/bin/env python3
"""軌一 snapshotter v3：加密 / AI 算力市場每日快照（adapter 架構 + 來源層級重試）
只存原始數字，不做任何分析或觀點（投顧法鐵律）
授權：輸出資料 CC BY 4.0

時區鐵律：檔名日期一律 UTC；排程時間為台北時間。兩者不可混用。
每個來源一支 adapter，放在 track-crypto/adapters/<key>.py。

v3 變更（2026-08-31，來源層級重試，見 FIX_TIMING_RETRY_SPEC.md）：
單一來源（單一 adapter 執行）失敗時，等待 120 秒後重試一次（只重試一次）。
manifest 記錄 attempts（1 或 2）與 first_error（第一次失敗訊息，即使第二次成功也保留）。
總時間保護：本輪已執行超過 90 分鐘時，跳過剩餘重試，直接記為失敗，避免拖垮 11:30 的 push 排程。
注意：這是「單一來源」內部的重試，與 fetch() 內既有的「單一 HTTP 請求」重試
（3 次、退避 3/6 秒）是兩個不同層級，互不取代。

adapter 介面（與 track-crypto batch5 已交付的三支一致）：
    KEY = "..."                # 快照子目錄名 / manifest 鍵
    DESC = "..."                # 人類可讀說明（僅用於 manifest／記錄，不落地進快照本體）
    SOURCE_HOME = "..."         # 來源首頁或 API 端點（僅用於記錄）
    ROBOTS_VERIFIED = "..."     # robots.txt 親驗記錄（僅用於記錄）
    PARSER_VERSION = 1          # 解析邏輯版本號，變動時遞增，供 manifest 追蹤
    def collect(fetch) -> dict/list:
        ...                     # fetch(url, headers=None, timeout=45) -> str（原始回應內文，未解析）

🔴 快照本體格式（與軌一今天以前完全相同，不可改動，否則歷史資料無法比較）：
    {"_meta": {"source": "<key>", "fetched_at": "<UTC ISO>", "license": "CC BY 4.0"},
     "data": <collect() 的回傳值>}
注意：_meta 只有這 3 個鍵（軌二的 channels/desc/source_home/robots_verified/parser_version
等擴充欄位一律不進快照本體，只進 manifest，避免破壞既有比對邏輯）。

v4 變更（2026-09-03，manifest 完整性欄位，見 SPEC-manifest-fields.md，只動 manifest 組裝，
不動上面這段快照本體格式、不動 write_gz()）：
manifest 的 sources[key] 新增 n／n_by_path／complete／completeness_check／reported_total／
truncated／dup_keys 七個欄位（只在抓取成功時附加；欄位設計理由與逐來源判定依據見
docs/manifest-fields-report.md）。truncated 語意與軌二 _meta.truncated 完全一致
（一律為布林值，讀不到旗標時預設 False），讓 scripts/healthcheck.py 既有的
check_truncation_streak() 不必修改就能涵蓋軌一。既有 ok/bytes/secs/parser_version/attempts
等欄位完全不受影響。
"""
import json, gzip, os, sys, time, re, hashlib, importlib.util, urllib.request
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
ADPT = os.path.join(BASE, "adapters")
UA = ("snapshotter-research/1.0 (daily archival; public accountability; 1 req/sec; "
      "github.com/ianhomew/public-api-timeseries)")
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
STAMP = datetime.now(timezone.utc).isoformat()

# --- 來源層級重試設定（v3 新增） ---
RETRY_WAIT_SECS = 120       # 單一來源失敗後，重試前等待秒數
MAX_ATTEMPTS = 2            # 最多嘗試次數（1 次原始 + 1 次重試）
MAX_RUN_SECS = 90 * 60      # 本輪總時間保護：超過 90 分鐘不再等待重試
RUN_START = time.time()


def fetch(url, headers=None, timeout=45, retries=3):
    """提供給 adapter 的抓取函式：3 次重試、退避 3/6 秒、可識別 UA，
    支援自訂 headers 與 timeout。回傳未解析的原始回應內文（str），
    JSON 解析交由 adapter 自行處理（各來源回應格式不盡相同）。
    """
    hdr = {"User-Agent": UA, "Accept": "application/json"}
    if headers:
        hdr.update(headers)
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdr)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as e:
            last = e
            if i < retries - 1:
                time.sleep(3 * (i + 1))
    raise last


def load_adapters():
    out = []
    for fn in sorted(os.listdir(ADPT)):
        if not fn.endswith(".py") or fn.startswith("_"):
            continue
        name = fn[:-3]
        spec = importlib.util.spec_from_file_location(name, os.path.join(ADPT, fn))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if not hasattr(mod, "PARSER_VERSION"):
            # 啟動檢查（SPEC-parser-version-disk.md，2026-09-02 新增）：
            # adapter 缺 PARSER_VERSION 時，detect_changes.py 的 parser_version() 讀不到快照
            # _meta.parser_version 就隱性預設為 1；未來若改了解析邏輯卻忘記新增／遞增這個常數，
            # 版本比對保護機制形同虛設，可能把解析器改版誤判為「內容改寫」並自動 commit。
            # 這裡只印警告、不中止載入：忘記宣告的新 adapter 仍會正常運作，只是看不見警告。
            print("WARN %-14s 缺少 PARSER_VERSION 常數（detect_changes.py 讀不到時預設視為 1）："
                  "新增／修改解析邏輯時務必宣告並於改版時遞增，否則版本比對保護機制不會生效"
                  % getattr(mod, "KEY", name), file=sys.stderr, flush=True)
        out.append(mod)
    return out


def write_gz(key, payload):
    """NEVER_OVERWRITE：已存在且內容不同時，另存時戳版本，永不覆蓋歷史。
    原子寫入：先寫 tmp 檔，再 os.replace 換名。
    """
    d = os.path.join(DATA, key)
    os.makedirs(d, exist_ok=True)
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    final = os.path.join(d, TODAY + ".json.gz")
    if os.path.exists(final):
        try:
            with gzip.open(final, "rt", encoding="utf-8") as f:
                old = json.dumps(json.load(f), ensure_ascii=False, separators=(",", ":")).encode()
            if hashlib.sha256(old).hexdigest() == hashlib.sha256(blob).hexdigest():
                return final, os.path.getsize(final)
        except Exception:
            pass
        final = os.path.join(d, TODAY + "T" + datetime.now(timezone.utc).strftime("%H%M%S") + ".json.gz")
    tmp = final + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        f.write(blob.decode())
    os.replace(tmp, final)
    return final, os.path.getsize(final)


def collect_with_retry(mod, key):
    """來源層級重試（v3）：失敗等 120 秒後重試一次；只重試一次。
    回傳 (ok, data_or_None, attempts, first_error_or_None, last_error_or_None, skipped_by_budget)。
    第一次就成功時完全不呼叫 time.sleep，沒有任何額外延遲。"""
    attempts = 0
    first_error = None
    last_error = None
    while True:
        attempts += 1
        try:
            data = mod.collect(fetch)
            return True, data, attempts, first_error, None, False
        except Exception as e:
            err = "%s: %s" % (type(e).__name__, e)
            last_error = err
            if first_error is None:
                first_error = err
            if attempts >= MAX_ATTEMPTS:
                return False, None, attempts, first_error, last_error, False
            elapsed = time.time() - RUN_START
            if elapsed + RETRY_WAIT_SECS > MAX_RUN_SECS:
                # 總時間保護：本輪已跑太久，不再等待重試，直接記為失敗，避免拖垮 11:30 的 push 排程。
                print("SKIP_RETRY %-14s 已執行 %.0f 分鐘，超過 90 分鐘總時間保護，放棄重試：%s"
                      % (key, elapsed / 60, err), file=sys.stderr, flush=True)
                return False, None, attempts, first_error, last_error, True
            print("RETRY %-14s 第 1 次失敗：%s；等待 %d 秒後重試（第 2 次，也是最後一次）"
                  % (key, err, RETRY_WAIT_SECS), flush=True)
            time.sleep(RETRY_WAIT_SECS)


# ============================================================================
# 完整性欄位計算（SPEC-manifest-fields.md，2026-09-03 新增）
# 目的：讓 healthcheck.py 既有的 check_truncation_streak()（讀 sources[key].truncated／.n，
# 不修改該函式）能涵蓋軌一；並為軌一下架偵測第三階段（design doc 2.2）鋪路。
# 語意對齊軌二（track-gov/scripts/snap_gov.py）：truncated 一律是布林值（讀不到旗標時
# 預設 False，比照軌二未宣告 deadline 的舊式 adapter 一律 truncated=False 的既有慣例）。
#
# 設計原則（完整推導與逐來源實測依據見本機 docs/manifest-fields-report.md）：
#   1. 只讀，不改變 collect() 的回傳值、不改變 payload／write_gz() 的任何行為。
#   2. 全部包在呼叫端的 try/except 內：這裡任何例外都只會讓新欄位留空，
#      絕不會把成功的抓取改記為失敗（既有 entry 的 ok/bytes/secs/parser_version/attempts
#      完全不受影響）。
#   3. 既有 adapter 一律不改：n／n_by_path 用有界深度探索自動找出 data 底下的
#      「可比對子集合」（list of dict、或 dict-of-dict 形式的 keyed collection），
#      不必每支 adapter 自己宣告。
#   4. complete／completeness_check 只用機械化規則判定（欄位名是否含 total／是否恰為
#      count／是否有已校準的歷史區間），不摻雜「這是不是滾動視窗」之類的來源語意判斷──
#      那是 detect_delistings.py 白名單／window type 的責任（見 design doc 2.4 閘門 1），
#      manifest 只負責誠實回報機械判定的事實。
# ============================================================================
_EXPLORE_MAX_DEPTH = 4  # dict 才繼續遞迴的深度上限；list／dict-of-dict 都是遞迴終止點。


def _is_dict_of_dict(node):
    """dict 的值至少 3 筆、且其中 >=90% 本身也是 dict，視為『keyed collection』
    （例如 cex_symbols_ext 的 kraken：{交易對代碼: 交易對物件}）。
    停在這一層、不繼續往內鑽，避免鑽進每個 pair 底下 fees/leverage_buy 等巢狀陣列
    （2026-09-02 每日快照變動盤點方法論記憶已記錄過這個陷阱：不設界限會鑽入
    上千個子節點各自展開陣列，這裡用「dict-of-dict 即終止」從結構上避免整類問題）。"""
    if not isinstance(node, dict) or len(node) < 3:
        return False
    vals = list(node.values())
    n_dict = sum(1 for v in vals if isinstance(v, dict))
    return n_dict / len(vals) >= 0.9


def _explore_subsets(data, max_depth=_EXPLORE_MAX_DEPTH):
    """有界深度探索 data 底下所有『可比對子集合』。
    回傳 [(path_tuple, kind, container), ...]，kind 為 "list" 或 "dictofdict"。
    只收「非空且元素為 dict 的 list」或「dict-of-dict」：純量陣列（例如表格表頭字串陣列）
    與空陣列一律不算子集合，避免把非實體資料（如 payment_pricing_pages 的表頭字串陣列、
    cex_symbols 的 mexc.rateLimits/exchangeFilters 空陣列）誤算進 n。"""
    found = []

    def walk(node, path, depth):
        if isinstance(node, list):
            if node and isinstance(node[0], dict):
                found.append((path, "list", node))
            return
        if isinstance(node, dict):
            if _is_dict_of_dict(node):
                found.append((path, "dictofdict", node))
                return
            if depth >= max_depth:
                return
            for k, v in node.items():
                walk(v, path + (k,), depth + 1)

    walk(data, (), 0)
    return found


def _path_get(root, path):
    node = root
    for k in path:
        if not isinstance(node, dict):
            return None
        node = node.get(k)
    return node


# 自報總數欄位優先序：欄位名含 total 但不含 returned／fetched（那類欄位描述『這次呼叫
# 實際拿回多少』，跟 len(items) 幾乎必然相等，拿來自我比對沒有鑑別力，見報告 §2.2
# agent_virtuals 的 total_returned／total_reported 案例）。多個候選同時存在時，
# 依此優先序取第一個命中的欄位名（agent_virtuals→total_reported、
# mcp_smithery→total_count_reported、openrouter_models→total_count 優先於 count）。
_TOTAL_PRIORITY = ("total", "total_count", "total_reported", "reported_total", "total_count_reported")


def _find_reported_total(container):
    """回傳 (欄位名, 判定方式) 或 (None, None)。判定方式只會是 "total_match" 或
    "count_match" 兩者之一（第三、四種可能值 range_check／unknown 由呼叫端
    compute_manifest_fields() 在這裡回傳 (None, None) 時另外決定）。"""
    if not isinstance(container, dict):
        return None, None
    total_candidates = {k: v for k, v in container.items()
                         if isinstance(v, (int, float)) and not isinstance(v, bool)
                         and re.search(r'total', k, re.I)
                         and not re.search(r'returned|fetched', k, re.I)}
    if total_candidates:
        for name in _TOTAL_PRIORITY:
            for k in total_candidates:
                if k.lower() == name:
                    return k, "total_match"
        return sorted(total_candidates)[0], "total_match"
    for k, v in container.items():
        if k.lower() == "count" and isinstance(v, (int, float)) and not isinstance(v, bool):
            return k, "count_match"
    return None, None


def _find_truncated_flag(data):
    """讀 data 層的截斷旗標。優先找同極性的 "truncated"（agent_virtuals、vast_gpu），
    找不到再找反極性的 "is_full"（mcp_smithery：is_full=false 等同 truncated=true）。
    兩者都找不到回傳 (None, None)，呼叫端預設為 False（比照軌二未宣告 deadline 的
    舊式 adapter 一律 truncated=False 的既有慣例）。"""
    if not isinstance(data, dict):
        return None, None
    if isinstance(data.get("truncated"), bool):
        return data["truncated"], "truncated"
    if isinstance(data.get("is_full"), bool):
        return (not data["is_full"]), "is_full(inverted)"
    return None, None


# range_check 校準表：(來源 KEY, 子集合 path tuple) -> (下限, 上限)。
# 前 8 筆沿用 track-crypto/scripts/detect_delistings.py 的 GROUP_SOURCES（2026-09-02，
# 依 2026-08-28~09-02 六天實測 min/max 各加 10% 安全邊界校準，已在該程式實際運作），
# 直接照抄數字以保持兩支程式對同一批來源的判定基準一致，不重新計算。
# cex_symbols／oracle_feed_directory 為本輪新校準（2026-08-26~09-03，最多 9 天實測
# min/max 各加 10%，見 docs/manifest-fields-report.md §2.2 校準紀錄）；這兩個來源
# 目前沒有其他程式做過完整性校準（cex_symbols 的 scripts/cex_events.py 明確沒有任何
# 完整性守門，design doc 2.5 已記錄此缺陷）。
# 區間應隨資料持續累積重新校準，不是最終值（比照 detect_delistings.py 同一份表的既有備註）。
_RANGE_CHECK_TABLE = {
    ("cex_currency_status", ("gate",)): (4938, 6057),
    ("cex_currency_status", ("coinbase",)): (453, 556),
    ("cex_earn_apr", ("bybit",)): (206, 263),
    ("cex_earn_apr", ("okx",)): (151, 185),
    ("cex_symbols_ext", ("coinbase",)): (752, 921),
    ("cex_symbols_ext", ("upbit",)): (762, 934),
    ("cex_symbols_ext", ("kraken",)): (1293, 1585),
    ("cex_withdrawal_limits", ()): (2019, 2470),
    ("cex_symbols", ("exchanges", "bybit", "result", "list")): (486, 604),
    ("cex_symbols", ("exchanges", "okx", "data")): (1242, 1528),
    ("cex_symbols", ("exchanges", "bitget", "data")): (1164, 1437),
    ("cex_symbols", ("exchanges", "htx", "data")): (1943, 2377),
    ("cex_symbols", ("exchanges", "gateio")): (1999, 2472),
    ("cex_symbols", ("exchanges", "kucoin", "data")): (902, 1108),
    ("cex_symbols", ("exchanges", "mexc", "symbols")): (1861, 2336),
    ("oracle_feed_directory", ("chainlink",)): (262, 322),
    ("oracle_feed_directory", ("pyth",)): (1658, 2049),
}

# dup_keys 主鍵欄位對照：(來源 KEY, 子集合 path tuple) -> 欄位名（單一鍵）或欄位名 tuple
# （複合鍵）。前段沿用 detect_delistings.py SOURCES／GROUP_SOURCES 已驗證的 key_field；
# 後段依本輪對 track-crypto/scripts/cex_events.py 的 SPEC 表（cex_symbols 7 家路徑與
# 鍵名）與本輪實測 sample_keys 判定。沒有自然單一鍵的子集合（crypto_project_liveness
# 用複合鍵；project_tokenomics_docs／defi_yield_rates 等無自然鍵者不列入，dup_keys 留 None，
# 不臆測）。
_KEY_FIELD_HINTS = {
    ("x402_bazaar", ("items",)): "resource",
    ("ofac_sanctions_crypto", ("items",)): "uid",
    ("agent_virtuals", ("items",)): "id",
    ("openrouter_models", ("models",)): "id",
    ("openrouter_providers", ("providers",)): "slug",
    ("audit_registry_certik", ("recently_audited",)): "slug",
    ("dao_proposal_snapshot", ("proposals",)): "id",
    ("hf_trending_models", ("models",)): "id",
    ("mcp_smithery", ("servers",)): "id",
    ("vast_gpu", ("offers",)): "id",
    ("payment_protocol_repos", ("repos",)): "id",
    ("cex_currency_status", ("gate",)): "currency",
    ("cex_currency_status", ("coinbase",)): "id",
    ("cex_earn_apr", ("bybit",)): "productId",
    ("cex_earn_apr", ("okx",)): "ccy",
    ("cex_symbols_ext", ("coinbase",)): "id",
    ("cex_symbols_ext", ("upbit",)): "market",
    ("cex_withdrawal_limits", ()): "currency",
    ("oracle_feed_directory", ("pyth",)): "id",
    ("oracle_feed_directory", ("chainlink",)): "name",
    ("cex_symbols", ("exchanges", "bybit", "result", "list")): "symbol",
    ("cex_symbols", ("exchanges", "okx", "data")): "instId",
    ("cex_symbols", ("exchanges", "bitget", "data")): "symbol",
    ("cex_symbols", ("exchanges", "htx", "data")): "symbol",
    ("cex_symbols", ("exchanges", "gateio")): "id",
    ("cex_symbols", ("exchanges", "kucoin", "data")): "symbol",
    ("cex_symbols", ("exchanges", "mexc", "symbols")): "symbol",
    ("cex_announcements", ("binance",)): "id",
    ("cex_announcements", ("bybit",)): "url",
    ("cex_announcements", ("okx",)): "url",
    ("payment_pricing_pages", ("gas_fees_by_source_chain", "rows")): "source_chain",
    ("crypto_project_liveness", ("hacks",)): ("name", "date"),
}


def _compute_dup_keys(items, key_field):
    """key_field 為 None 時回傳 None（不計算，不是 0）；單一欄位或欄位 tuple（複合鍵）皆可。"""
    if key_field is None:
        return None
    try:
        if isinstance(key_field, tuple):
            keys = [tuple(it.get(f) for f in key_field) for it in items if isinstance(it, dict)]
        else:
            keys = [it.get(key_field) for it in items if isinstance(it, dict)]
    except Exception:
        return None
    if len(keys) != len(items):
        return None
    return len(keys) - len(set(keys))


def compute_manifest_fields(key, data):
    """回傳要併入 manifest sources[key] 的新欄位 dict：
    n／n_by_path／complete／completeness_check／reported_total／truncated／dup_keys。
    純讀取 data（collect() 的回傳值，尚未寫入快照的物件），不修改它、不做任何 I/O。"""
    subsets = _explore_subsets(data)

    n_by_path = {}
    complete_by_path = {}
    check_by_path = {}
    dup_by_path = {}

    for path, kind, node in subsets:
        label = ".".join(path) if path else "(root)"
        n_by_path[label] = len(node)
        parent = _path_get(data, path[:-1]) if path else data
        parent = parent if isinstance(parent, dict) else {}

        tf_key, method = _find_reported_total(parent)
        if method:
            reported_total = parent.get(tf_key)
            ok = (reported_total == len(node))
            check_by_path[label] = method
        else:
            rng = _RANGE_CHECK_TABLE.get((key, path))
            if rng:
                lo, hi = rng
                ok = (lo <= len(node) <= hi)
                check_by_path[label] = "range_check"
            else:
                ok = None
                check_by_path[label] = "unknown"

        # errors 兄弟欄位非空 -> 已知有子集合抓取失敗，complete 只能從 True 降級為 False
        # （不會把 None 也降級成 False：我們仍然不知道真正該有多少筆，只是額外確認
        # 「至少有一部分確定沒抓齊」，比照 detect_delistings.py 的 require_empty 機制，
        # 見報告 §2.4 payment_protocol_repos／cex_announcements 的實測依據）。
        errs = parent.get("errors")
        if isinstance(errs, dict) and errs and ok is True:
            ok = False
        complete_by_path[label] = ok

        kf = _KEY_FIELD_HINTS.get((key, path))
        if kind == "list":
            dv = _compute_dup_keys(node, kf)
        else:
            dv = 0  # dict-of-dict：JSON 物件鍵天生唯一，重複數恆為 0
        dup_by_path[label] = dv  # 可能是 None（無主鍵線索，未計算）

    n_total = sum(n_by_path.values()) if n_by_path else None

    truncated, _trunc_src = _find_truncated_flag(data)
    if truncated is None:
        truncated = False  # 讀不到旗標一律視為未截斷（語意對齊軌二既有預設值）

    if not n_by_path:
        complete, completeness_check = None, "unknown"
    else:
        vals = list(complete_by_path.values())
        methods = set(check_by_path.values())
        if any(v is False for v in vals):
            complete = False
        elif all(v is True for v in vals):
            complete = True
        else:
            complete = None
        completeness_check = methods.pop() if len(methods) == 1 else "unknown"

    reported_total_top = None
    tf_key, _m = _find_reported_total(data if isinstance(data, dict) else {})
    if tf_key:
        reported_total_top = data.get(tf_key)

    if not n_by_path or any(v is None for v in dup_by_path.values()):
        dup_total = None
    else:
        dup_total = sum(dup_by_path.values())

    return {
        "n": n_total,
        "n_by_path": n_by_path if len(n_by_path) > 1 else None,
        "complete": complete,
        "completeness_check": completeness_check,
        "reported_total": reported_total_top,
        "truncated": truncated,
        "dup_keys": dup_total,
    }


def main():
    os.makedirs(DATA, exist_ok=True)
    manifest = {"date": TODAY, "fetched_at": STAMP, "sources": {}}
    mods = load_adapters()
    only = set(sys.argv[1:])
    if only:
        mods = [m for m in mods if m.KEY in only]
    if not mods:
        print("FATAL 找不到任何 adapter", file=sys.stderr)
        return 1
    for mod in mods:
        key, t0 = mod.KEY, time.time()
        parser_version = getattr(mod, "PARSER_VERSION", 1)
        ok, data, attempts, first_error, last_error, skipped = collect_with_retry(mod, key)
        if ok:
            try:
                payload = {"_meta": {"source": key, "fetched_at": STAMP, "license": "CC BY 4.0"},
                           "data": data}
                path, size = write_gz(key, payload)
                entry = {"ok": True, "bytes": size, "secs": round(time.time() - t0, 1),
                         "parser_version": parser_version, "attempts": attempts}
                if attempts > 1 and first_error:
                    entry["first_error"] = first_error
                # 完整性欄位（SPEC-manifest-fields.md）：獨立 try/except，任何例外都只讓
                # 這幾個新欄位留空，絕不會把已經成功的抓取／已經寫入的快照改記為失敗。
                try:
                    entry.update(compute_manifest_fields(key, data))
                except Exception as _mf_e:
                    print("WARN %-14s 完整性欄位計算失敗（不影響本次抓取成功判定，欄位留空）：%s: %s"
                          % (key, type(_mf_e).__name__, _mf_e), file=sys.stderr, flush=True)
                manifest["sources"][key] = entry
                print("OK   %-14s %10s B %.1fs（attempts=%d）"
                      % (key, format(size, ","), time.time() - t0, attempts))
            except Exception as e:
                # write_gz 等寫入階段失敗不屬於「來源抓取失敗」，不重試，直接記錄。
                err = "%s: %s" % (type(e).__name__, e)
                entry = {"ok": False, "error": err, "secs": round(time.time() - t0, 1),
                         "parser_version": parser_version, "attempts": attempts}
                if first_error:
                    entry["first_error"] = first_error
                manifest["sources"][key] = entry
                print("FAIL %-14s %s" % (key, err), file=sys.stderr)
        else:
            entry = {"ok": False, "error": last_error, "secs": round(time.time() - t0, 1),
                     "parser_version": parser_version, "attempts": attempts}
            if attempts > 1:
                entry["first_error"] = first_error
            if skipped:
                entry["skipped_retry_time_budget"] = True
            manifest["sources"][key] = entry
            print("FAIL %-14s %s（attempts=%d）" % (key, last_error, attempts), file=sys.stderr)
    # manifest 合併寫入：單獨重跑一個來源時，不得覆寫當日其他來源的紀錄
    # （比照軌二 2026-08-28 修過的缺陷：原本用 "w" 無條件覆寫，一次單來源重跑就會蓋掉其他來源）。
    md = os.path.join(DATA, "_manifest")
    os.makedirs(md, exist_ok=True)
    mpath = os.path.join(md, TODAY + ".json")
    merged = {"date": TODAY, "sources": {}}
    if os.path.exists(mpath):
        try:
            merged = json.load(open(mpath, encoding="utf-8"))
            merged.setdefault("sources", {})
        except Exception:
            merged = {"date": TODAY, "sources": {}}
    merged["sources"].update(manifest["sources"])
    merged["date"] = TODAY
    merged["fetched_at"] = STAMP
    merged.setdefault("runs", []).append(
        {"at": STAMP, "sources": sorted(manifest["sources"])})
    tmp = mpath + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=1)
    os.replace(tmp, mpath)
    ok = sum(1 for v in manifest["sources"].values() if v.get("ok"))
    print("--- %d/%d 成功 ---" % (ok, len(mods)))
    # 單一來源失敗不影響其他來源；只有「全部失敗」才回傳非 0（沿用軌一既有行為）
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
