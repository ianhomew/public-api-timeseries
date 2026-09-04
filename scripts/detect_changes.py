#!/usr/bin/env python3
"""detect_changes_v2.py — 偵測快照之間的變動，產生可稽核的 diff 紀錄

每日抓取後自動執行。比對最近兩份快照：
  - 內容改寫（同一 dataserno 的 body_sha256 改變）→ 產生 unified diff
  - 新增、下架
有變動才產生檔案；無變動不留痕跡。
輸出：changes/<source>/YYYY-MM-DD.md  +  CHANGES.md（累積索引）

v3 變更（Y3 修法，依 SPEC-y3-rolling.md；本輪僅產出補丁、未部署到正式目錄）：
tail_start 公式原本用「當日新增筆數 + 當日全部消失筆數」估計「自然捲動視窗大小」，
但「當日全部消失筆數」本身就包含尚待判定的「真下架」，等於用未知數的一部分去估計自己的門檻
（新增+移除量越大，安全區自動放大，反而更容易把真下架吞成 rolled，即 Y3 稽核指出的漏報路徑）。
修法：改用「僅新增筆數」估計捲動量（假設視窗大小穩定時，新增 k 筆對應擠出 k 筆最舊的），
不再依賴 removed_set 本身。保留原有 -2 安全緩衝，不放寬既有保護（截斷跳過／parser_version
跳過／揮發性過濾皆未變動）。對 2026-08-27～09-04 全部 18 來源歷史資料回放，
與舊公式在 124 組『非跳過』日期對上輸出逐位元組相同（0 筆差異），詳見
docs/y3-rolling-report.md 第 8 節。

v2 變更（2026-08-31，依 PERF_FIX_SPEC.md 修正 3，最重要的一項）：
若某來源當天被截斷（快照 _meta.truncated=true，例如因每來源 600 秒時間預算被 snap_gov_v4.py
提前中止），只抓到部分筆數，少掉的那些筆數不能被誤判為「下架」——那是災難級的假警報。
規則：比對時只要任一邊快照 _meta.truncated 為 true：
  1. 完全跳過「下架」判定（不產生任何 removed，rolled 也一併跳過，因為它依賴 removed）。
  2. 「內容改寫」仍照常比對（兩邊都有的 id 才比，不受截斷影響）。
  3. 輸出中明確註明「因快照截斷，本日不做下架判定」。
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

def truncated_of(j):
    """v2 新增：快照是否因每來源時間預算被提前中止（snap_gov_v4.py 寫入 _meta.truncated）。"""
    d = j.get("data", j)
    return bool((d.get("_meta") or {}).get("truncated"))

def compare(source, cfg, f_old, f_new):
    j_old, j_new = load(f_old), load(f_new)
    trunc_old, trunc_new = truncated_of(j_old), truncated_of(j_new)
    skip_removed = trunc_old or trunc_new   # v2：任一邊截斷就完全跳過下架判定
    err = errors_of(j_old) | errors_of(j_new)   # 抓取失敗者不列入下架/新增判定
    list_old = items_of(j_old)
    a = {_key(i, cfg): i for i in list_old}
    b = {_key(i, cfg): i for i in items_of(j_new)}
    added = sorted(set(b) - set(a) - err)
    changed = sorted(k for k in set(a) & set(b) if a[k][cfg["sha"]] != b[k][cfg["sha"]])

    if skip_removed:
        # 快照被截斷：少掉的 id 可能只是「這次沒抓到」，不是「機關下架」。
        # 完全不計算 removed / rolled，避免災難級假警報。
        removed, rolled = [], []
    else:
        # 「滾動移出」不是「下架」。
        # 多數來源每日只抓最新 N 筆，有新稿進來就會把最舊的擠出視窗。
        # 這種消失發生在清單尾端，且通常伴隨等量的新增，不代表機關撤稿。
        # 真正的下架是「從清單中段消失」。
        removed_set = set(a) - set(b) - err
        pos = {_key(i, cfg): n for n, i in enumerate(list_old)}
        tail_start = len(list_old) - len(added) - 2  # v3 修法：不再用 removed_set 自我指涉估計捲動量（見 SPEC-y3-rolling.md）
        rolled = sorted(k for k in removed_set if pos.get(k, 0) >= tail_start)
        removed = sorted(removed_set - set(rolled))
    return a, b, added, removed, changed, rolled, skip_removed

def render(source, cfg, d_old, d_new, a, b, added, removed, changed, skip_removed):
    L = []
    L.append("# 變動偵測 — %s" % cfg["label"])
    L.append("")
    L.append("| 項目 | 值 |")
    L.append("|---|---|")
    L.append("| 來源 | `%s` |" % source)
    L.append("| 比對區間 | `%s` → `%s` |" % (d_old, d_new))
    L.append("| **內容改寫** | **%d** |" % len(changed))
    L.append("| 新增 | %d |" % len(added))
    L.append("| 下架 | %s |" % ("N/A（本日快照截斷，不判定）" if skip_removed else str(len(removed))))
    L.append("| 偵測時間 | %s |" % datetime.now(timezone.utc).isoformat())
    L.append("")
    if skip_removed:
        L.append("> ⚠️ **因快照截斷，本日不做下架判定。** "
                  "比對區間內至少一份快照的 `_meta.truncated` 為 `true`"
                  "（來源在每來源 600 秒時間預算內未能抓完全部項目），"
                  "少掉的項目可能只是「這次沒抓到」而非機關真的下架，"
                  "為避免假警報，本次完全不產生「下架」判定。"
                  "「內容改寫」比對不受影響（僅比對兩邊都有的 id）。")
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
    L.append("本紀錄由 `scripts/detect_changes_v2.py` 自動產生。")
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
        a, b, added, removed, changed, rolled, skip_removed = compare(source, cfg, f_old, f_new)
        removed_desc = ("截斷，不判定" if skip_removed else str(len(removed)))
        print("%s: %s→%s 改寫%d 下架%s 新增%d%s%s"
              % (source, d_old, d_new, len(changed), removed_desc, len(added),
                 ("（另有 %d 筆滾動移出視窗，不計為下架）" % len(rolled)) if rolled else "",
                 "（⚠️ 本日快照截斷，下架判定已跳過）" if skip_removed else ""))
        if not (changed or removed):
            continue      # 只有新增（或截斷時無改寫可報）不算「變動事件」，不留紀錄
        total_changed += len(changed); total_removed += len(removed)
        outdir = os.path.join(CHANGES, source)
        os.makedirs(outdir, exist_ok=True)
        out = os.path.join(outdir, "%s.md" % d_new)
        with open(out, "w", encoding="utf-8") as f:
            f.write(render(source, cfg, d_old, d_new, a, b, added, removed, changed, skip_removed))
        entries.append("| %s | `%s` | **%d** | %s | %d | [紀錄](changes/%s/%s.md) |"
                       % (d_new, source, len(changed),
                          ("N/A" if skip_removed else str(len(removed))),
                          len(added), source, d_new))
        print("  → 已寫入 %s" % out)
    if entries:
        update_index(entries)
    # 供 push.sh 讀取，用來組 commit message
    print("SUMMARY changed=%d removed=%d" % (total_changed, total_removed))
    return 0

if __name__ == "__main__":
    sys.exit(main())
