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
"""
import json, gzip, os, sys, time, hashlib, importlib.util, urllib.request
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
