#!/usr/bin/env python3
"""explore.py — 檢視已存檔的快照資料

用法：
  explore.py                      總覽：各來源檔案數、日期範圍、大小
  explore.py <source>             列出該來源所有日期
  explore.py <source> <date>      預覽該日快照（摘要 + 樣本）
  explore.py <source> <date> -n 5 顯示 5 筆樣本
  explore.py <source> <date> --raw 印出原始 JSON 前 3000 字
  explore.py --diff <source> <d1> <d2>   比對兩日差異（新增/移除/改寫）
"""
import os, sys, gzip, json, glob, argparse
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DESC = {
    "x402_bazaar":       ("軌一", "x402 協議全量掛牌：誰在賣什麼 API、賣多少錢"),
    "cex_symbols":       ("軌一", "7 家交易所的交易對與幣種狀態（下架即從 API 消失）"),
    "vast_gpu":          ("軌一", "vast.ai GPU 現貨報價（512 筆，已認證）"),
    "mcp_registry":      ("軌一", "MCP 官方註冊表（約 82,000 個 server 與其狀態）"),
    "fsc_clarification": ("軌二", "金管會即時新聞澄清全文（全部歷史 50 筆）"),
}

def sources():
    out = {}
    for track in ("track-crypto", "track-gov"):
        for d in sorted(glob.glob(os.path.join(REPO, track, "data", "*"))):
            name = os.path.basename(d)
            if name == "_manifest":
                continue
            files = sorted(glob.glob(os.path.join(d, "*.json.gz")))
            if files:
                out[name] = files
    return out

def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return "%.1f%s" % (n, u)
        n /= 1024
    return "%.1fTB" % n

def load(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)

def summarize(name, j):
    """回傳 (筆數, 樣本清單)"""
    d = j.get("data", j)
    if name == "x402_bazaar":
        items = d.get("items", [])
        def px(i):
            a = (i.get("accepts") or [{}])[0]
            amt = a.get("amount") or a.get("maxAmountRequired")
            nm = ((a.get("extra") or {}).get("name") or "")
            try:
                return "%.4f %s" % (int(amt) / 1e6, nm or "USDC")
            except Exception:
                return str(amt)
        s = [{"resource": str(i.get("resource"))[:66],
              "price": px(i),
              "network": ((i.get("accepts") or [{}])[0]).get("network"),
              "payTo": str(((i.get("accepts") or [{}])[0]).get("payTo"))[:14] + "...",
              "desc": str(i.get("description") or "")[:64]}
             for i in items[:50]]
        return len(items), s
    if name == "cex_symbols":
        ex = d.get("exchanges", {})
        s = []
        for k, v in ex.items():
            n = 0
            if isinstance(v, dict):
                n = len(v.get("data") or v.get("symbols") or
                        (v.get("result", {}) or {}).get("list") or [])
            elif isinstance(v, list):
                n = len(v)
            s.append({"exchange": k, "symbols": n})
        return sum(x["symbols"] for x in s), s
    if name == "vast_gpu":
        offers = d.get("offers", [])
        s = [{"gpu": o.get("gpu_name"), "num": o.get("num_gpus"),
              "usd_per_hr": o.get("dph_total"), "ram_gb": o.get("gpu_ram"),
              "loc": o.get("geolocation"), "reliability": o.get("reliability2")}
             for o in offers[:50]]
        return len(offers), s
    if name == "mcp_registry":
        srv = d.get("servers", [])
        def _g(x):
            core = x.get("server", x)
            meta = (x.get("_meta") or {}).get("io.modelcontextprotocol.registry/official", {}) or {}
            return {"name": core.get("name"),
                    "version": core.get("version"),
                    "status": meta.get("status") or core.get("status"),
                    "statusChangedAt": meta.get("statusChangedAt"),
                    "publishedAt": meta.get("publishedAt"),
                    "desc": str(core.get("description") or "")[:60]}
        return len(srv), [_g(x) for x in srv[:50]]
    if name == "fsc_clarification":
        items = d.get("items", j.get("items", []))
        s = [{"date": i.get("date"), "title": i.get("title", "")[:60],
              "chars": len(i.get("body_text", "")), "sha": i.get("body_sha256", "")[:12]}
             for i in items[:50]]
        return len(items), s
    return None, []

def stats_path(f):
    return f[:-8] + ".stats.json" if f.endswith(".json.gz") else f + ".stats.json"

def build_stats(name, f, force=False):
    sp = stats_path(f)
    if not force and os.path.exists(sp) and os.path.getmtime(sp) >= os.path.getmtime(f):
        return json.load(open(sp, encoding="utf-8"))
    j = load(f)
    total, sample = summarize(name, j)
    st = {"source": name, "date": os.path.basename(f)[:10],
          "total": total, "bytes": os.path.getsize(f),
          "fetched_at": j.get("_meta", {}).get("fetched_at"),
          "sample_head": sample[:12]}
    tmp = sp + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(st, fh, ensure_ascii=False)
    os.replace(tmp, sp)
    return st

def get_stats(name, f):
    try:
        return build_stats(name, f)
    except Exception:
        return None

def build_all_cache():
    n = 0
    for name, files in sources().items():
        for f in files:
            try:
                build_stats(name, f); n += 1
            except Exception as e:
                print("skip %s: %s" % (f, e))
    print("已建立 %d 份統計快取" % n)

def overview():
    src = sources()
    if not src:
        print("尚無資料")
        return
    print("=" * 78)
    print("已存檔快照總覽    ", datetime.now().strftime("%Y-%m-%d %H:%M"))
    print("=" * 78)
    tot_files = tot_bytes = 0
    for name, files in src.items():
        track, desc = DESC.get(name, ("?", ""))
        days = [os.path.basename(f)[:10] for f in files]
        size = sum(os.path.getsize(f) for f in files)
        tot_files += len(files); tot_bytes += size
        print("\n[%s] %s" % (track, name))
        print("   %s" % desc)
        print("   檔案數 %-4d  日期 %s ~ %s  合計 %s  最新單檔 %s"
              % (len(files), days[0], days[-1], human(size),
                 human(os.path.getsize(files[-1]))))
        st = get_stats(name, files[-1])
        if st and st.get("total") is not None:
            print("   最新一份內含 %s 筆紀錄" % format(st["total"], ","))

    print("\n" + "-" * 78)
    print("總計 %d 個檔案，%s" % (tot_files, human(tot_bytes)))
    print("查看內容： explore.py <source> <date>")
    print("可用 source： %s" % ", ".join(src))

def list_dates(name):
    src = sources()
    if name not in src:
        print("查無來源 %s。可用：%s" % (name, ", ".join(src))); return
    print("%s — 共 %d 個日期" % (name, len(src[name])))
    for f in src[name]:
        print("   %s   %8s" % (os.path.basename(f)[:10], human(os.path.getsize(f))))

def show(name, date, n, raw):
    src = sources()
    if name not in src:
        print("查無來源 %s" % name); return
    hit = [f for f in src[name] if os.path.basename(f).startswith(date)]
    if not hit:
        print("查無 %s 的 %s" % (name, date)); return
    sp = stats_path(hit[0])
    if not raw and n <= 12 and os.path.exists(sp) and os.path.getmtime(sp) >= os.path.getmtime(hit[0]):
        st = json.load(open(sp, encoding="utf-8"))
        if st.get("sample_head"):
            print("=" * 78)
            print("%s  %s   (快取)" % (name, date))
            print("說明：%s" % DESC.get(name, ("", ""))[1])
            print("抓取時間：%s" % st.get("fetched_at"))
            print("=" * 78)
            print("總筆數：%s" % format(st["total"], ",") if st.get("total") else "")
            print()
            for i, row in enumerate(st["sample_head"][:n], 1):
                print("--- %d ---" % i)
                for k, v in row.items():
                    print("   %-12s %s" % (k, str(v)[:100]))
            if st.get("total", 0) > n:
                print()
                print("(僅顯示前 %d 筆，共 %s 筆。-n 超過 12 會讀取完整檔案)" % (n, format(st["total"], ",")))
            return
    j = load(hit[0])
    meta = j.get("_meta", {})
    print("=" * 78)
    print("%s  %s" % (name, date))
    print("說明：%s" % DESC.get(name, ("", ""))[1])
    print("抓取時間：%s" % meta.get("fetched_at", "?"))
    print("授權：%s" % meta.get("license", "?"))
    print("=" * 78)
    if raw:
        print(json.dumps(j, ensure_ascii=False, indent=1)[:3000]); return
    total, sample = summarize(name, j)
    print("總筆數：%s\n" % format(total, ",") if total is not None else "")
    for i, row in enumerate(sample[:n], 1):
        print("--- %d ---" % i)
        for k, v in row.items():
            print("   %-12s %s" % (k, str(v)[:100]))
    if total and total > n:
        print("\n(僅顯示前 %d 筆，共 %s 筆。用 -n 調整)" % (n, format(total, ",")))

def diff(name, d1, d2):
    src = sources()
    f1 = [f for f in src.get(name, []) if os.path.basename(f).startswith(d1)]
    f2 = [f for f in src.get(name, []) if os.path.basename(f).startswith(d2)]
    if not f1 or not f2:
        print("找不到指定日期"); return
    a, b = load(f1[0]), load(f2[0])
    if name == "fsc_clarification":
        ia = {i["dataserno"]: i for i in a["items"]}
        ib = {i["dataserno"]: i for i in b["items"]}
        add = set(ib) - set(ia); rm = set(ia) - set(ib)
        chg = [k for k in set(ia) & set(ib)
               if ia[k]["body_sha256"] != ib[k]["body_sha256"]]
        print("新增 %d、移除 %d、**內容改寫 %d**" % (len(add), len(rm), len(chg)))
        for k in chg:
            print("\n[改寫] %s %s" % (k, ib[k]["title"][:50]))
            print("   %s → %s" % (ia[k]["body_sha256"][:16], ib[k]["body_sha256"][:16]))
        for k in rm:
            print("[下架] %s %s" % (k, ia[k]["title"][:50]))
    else:
        print("目前僅 fsc_clarification 支援 diff")

if __name__ == "__main__":
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("args", nargs="*")
    p.add_argument("-n", type=int, default=8)
    p.add_argument("--raw", action="store_true")
    p.add_argument("--diff", action="store_true")
    p.add_argument("--build-cache", action="store_true")
    p.add_argument("-h", "--help", action="store_true")
    o = p.parse_args()
    if o.help:
        print(__doc__); sys.exit(0)
    if o.build_cache:
        build_all_cache()
    elif o.diff and len(o.args) == 3:
        diff(*o.args)
    elif len(o.args) == 0:
        overview()
    elif len(o.args) == 1:
        list_dates(o.args[0])
    else:
        show(o.args[0], o.args[1], o.n, o.raw)
