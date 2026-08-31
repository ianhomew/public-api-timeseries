#!/usr/bin/env python3
"""detect_changes.py — 偵測快照之間的變動，產生可稽核的 diff 紀錄

每日抓取後自動執行。比對最近兩份快照：
  - 內容改寫（同一 dataserno 的 body_sha256 改變）→ 產生 unified diff
  - 新增、下架
有變動才產生檔案；無變動不留痕跡。
輸出：changes/<source>/YYYY-MM-DD.md  +  CHANGES.md（累積索引）
"""
import os, sys, re, gzip, json, glob, difflib
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHANGES = os.path.join(REPO, "changes")
INDEX = os.path.join(REPO, "CHANGES.md")

# 支援全文比對的來源：自 track-gov/adapters/*.py 自動探索，新增機關不必再改這支程式。
# 識別鍵一律用 item["id"]；金管會舊快照（2026-08-26～27）只有 dataserno，由 _key() 相容處理。
def _discover():
    out = {}
    adir = os.path.join(REPO, "track-gov", "adapters")
    if os.path.isdir(adir):
        for fn in sorted(os.listdir(adir)):
            if not fn.endswith(".py") or fn.startswith("_"):
                continue
            src = open(os.path.join(adir, fn), encoding="utf-8").read()
            k = re.search(r'^KEY\s*=\s*["\'](.+?)["\']', src, re.M)
            d = re.search(r'^DESC\s*=\s*["\'](.+?)["\']', src, re.M)
            if k:
                out[k.group(1)] = {"key": "id", "title": "title", "text": "body_text",
                                   "sha": "body_sha256", "url": "url",
                                   "label": d.group(1) if d else k.group(1)}
    return out

TEXT_SOURCES = _discover()

def _key(item, cfg):
    """相容：新快照有 id；金管會舊快照只有 dataserno"""
    return str(item.get(cfg["key"]) or item.get("dataserno") or item.get("id"))


def load(p):
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return json.load(f)

def items_of(j):
    d = j.get("data", j)
    return d.get("items", j.get("items", []))

def snapshots(source):
    """每個 UTC 日期只取最後一份。
    同日多份是「當日重跑／遷移」的產物，不是改寫事件；跨日比較才有意義。"""
    for track in ("track-gov", "track-crypto"):
        d = os.path.join(REPO, track, "data", source)
        if os.path.isdir(d):
            per_day = {}
            for p in sorted(glob.glob(os.path.join(d, "*.json.gz"))):
                per_day[os.path.basename(p)[:10]] = p
            return [per_day[k] for k in sorted(per_day)]
    return []

def errors_of(j):
    d = j.get("data", j)
    return set((d.get("errors") or {}).keys())

def parser_version(j):
    d = j.get("data", j)
    return (d.get("_meta") or {}).get("parser_version", 1)

def compare(source, cfg, f_old, f_new):
    j_old, j_new = load(f_old), load(f_new)
    err = errors_of(j_old) | errors_of(j_new)   # 抓取失敗者不列入下架/新增判定
    list_old = items_of(j_old)
    a = {_key(i, cfg): i for i in list_old}
    b = {_key(i, cfg): i for i in items_of(j_new)}
    added = sorted(set(b) - set(a) - err)
    removed = set(a) - set(b) - err
    changed = sorted(k for k in set(a) & set(b) if a[k][cfg["sha"]] != b[k][cfg["sha"]])

    # 「滾動移出」不是「下架」。
    # 多數來源每日只抓最新 100 筆，有新稿進來就會把最舊的擠出視窗。
    # 這種消失發生在清單尾端，且通常伴隨等量的新增，不代表機關撤稿。
    # 真正的下架是「從清單中段消失」。
    pos = {_key(i, cfg): n for n, i in enumerate(list_old)}
    tail_start = len(list_old) - (len(added) + len(removed)) - 2
    rolled = sorted(k for k in removed if pos.get(k, 0) >= tail_start)
    removed = sorted(removed - set(rolled))
    return a, b, added, removed, changed, rolled

def render(source, cfg, d_old, d_new, a, b, added, removed, changed):
    L = []
    L.append("# 變動偵測 — %s" % cfg["label"])
    L.append("")
    L.append("| 項目 | 值 |")
    L.append("|---|---|")
    L.append("| 來源 | `%s` |" % source)
    L.append("| 比對區間 | `%s` → `%s` |" % (d_old, d_new))
    L.append("| **內容改寫** | **%d** |" % len(changed))
    L.append("| 新增 | %d |" % len(added))
    L.append("| 下架 | %d |" % len(removed))
    L.append("| 偵測時間 | %s |" % datetime.now(timezone.utc).isoformat())
    L.append("")
    if changed:
        L.append("## 🔴 內容改寫（原文被修改）")
        L.append("")
        for k in changed:
            o, n = a[k], b[k]
            L.append("### `%s` %s" % (k, n.get(cfg["title"], "")))
            L.append("")
            L.append("- 來源：%s" % n.get(cfg["url"], ""))
            L.append("- sha256：`%s` → `%s`" % (o[cfg["sha"]][:16], n[cfg["sha"]][:16]))
            L.append("- 字數：%d → %d" % (len(o.get(cfg["text"], "")), len(n.get(cfg["text"], ""))))
            L.append("")
            diff = list(difflib.unified_diff(
                o.get(cfg["text"], "").splitlines(),
                n.get(cfg["text"], "").splitlines(),
                fromfile="%s (%s)" % (k, d_old), tofile="%s (%s)" % (k, d_new),
                lineterm="", n=2))
            L.append("```diff")
            L.extend(diff[:400])
            if len(diff) > 400:
                L.append("... (差異過長，已截斷。完整內容見兩份原始快照)")
            L.append("```")
            L.append("")
    if removed:
        L.append("## ⚠️ 已下架")
        L.append("")
        for k in removed:
            L.append("- `%s` %s" % (k, a[k].get(cfg["title"], "")))
        L.append("")
    if added:
        L.append("## 新增")
        L.append("")
        for k in added:
            L.append("- `%s` %s" % (k, b[k].get(cfg["title"], "")))
        L.append("")
    L.append("---")
    L.append("")
    L.append("本紀錄由 `scripts/detect_changes.py` 自動產生。")
    L.append("僅陳述「內容是否被修改」此一事實，**不含任何解讀或評論**。")
    return "\n".join(L) + "\n"

def update_index(entries):
    head = ["# 變動紀錄索引", "",
            "本檔案自動維護。列出所有偵測到**內容改寫或下架**的日期。", "",
            "| 日期 | 來源 | 改寫 | 下架 | 新增 | 紀錄 |", "|---|---|---|---|---|---|"]
    old = []
    if os.path.exists(INDEX):
        for line in open(INDEX, encoding="utf-8"):
            if line.startswith("| 2") and "|---|" not in line:
                old.append(line.rstrip("\n"))
    rows = sorted(set(old + entries), reverse=True)
    with open(INDEX, "w", encoding="utf-8") as f:
        f.write("\n".join(head + rows) + "\n")

def main():
    total_changed = total_removed = 0
    entries = []
    for source, cfg in TEXT_SOURCES.items():
        snaps = snapshots(source)
        if len(snaps) < 2:
            print("%s: 快照不足 2 份，略過" % source)
            continue
        f_old, f_new = snaps[-2], snaps[-1]
        d_old, d_new = os.path.basename(f_old)[:10], os.path.basename(f_new)[:10]
        # 解析器改版會讓整批 body_sha256 改變，那不是「機關改寫公告」。
        # 版本不同時跳過比對，避免產生 100% 的假警報。
        v_old, v_new = parser_version(load(f_old)), parser_version(load(f_new))
        if v_old != v_new:
            print("%s: 解析器版本 %s→%s，跳過本次比對（非內容改寫）" % (source, v_old, v_new))
            continue
        a, b, added, removed, changed, rolled = compare(source, cfg, f_old, f_new)
        print("%s: %s→%s 改寫%d 下架%d 新增%d%s"
              % (source, d_old, d_new, len(changed), len(removed), len(added),
                 ("（另有 %d 筆滾動移出視窗，不計為下架）" % len(rolled)) if rolled else ""))
        if not (changed or removed):
            continue      # 只有新增不算「變動事件」，不留紀錄
        total_changed += len(changed); total_removed += len(removed)
        outdir = os.path.join(CHANGES, source)
        os.makedirs(outdir, exist_ok=True)
        out = os.path.join(outdir, "%s.md" % d_new)
        with open(out, "w", encoding="utf-8") as f:
            f.write(render(source, cfg, d_old, d_new, a, b, added, removed, changed))
        entries.append("| %s | `%s` | **%d** | %d | %d | [紀錄](changes/%s/%s.md) |"
                       % (d_new, source, len(changed), len(removed), len(added), source, d_new))
        print("  → 已寫入 %s" % out)
    if entries:
        update_index(entries)
    # 供 push.sh 讀取，用來組 commit message
    print("SUMMARY changed=%d removed=%d" % (total_changed, total_removed))
    return 0

if __name__ == "__main__":
    sys.exit(main())
