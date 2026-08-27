#!/usr/bin/env python3
"""軌二 snapshotter：金管會公告每日快照（可問責性存檔）
目的：偵測靜默改寫、下架、撤稿。只存原文，不做任何解讀。
授權：輸出資料 CC BY 4.0（著作權法第9條：公文含新聞稿，不受著作權保護）
"""
import json, gzip, os, sys, time, re, hashlib, html, urllib.request
from datetime import datetime, timezone

BASE = os.path.expanduser("~/snap/track-gov")
DATA = os.path.join(BASE, "data")
UA = "snapshotter-research/1.0 (daily archival; public accountability; 1 req/sec)"
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
STAMP = datetime.now(timezone.utc).isoformat()
ROOT = "https://www.fsc.gov.tw/ch/"

CHANNELS = [
    {"key": "fsc_clarification", "id": "609", "parentpath": "0,7,478",
     "list_mc": "disputearea_list.jsp", "view_mc": "disputearea_view.jsp",
     "dtable": "News", "desc": "金管會即時新聞澄清"},
]

def fetch(url, retries=3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as e:
            last = e
            if i < retries - 1:
                time.sleep(3 * (i + 1))
    raise last

TAG = re.compile(r"<[^>]+>")

def clean(h):
    h = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", h)
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", h)
    t = html.unescape(TAG.sub(" ", h))
    t = re.sub(r"[ \t\r\f\v\u3000]+", " ", t)
    return "\n".join(ln.strip() for ln in t.split("\n") if ln.strip())

def grab(raw, cls):
    m = re.search(r'(?is)<div[^>]*class="' + cls + r'"[^>]*>(.*?)</div>', raw)
    return clean(m.group(1)) if m else ""

def body_of(raw):
    """從 class=ap 起，到 footer 前。注意 page-edit 是內容容器，不是頁尾"""
    i = raw.find('class="ap"')
    if i < 0:
        i = raw.find('class="maincontent"')
    if i < 0:
        return ""
    j = len(raw)
    for mark in ['class="footer', 'id="footer"', 'class="gotop"']:
        k = raw.find(mark, i)
        if k > 0:
            j = min(j, k)
    k = raw.find(">", i)
    if 0 < k < i + 200:
        i = k + 1
    return clean(raw[i:j])

def list_sernos(ch):
    out, seen, page = [], set(), 1
    while page <= 50:
        u = (ROOT + "home.jsp?id=" + ch["id"] + "&parentpath=" + ch["parentpath"] +
             "&mcustomize=" + ch["list_mc"] + "&page=" + str(page))
        t = fetch(u)
        found = re.findall(re.escape(ch["view_mc"]) + r"&dataserno=(\d+)", t)
        new = [s for s in dict.fromkeys(found) if s not in seen]
        if not new:
            break
        for s in new:
            seen.add(s); out.append(s)
        page += 1
        time.sleep(1)
    return out

def fetch_item(ch, serno):
    u = (ROOT + "home.jsp?id=" + ch["id"] + "&parentpath=" + ch["parentpath"] +
         "&mcustomize=" + ch["view_mc"] + "&dataserno=" + serno +
         "&dtable=" + ch["dtable"])
    raw = fetch(u)
    body = body_of(raw)
    return {"dataserno": serno, "url": u,
            "title": grab(raw, "subject")[:300],
            "date": grab(raw, "date")[:40],
            "body_text": body,
            "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
            "raw_sha256": hashlib.sha256(raw.encode()).hexdigest(),
            "raw_bytes": len(raw)}

def write_gz(key, payload):
    d = os.path.join(DATA, key); os.makedirs(d, exist_ok=True)
    final = os.path.join(d, TODAY + ".json.gz"); tmp = final + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, final)
    return final, os.path.getsize(final)

def main():
    manifest = {"date": TODAY, "fetched_at": STAMP, "channels": {}}
    for ch in CHANNELS:
        t0 = time.time()
        try:
            sernos = list_sernos(ch)
            items, errs = [], {}
            for s in sernos:
                try:
                    items.append(fetch_item(ch, s))
                except Exception as e:
                    errs[s] = type(e).__name__ + ": " + str(e)
                time.sleep(1)
            payload = {"_meta": {"channel": ch["key"], "desc": ch["desc"],
                                 "fetched_at": STAMP, "license": "CC BY 4.0",
                                 "note": "raw government notices; no interpretation"},
                       "total": len(items), "errors": errs, "items": items}
            path, size = write_gz(ch["key"], payload)
            manifest["channels"][ch["key"]] = {"ok": True, "n": len(items),
                                               "bytes": size, "errors": len(errs),
                                               "secs": round(time.time() - t0, 1)}
            print("OK   %-20s %4d 筆 %8d B %.1fs" % (ch["key"], len(items), size, time.time() - t0))
        except Exception as e:
            manifest["channels"][ch["key"]] = {"ok": False, "error": type(e).__name__ + ": " + str(e)}
            print("FAIL %-20s %s: %s" % (ch["key"], type(e).__name__, e), file=sys.stderr)
    md = os.path.join(DATA, "_manifest"); os.makedirs(md, exist_ok=True)
    with open(os.path.join(md, TODAY + ".json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    ok = sum(1 for v in manifest["channels"].values() if v.get("ok"))
    print("--- %d/%d 成功 ---" % (ok, len(CHANNELS)))
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
