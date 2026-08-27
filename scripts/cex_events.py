#!/usr/bin/env python3
"""cex_events.py — 從每日 cex_symbols 快照萃取上架/下架事件流

為什麼需要：
  bybit / okx / mexc 三家 API 只回傳「存活」標的，下架後直接消失（下架史遭銷毀）。
  只有 HTX 保留 offline 紀錄（1,547/2,159）。
  用未修正生存者偏誤的資料回測，會系統性高估報酬。

輸出：track-crypto/data/cex_events/events.jsonl（累積、只追加）
  {"date","exchange","symbol","event","from","to"}
  event: LISTED / DELISTED / STATUS_CHANGED

本工具只記錄事實，不做任何解讀或建議。
"""
import os, sys, gzip, json, glob
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "track-crypto/data/cex_symbols")
OUT = os.path.join(REPO, "track-crypto/data/cex_events")
JL = os.path.join(OUT, "events.jsonl")

# 各交易所的 symbol 與 status 欄位路徑
SPEC = {
    "bybit":  {"path": ("result", "list"), "sym": "symbol",    "st": "status"},
    "okx":    {"path": ("data",),          "sym": "instId",    "st": "state"},
    "bitget": {"path": ("data",),          "sym": "symbol",    "st": "status"},
    "htx":    {"path": ("data",),          "sym": "symbol",    "st": "state"},
    "gateio": {"path": None,               "sym": "id",        "st": "trade_status"},
    "kucoin": {"path": ("data",),          "sym": "symbol",    "st": "enableTrading"},
    "mexc":   {"path": ("symbols",),       "sym": "symbol",    "st": "status"},
}

def dig(obj, path):
    if path is None:
        return obj if isinstance(obj, list) else []
    for k in path:
        obj = (obj or {}).get(k, [])
    return obj or []

def snapshot(f):
    """回傳 {exchange: {symbol: status}}"""
    with gzip.open(f, "rt", encoding="utf-8") as fh:
        j = json.load(fh)
    ex = j.get("data", j).get("exchanges", {})
    out = {}
    for name, spec in SPEC.items():
        rows = dig(ex.get(name), spec["path"])
        d = {}
        for r in rows:
            if not isinstance(r, dict):
                continue
            s = r.get(spec["sym"])
            if s:
                d[str(s)] = str(r.get(spec["st"]))
        if d:
            out[name] = d
    return out

def main():
    files = sorted(glob.glob(os.path.join(SRC, "*.json.gz")))
    if len(files) < 2:
        print("快照不足 2 份（目前 %d），無法產生事件流" % len(files))
        return 0
    os.makedirs(OUT, exist_ok=True)
    seen = set()
    if os.path.exists(JL):
        for line in open(JL, encoding="utf-8"):
            try:
                e = json.loads(line)
                seen.add((e["date"], e["exchange"], e["symbol"], e["event"]))
            except Exception:
                pass
    new = []
    for prev_f, cur_f in zip(files[:-1], files[1:]):
        d_prev = os.path.basename(prev_f)[:10]
        d_cur = os.path.basename(cur_f)[:10]
        a, b = snapshot(prev_f), snapshot(cur_f)
        for exch in sorted(set(a) & set(b)):
            pa, pb = a[exch], b[exch]
            for s in sorted(set(pb) - set(pa)):
                new.append({"date": d_cur, "exchange": exch, "symbol": s,
                            "event": "LISTED", "from": None, "to": pb[s]})
            for s in sorted(set(pa) - set(pb)):
                new.append({"date": d_cur, "exchange": exch, "symbol": s,
                            "event": "DELISTED", "from": pa[s], "to": None})
            for s in sorted(set(pa) & set(pb)):
                if pa[s] != pb[s]:
                    new.append({"date": d_cur, "exchange": exch, "symbol": s,
                                "event": "STATUS_CHANGED", "from": pa[s], "to": pb[s]})
    fresh = [e for e in new if (e["date"], e["exchange"], e["symbol"], e["event"]) not in seen]
    if fresh:
        with open(JL, "a", encoding="utf-8") as f:
            for e in fresh:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    from collections import Counter
    c = Counter((e["exchange"], e["event"]) for e in fresh)
    print("新增事件 %d 筆（累積檔 %s）" % (len(fresh), JL))
    for (exch, ev), n in sorted(c.items()):
        print("   %-8s %-15s %d" % (exch, ev, n))
    print("EVENTS new=%d" % len(fresh))
    return 0

if __name__ == "__main__":
    sys.exit(main())
