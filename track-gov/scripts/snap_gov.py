#!/usr/bin/env python3
"""軌二 snapshotter v5：政府公告每日快照（adapter 架構 + 來源層級重試 + 每來源時間預算 + 空正文守門）
目的：偵測靜默改寫、下架、撤稿。只存原文，不做任何解讀。
授權：輸出資料 CC BY 4.0（著作權法第 9 條：公文含新聞稿，不受著作權保護）

時區鐵律：檔名日期一律 UTC；排程時間為台北時間。兩者不可混用。
每個來源一支 adapter，放在 track-gov/adapters/<key>.py，介面見 adapters/README.md。

v5 變更（R3-budget，依 SPEC-r3-budget.md，修正 moda_press／ey_press／moi_press 內頁解析失敗時
仍寫入空 body_text 的問題，以及讓 SOURCE_BUDGET_SECS 可依來源覆寫）：
1. 【R3 空正文守門】新增共用層守門 guard_parse_failures()：collect() 正規化後，任何一筆
   body_text 長度小於門檻（預設 BODY_MIN_LEN_DEFAULT=50）一律視為「該筆解析失敗」，不寫入
   快照，並累計 parse_failed 計數寫進 manifest（entry["parse_failed"]）。
   門檻依據：對 18 個來源既有快照（4–7 天，共 7,602 筆真實正文）實測長度分布，所有來源的
   真實最短正文都遠高於 50（各來源最小值介於 58～678 字，中位數介於 113～1951 字），50 這個門檻
   低於任何一個來源觀察到的真實最短值，不會誤傷「本來就很短的正文」，但足以擋下「切點抓
   失敗、body_text 變成空字串或只剩幾個字」的解析失敗案例。
   放在共用層（snap_gov.py）而非各 adapter 的理由：18 個 adapter 中已有 12 個各自寫了
   `if len(body) < 50: continue`（或等效的 truthy 檢查）守門，但 moda_press／ey_press／
   moi_press 這 3 個完全沒有 —— 這正是「每支 adapter 各自記得寫」在真實世界失守的證據
   （R3 稽核發現）。放在共用層之後，新增 adapter 忘記寫守門也會被自動接住，不必逐支複查；
   既有 12 支 adapter 自己的門檻更嚴格或相同時完全是 no-op，不會改變既有行為。
   個別來源如有理由需要更低的門檻（例如 tpe_clarify 因内容本來就精簡，adapter 內部已用
   30），可用模組級 MIN_BODY_LEN 覆寫，向下相容、不強迫所有來源統一成同一個數字。
2. 【依來源覆寫時間預算】adapter 可宣告模組級 SOURCE_BUDGET_SECS（例如某來源已知需要更久），
   collect_with_retry() 讀不到就沿用全域預設 SOURCE_BUDGET_SECS=600。向下相容：未宣告的
   adapter 完全沿用舊行為。

v4 變更（2026-08-31，依 PERF_FIX_SPEC.md，修正來源站台間歇性變慢被我方逾時/重試放大的問題）：
1. fetch() timeout 45→20 秒；重試退避 3s/6s → 2s/4s（重試次數維持 3 次不變）。
   單筆最壞情況：45×3+9=144 秒 → 20×3+6=66 秒。
2. 新增「每來源時間預算」SOURCE_BUDGET_SECS=600 秒（硬上限，比照軌一 agent_virtuals 做法）。
   驅動程式無法中斷 adapter 內部迴圈，所以改用 deadline（UNIX 時間戳）傳給 adapter，
   adapter 自行在每次翻頁／每抓一筆內頁前檢查 time.time() < deadline，超過就停止並回傳已取得的資料。
   介面擴充為 collect(fetch, clean, deadline=None)，向下相容：
   用 inspect.signature 偵測 adapter 的 collect() 是否接受第三個參數，
   只接受 2 個參數的舊 adapter 完全不受影響、也不會被要求接受 deadline。
3. 因 2 而被截斷的來源，其快照 _meta 會標記 "truncated": true 與 "items_fetched": N，
   供 detect_changes_v2.py 判斷是否要跳過「下架」判定（避免把截斷誤判為下架的假警報）。

v3 沿用（來源層級重試，見 FIX_TIMING_RETRY_SPEC.md）：
單一來源（單一 adapter 執行）失敗時，等待 120 秒後重試一次（只重試一次）。
manifest 記錄 attempts（1 或 2）與 first_error（第一次失敗訊息，即使第二次成功也保留）。
總時間保護：本輪已執行超過 90 分鐘時，跳過剩餘重試，直接記為失敗，避免拖垮 11:30 的 push 排程。
注意：這是「單一來源」內部的重試（等一次來源本身，例如 moi_press 網路抖動），
與 fetch() 內既有的「單一 HTTP 請求」重試（3 次、退避 2/4 秒）是兩個不同層級，互不取代。
"""
import json, gzip, os, sys, re, time, html, hashlib, importlib.util, inspect, urllib.request
import requests
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
ADPT = os.path.join(BASE, "adapters")
UA = ("snapshotter-research/1.0 (daily archival; public accountability; 1 req/sec; "
      "github.com/ianhomew/public-api-timeseries)")
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
STAMP = datetime.now(timezone.utc).isoformat()
TAG = re.compile(r"<[^>]+>")

# --- 來源層級重試設定（v3） ---
RETRY_WAIT_SECS = 120       # 單一來源失敗後，重試前等待秒數
MAX_ATTEMPTS = 2            # 最多嘗試次數（1 次原始 + 1 次重試）
MAX_RUN_SECS = 90 * 60      # 本輪總時間保護：超過 90 分鐘不再等待重試
RUN_START = time.time()

# --- 每來源時間預算（v4 新增，見 PERF_FIX_SPEC.md 修正 2；v5 起可依來源覆寫） ---
SOURCE_BUDGET_SECS = 600    # 全域預設：每次 collect() 嘗試的硬上限（每次重試各自重新計算）。
                            # adapter 可宣告模組級 SOURCE_BUDGET_SECS 覆寫此預設值（見
                            # collect_with_retry() 的 getattr 讀取），未宣告則沿用本值。

# --- 空正文守門（R3，v5 新增，見 SPEC-r3-budget.md） ---
BODY_MIN_LEN_DEFAULT = 50  # 共用層預設門檻：依 18 來源既有快照實測長度分布決定（見檔頭 v5 說明），
                            # 低於任何一個來源觀察到的真實最短值，不會誤傷本來就很短的正文。
                            # adapter 可宣告模組級 MIN_BODY_LEN 覆寫（例如 tpe_clarify 內容本來就精簡）。

# --- keep-alive Session（方案 C，見 SPEC-keepalive.md）---
# 每個「來源」（一次 collect_with_retry 呼叫）共用一個 requests.Session 以重用 TCP+TLS
# 連線；來源之間、以及同一來源的重試之間，一律呼叫 _reset_session() 關閉舊連線池、
# 重建全新 Session，確保不會有連線狀態跨來源／跨重試殘留（例如伺服器已把閒置連線
# 主動關閉，殘留的 Session 物件裡還握著失效的 socket）。
_SESSION = None

def _get_session():
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        _SESSION.headers.update({"User-Agent": UA})
    return _SESSION

def _reset_session():
    """關閉目前的 Session（釋放連線池），下次 fetch() 呼叫 _get_session() 會重建全新的。
    在每個來源開始前、每次重試前、來源結束後都會呼叫，確保不跨來源／跨重試殘留連線。"""
    global _SESSION
    if _SESSION is not None:
        try:
            _SESSION.close()
        except Exception:
            pass
        _SESSION = None

def fetch(url, retries=3):
    last = None
    for i in range(retries):
        try:
            sess = _get_session()
            resp = sess.get(url, headers={"User-Agent": UA}, timeout=(20, 20))
            resp.raise_for_status()
            raw = resp.content
            enc = "utf-8"
            m = re.search(rb'charset=["\']?([\w-]+)', raw[:2000], re.I)
            if m:
                enc = m.group(1).decode("ascii", "ignore")
            return raw.decode(enc, "ignore")
        except Exception as e:
            last = e
            # 連線可能已被伺服器主動關閉或已失效：換下一次重試前重建 Session，
            # 避免用一條壞掉的連線繼續重試（requests 的連線池遇到 RemoteDisconnected
            # 等情形通常會自動處理，這裡是額外保險，確保重試永遠拿到乾淨連線）。
            _reset_session()
            if i < retries - 1:
                time.sleep(2 * (i + 1))
    raise last

def clean(h):
    h = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", h)
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", h)
    t = html.unescape(TAG.sub(" ", h))
    t = re.sub(r"[ \t\r\f\v\u3000]+", " ", t)
    return "\n".join(ln.strip() for ln in t.split("\n") if ln.strip())

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
            print("WARN %-20s 缺少 PARSER_VERSION 常數（detect_changes.py 讀不到時預設視為 1）："
                  "新增／修改解析邏輯時務必宣告並於改版時遞增，否則版本比對保護機制不會生效"
                  % getattr(mod, "KEY", name), file=sys.stderr, flush=True)
        out.append(mod)
    return out

def write_gz(key, payload):
    """NEVER_OVERWRITE：已存在且內容不同時另存時戳版本，永不覆蓋歷史"""
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

# 每次抓取都會變動、但與「公告內容是否被改寫」無關的行（例：瀏覽人次計數器）。
# 不濾掉的話，每日 diff 會天天誤報「內容改寫」，真訊號被雜訊淹沒。
VOLATILE_LABEL = re.compile(r"^(瀏覽人次|點閱數|瀏覽次數|點閱次數|人氣指數)[：:]?\s*\d*$")

def strip_volatile(text):
    out, skip_next_number = [], False
    for ln in text.split("\n"):
        if VOLATILE_LABEL.match(ln.strip()):
            skip_next_number = True
            continue
        if skip_next_number:
            skip_next_number = False
            if re.fullmatch(r"[\d,]+", ln.strip()):
                continue
        out.append(ln)
    return "\n".join(out)

def normalize(items):
    out = []
    for it in items:
        body = strip_volatile(it.get("body_text") or "")
        rec = {
            "id": str(it["id"]),
            "url": it["url"],
            "title": (it.get("title") or "")[:300],
            "date": (it.get("date") or "")[:40],
            "body_text": body,
            "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
        }
        for k in ("dataserno", "raw_sha256", "raw_bytes"):
            if k in it:
                rec[k] = it[k]
        out.append(rec)
    return out

def collect_accepts_deadline(mod):
    """用 inspect.signature 判斷 adapter 的 collect() 是否接受第三個參數（deadline）。
    只接受 2 個參數的舊 adapter 回傳 False，驅動程式就只用 2 個參數呼叫，完全不受影響。"""
    try:
        params = list(inspect.signature(mod.collect).parameters.values())
    except (TypeError, ValueError):
        return False
    positional = [p for p in params
                  if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    has_var_positional = any(p.kind is p.VAR_POSITIONAL for p in params)
    return len(positional) >= 3 or has_var_positional

def _call_collect(mod, deadline):
    """向下相容呼叫：新式 adapter 帶 deadline，舊式（僅 2 參數）adapter 完全不傳。
    回傳 (raw_items, truncated)。truncated 只對新式 adapter 有意義
    （用「呼叫返回時是否已超過 deadline」近似判斷是否被截斷；
    舊式 adapter 無法中斷內部迴圈，一律視為未截斷 False）。"""
    if collect_accepts_deadline(mod):
        raw_items = mod.collect(fetch, clean, deadline)
        truncated = time.time() >= deadline
        return raw_items, truncated
    return mod.collect(fetch, clean), False

def guard_parse_failures(mod, items):
    """R3 空正文守門（共用層）：body_text 過短視為該筆解析失敗，不寫入正文，
    只計數、不中止整批（除非全部都失敗，那會在 _collect_once 觸發既有的『0 筆』例外）。
    門檻可用 adapter 模組級 MIN_BODY_LEN 覆寫；未宣告則用全域 BODY_MIN_LEN_DEFAULT。
    回傳 (kept_items, parse_failed_count)。"""
    min_len = getattr(mod, "MIN_BODY_LEN", BODY_MIN_LEN_DEFAULT)
    kept, parse_failed = [], 0
    for it in items:
        if len(it.get("body_text") or "") < min_len:
            parse_failed += 1
            continue
        kept.append(it)
    return kept, parse_failed

def _collect_once(mod, deadline):
    """單次嘗試：抓取＋正規化＋空正文守門＋合法性檢查。失敗一律拋例外，交給重試層處理。"""
    raw_items, truncated = _call_collect(mod, deadline)
    items = normalize(raw_items)
    items, parse_failed = guard_parse_failures(mod, items)
    if not items:
        raise RuntimeError("collect() 正規化＋守門後 0 筆（parse_failed=%d）—— 視為抓取失敗，"
                           "不寫入快照（避免下游誤判為全部下架）" % parse_failed)
    ids = [i["id"] for i in items]
    if len(set(ids)) != len(ids):
        raise RuntimeError("id 重複 %d/%d —— adapter 的識別碼不穩定" % (len(ids) - len(set(ids)), len(ids)))
    return items, truncated, parse_failed

def source_budget_secs(mod):
    """依來源覆寫時間預算（v5）：adapter 可宣告模組級 SOURCE_BUDGET_SECS 覆寫全域預設；
    讀不到（AttributeError）就用全域 SOURCE_BUDGET_SECS=600。向下相容：
    未宣告 SOURCE_BUDGET_SECS 的既有 adapter 完全不受影響。"""
    return getattr(mod, "SOURCE_BUDGET_SECS", SOURCE_BUDGET_SECS)

def collect_with_retry(mod, key):
    """來源層級重試（v3）＋每來源時間預算（v4，v5 起可依來源覆寫）：
    失敗等 120 秒後重試一次；只重試一次；每次嘗試各自有 SOURCE_BUDGET_SECS 秒硬上限
    （全域預設 600 秒，adapter 可用模組級 SOURCE_BUDGET_SECS 覆寫）。
    回傳 (ok, items_or_None, truncated, attempts, first_error_or_None, last_error_or_None,
          skipped_by_budget, parse_failed)。
    第一次就成功時完全不呼叫 time.sleep，沒有任何額外延遲。"""
    attempts = 0
    first_error = None
    last_error = None
    budget = source_budget_secs(mod)
    _reset_session()  # keep-alive：每個來源開始前重建全新 Session，不沿用上一來源的連線
    while True:
        attempts += 1
        deadline = time.time() + budget
        try:
            items, truncated, parse_failed = _collect_once(mod, deadline)
            _reset_session()  # 來源成功結束：關閉本來源用的連線，不留給下一個來源
            return True, items, truncated, attempts, first_error, None, False, parse_failed
        except Exception as e:
            err = "%s: %s" % (type(e).__name__, e)
            last_error = err
            if first_error is None:
                first_error = err
            if attempts >= MAX_ATTEMPTS:
                _reset_session()  # 來源最終失敗：關閉本來源用的連線，不留給下一個來源
                return False, None, False, attempts, first_error, last_error, False, 0
            elapsed = time.time() - RUN_START
            if elapsed + RETRY_WAIT_SECS > MAX_RUN_SECS:
                # 總時間保護：本輪已跑太久，不再等待重試，直接記為失敗，避免拖垮 11:30 的 push 排程。
                print("SKIP_RETRY %-20s 已執行 %.0f 分鐘，超過 90 分鐘總時間保護，放棄重試：%s"
                      % (key, elapsed / 60, err), file=sys.stderr, flush=True)
                _reset_session()  # 來源最終失敗（time budget skip）：關閉連線，不留給下一個來源
                return False, None, False, attempts, first_error, last_error, True, 0
            print("RETRY %-20s 第 1 次失敗：%s；等待 %d 秒後重試（第 2 次，也是最後一次）"
                  % (key, err, RETRY_WAIT_SECS), flush=True)
            _reset_session()  # 重試前重建 Session：120 秒閒置期間伺服器很可能已關閉舊連線
            time.sleep(RETRY_WAIT_SECS)

def main():
    manifest = {"date": TODAY, "fetched_at": STAMP, "channels": {}}
    mods = load_adapters()
    only = set(sys.argv[1:])
    if only:
        mods = [m for m in mods if m.KEY in only]
    if not mods:
        print("FATAL 找不到任何 adapter", file=sys.stderr)
        return 1
    for mod in mods:
        key, t0 = mod.KEY, time.time()
        ok, items, truncated, attempts, first_error, last_error, skipped, parse_failed = \
            collect_with_retry(mod, key)
        if ok:
            try:
                meta = {"channel": key, "desc": mod.DESC,
                        "source_home": getattr(mod, "SOURCE_HOME", ""),
                        "robots_verified": getattr(mod, "ROBOTS_VERIFIED", ""),
                        "parser_version": getattr(mod, "PARSER_VERSION", 1),
                        "fetched_at": STAMP, "license": "CC BY 4.0",
                        "note": "raw government notices; no interpretation",
                        "truncated": truncated, "items_fetched": len(items),
                        "parse_failed": parse_failed}
                payload = {"_meta": meta, "total": len(items), "errors": {}, "items": items}
                path, size = write_gz(key, payload)
                entry = {"ok": True, "n": len(items), "bytes": size,
                         "errors": 0, "secs": round(time.time() - t0, 1), "attempts": attempts,
                         "truncated": truncated, "parse_failed": parse_failed}
                if truncated:
                    entry["items_fetched"] = len(items)
                if attempts > 1 and first_error:
                    entry["first_error"] = first_error
                manifest["channels"][key] = entry
                print("OK   %-20s %4d 筆 %9d B %.1fs（attempts=%d%s%s）"
                      % (key, len(items), size, time.time() - t0, attempts,
                         "，TRUNCATED" if truncated else "",
                         "，parse_failed=%d" % parse_failed if parse_failed else ""))
            except Exception as e:
                # write_gz 等寫入階段失敗不屬於「來源抓取失敗」，不重試，直接記錄。
                err = "%s: %s" % (type(e).__name__, e)
                entry = {"ok": False, "error": err, "secs": round(time.time() - t0, 1), "attempts": attempts}
                if first_error:
                    entry["first_error"] = first_error
                manifest["channels"][key] = entry
                print("FAIL %-20s %s" % (key, err), file=sys.stderr)
        else:
            entry = {"ok": False, "error": last_error, "secs": round(time.time() - t0, 1), "attempts": attempts}
            if attempts > 1:
                entry["first_error"] = first_error
            if skipped:
                entry["skipped_retry_time_budget"] = True
            manifest["channels"][key] = entry
            print("FAIL %-20s %s（attempts=%d）" % (key, last_error, attempts), file=sys.stderr)
    # manifest 合併寫入：單獨重跑一個來源時，不得覆寫當日其他來源的紀錄。
    # （2026-08-28 稽核發現：原本用 "w" 無條件覆寫，一次單來源重跑就把 11/11 蓋成 1/11）
    md = os.path.join(DATA, "_manifest")
    os.makedirs(md, exist_ok=True)
    mpath = os.path.join(md, TODAY + ".json")
    merged = {"date": TODAY, "channels": {}}
    if os.path.exists(mpath):
        try:
            merged = json.load(open(mpath, encoding="utf-8"))
            merged.setdefault("channels", {})
        except Exception:
            merged = {"date": TODAY, "channels": {}}
    merged["channels"].update(manifest["channels"])
    merged["date"] = TODAY
    merged["fetched_at"] = STAMP
    merged.setdefault("runs", []).append(
        {"at": STAMP, "channels": sorted(manifest["channels"])})
    tmp = mpath + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=1)
    os.replace(tmp, mpath)
    ok = sum(1 for v in manifest["channels"].values() if v.get("ok"))
    print("--- %d/%d 成功 ---" % (ok, len(mods)))
    return 0 if ok == len(mods) else 1

if __name__ == "__main__":
    sys.exit(main())
