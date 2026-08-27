#!/usr/bin/env python3
"""軌一 snapshotter：加密 / AI 算力市場每日快照
只存原始數字，不做任何分析或觀點（投顧法鐵律）
授權：輸出資料 CC BY 4.0
"""
import json, gzip, os, sys, time, urllib.request, urllib.error, urllib.parse
from datetime import datetime, timezone

BASE = os.path.expanduser("~/snap/track-crypto")
DATA = os.path.join(BASE, "data")
LOGS = os.path.join(BASE, "logs")
def load_env():
    ep = os.path.expanduser("~/snap/.env")
    env = {}
    if os.path.exists(ep):
        for line in open(ep):
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.strip().split("=", 1)
                env[k] = v
    return env

ENV = load_env()
UA = "snapshotter-research/1.0 (daily archival; 1 req/source/day; contact: see repo README)"
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
STAMP = datetime.now(timezone.utc).isoformat()

def fetch(url, retries=3, timeout=45):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = e
            if i < retries - 1:
                time.sleep(3 * (i + 1))
    raise last

def write_gz(source, payload):
    d = os.path.join(DATA, source)
    os.makedirs(d, exist_ok=True)
    final = os.path.join(d, f"{TODAY}.json.gz")
    tmp = final + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, final)          # 原子寫入
    return final, os.path.getsize(final)

# ---------- 來源定義 ----------
def src_x402():
    """x402 Bazaar 全量掛牌（分頁抓完）"""
    items, offset, limit = [], 0, 1000
    while True:
        j = fetch(f"https://api.cdp.coinbase.com/platform/v2/x402/discovery/resources?limit={limit}&offset={offset}")
        batch = j.get("items", [])
        items.extend(batch)
        pg = j.get("pagination", {}) or {}
        total = pg.get("total")
        offset += limit
        if not batch or (total is not None and offset >= total) or offset > 100000:
            break
        time.sleep(1)
    return {"x402Version": j.get("x402Version"), "total": len(items), "items": items}

def src_cex():
    """十家 CEX 交易對／幣種狀態（排除 Binance：robots 全站 Disallow）"""
    eps = {
        "bybit":  "https://api.bybit.com/v5/market/instruments-info?category=spot",
        "okx":    "https://www.okx.com/api/v5/public/instruments?instType=SPOT",
        "bitget": "https://api.bitget.com/api/v2/spot/public/symbols",
        "htx":    "https://api.huobi.pro/v1/common/symbols",
        "gateio": "https://api.gateio.ws/api/v4/spot/currency_pairs",
        "kucoin": "https://api.kucoin.com/api/v2/symbols",
        "mexc":   "https://api.mexc.com/api/v3/exchangeInfo",
    }
    out, errs = {}, {}
    for name, u in eps.items():
        try:
            out[name] = fetch(u)
        except Exception as e:
            errs[name] = f"{type(e).__name__}: {e}"
        time.sleep(1)
    return {"exchanges": out, "errors": errs}

def src_vast():
    q = json.dumps({"limit": 10000, "type": "on-demand", "order": [["dph_total", "asc"]]})
    url = "https://console.vast.ai/api/v0/bundles/?q=" + urllib.parse.quote(q)
    key = ENV.get("VAST_API_KEY")
    hdr = {"User-Agent": UA, "Accept": "application/json"}
    if key:
        hdr["Authorization"] = "Bearer " + key
    req = urllib.request.Request(url, headers=hdr)
    with urllib.request.urlopen(req, timeout=90) as r:
        j = json.loads(r.read().decode("utf-8"))
    j["_authenticated"] = bool(key)
    return j

def src_mcp():
    """MCP 官方註冊表 status/statusChangedAt"""
    servers, cursor, pages = [], None, 0
    while pages < 2000:
        u = "https://registry.modelcontextprotocol.io/v0/servers?limit=100"
        if cursor:
            u += "&cursor=" + urllib.parse.quote(cursor)
        j = fetch(u)
        batch = j.get("servers", [])
        servers.extend(batch)
        cursor = (j.get("metadata") or {}).get("nextCursor")
        pages += 1
        if not cursor or not batch:
            break
        time.sleep(0.25)
    return {"total": len(servers), "servers": servers}

SOURCES = [("x402_bazaar", src_x402), ("cex_symbols", src_cex),
           ("vast_gpu", src_vast), ("mcp_registry", src_mcp)]

def main():
    os.makedirs(LOGS, exist_ok=True)
    manifest = {"date": TODAY, "fetched_at": STAMP, "sources": {}}
    for name, fn in SOURCES:
        t0 = time.time()
        try:
            payload = {"_meta": {"source": name, "fetched_at": STAMP, "license": "CC BY 4.0"},
                       "data": fn()}
            path, size = write_gz(name, payload)
            manifest["sources"][name] = {"ok": True, "bytes": size,
                                         "secs": round(time.time() - t0, 1)}
            print(f"OK   {name:14s} {size:>10,}B {round(time.time()-t0,1)}s")
        except Exception as e:
            manifest["sources"][name] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            print(f"FAIL {name:14s} {type(e).__name__}: {e}", file=sys.stderr)
    mdir = os.path.join(DATA, "_manifest"); os.makedirs(mdir, exist_ok=True)
    with open(os.path.join(mdir, f"{TODAY}.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    ok = sum(1 for v in manifest["sources"].values() if v.get("ok"))
    print(f"--- {ok}/{len(SOURCES)} 成功 ---")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
