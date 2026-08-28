#!/usr/bin/env python3
"""軌二 snapshotter v2：政府公告每日快照（adapter 架構）
目的：偵測靜默改寫、下架、撤稿。只存原文，不做任何解讀。
授權：輸出資料 CC BY 4.0（著作權法第 9 條：公文含新聞稿，不受著作權保護）

時區鐵律：檔名日期一律 UTC；排程時間為台北時間。兩者不可混用。
每個來源一支 adapter，放在 track-gov/adapters/<key>.py，介面見 adapters/README.md。
"""
import json, gzip, os, sys, re, time, html, hashlib, importlib.util, urllib.request
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
ADPT = os.path.join(BASE, "adapters")
UA = ("snapshotter-research/1.0 (daily archival; public accountability; 1 req/sec; "
      "github.com/ianhomew/public-api-timeseries)")
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
STAMP = datetime.now(timezone.utc).isoformat()
TAG = re.compile(r"<[^>]+>")

def fetch(url, retries=3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=45) as r:
                raw = r.read()
                enc = "utf-8"
                m = re.search(rb'charset=["\']?([\w-]+)', raw[:2000], re.I)
                if m:
                    enc = m.group(1).decode("ascii", "ignore")
                return raw.decode(enc, "ignore")
        except Exception as e:
            last = e
            if i < retries - 1:
                time.sleep(3 * (i + 1))
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
        try:
            items = normalize(mod.collect(fetch, clean))
            if not items:
                raise RuntimeError("collect() 回傳 0 筆 —— 視為抓取失敗，不寫入快照"
                                   "（避免下游誤判為全部下架）")
            ids = [i["id"] for i in items]
            if len(set(ids)) != len(ids):
                raise RuntimeError("id 重複 %d/%d —— adapter 的識別碼不穩定" % (len(ids) - len(set(ids)), len(ids)))
            payload = {"_meta": {"channel": key, "desc": mod.DESC,
                                 "source_home": getattr(mod, "SOURCE_HOME", ""),
                                 "robots_verified": getattr(mod, "ROBOTS_VERIFIED", ""),
                                 "parser_version": getattr(mod, "PARSER_VERSION", 1),
                                 "fetched_at": STAMP, "license": "CC BY 4.0",
                                 "note": "raw government notices; no interpretation"},
                       "total": len(items), "errors": {}, "items": items}
            path, size = write_gz(key, payload)
            manifest["channels"][key] = {"ok": True, "n": len(items), "bytes": size,
                                         "errors": 0, "secs": round(time.time() - t0, 1)}
            print("OK   %-20s %4d 筆 %9d B %.1fs" % (key, len(items), size, time.time() - t0))
        except Exception as e:
            manifest["channels"][key] = {"ok": False, "error": "%s: %s" % (type(e).__name__, e),
                                         "secs": round(time.time() - t0, 1)}
            print("FAIL %-20s %s: %s" % (key, type(e).__name__, e), file=sys.stderr)
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
