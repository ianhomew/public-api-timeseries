#!/usr/bin/env python3
"""detect_changes_v2.py — 偵測快照之間的變動，產生可稽核的 diff 紀錄

每日抓取後自動執行。比對最近兩份快照：
  - 內容改寫（同一 dataserno 的 body_sha256 改變）→ 產生 unified diff
  - 新增、下架
有變動才產生檔案；無變動不留痕跡。
輸出：changes/<source>/YYYY-MM-DD.md  +  CHANGES.md（累積索引）

v4 變更（Window Guard 修法，依 SPEC-window-guard.md；補完 v3／Y3 修法報告第 8.3 節
誠實揭露的已知缺口——新公式在「刻意縮小視窗」時會產生假警報，合成情境實測 49 筆下架
判定中 48 筆是縮窗假動作、只有 1 筆是真下架；2026-08-31 本專案 3 個來源 MAX_ITEMS
100→50 的真實調整，當時純屬巧合被截斷保護接住，不是這條路徑本身安全）：
新增「視窗大小顯著變更 → 跳過下架判定」保護，比照既有 parser_version 不同就跳過比對的
原則（同一套思路）。資料來源：manifest 的 n（筆數，軌二既有欄位／軌一 commit 4211777
補上），不新增、不修改快照內嵌 _meta 欄位（軌一 _meta 硬性上限 3 個 key）。門檻：兩日
視窗大小相對變化 ≥20% 且絕對差 ≥5 筆（雙門檻，沿用 detect_delistings.py 既有
breaker_pct+abs_floor 慣例），門檻依據見 docs/window-guard-report.md「門檻依據」節。
只跳過「下架」（removed／rolled），「改寫」（changed）與「新增」（added）不受影響；
截斷保護（v2）優先序高於本保護，兩者同時成立時行為與訊息逐位元組不變；視窗大小穩定
（相鄰兩日比較不再顯著變化）後下一次比對即自動恢復判定，不需人工介入。實作為 compare()
的唯讀外層包裝 compare_guarded()，compare() 本身（v3／Y3 已回放驗證的核心邏輯，87 條
既有 selftest 直接呼叫）一行未改。對 2026-08-27～09-04 全部 18 來源歷史資料回放，
與 v3（未加本保護）輸出逐位元組相同（0 筆差異）——因為現有歷史上唯一符合「視窗顯著變化」
條件的日期對，全部已經被既有的截斷保護或 parser_version 跳過覆蓋，見
docs/window-guard-report.md 第 4 節。

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

# ============================================================================
# v4 新增（Window Guard，依 SPEC-window-guard.md）：
# 視窗大小顯著變更時跳過下架判定，比照既有 parser_version 不同就跳過比對的原則。
#
# 背景：v3（Y3）修法拿掉 tail_start 對 removed_set 的自我指涉後，回放證明確實修好了
# 「同日大量位移」「清單位置邊界」等既知漏報路徑（docs/y3-rolling-report.md 第 8.2 節），
# 但同一輪測試也誠實揭露一個新副作用（第 8.3 節）：「刻意縮小視窗」（例如調整某來源
# MAX_ITEMS）且沒有同時觸發截斷保護時，會把因視窗變小而自然消失的一大批項目誤判為
# 下架（合成情境實測 49 筆下架裡 48 筆是假警報）。本專案 2026-08-31 確實做過一次真實的
# MAX_ITEMS 100→50 調整（fda_clarify／moj_press／tpe_clarify），當時剛好被截斷保護
# （skip_removed，因逾時 truncated=true）意外接住，不是這條路徑本身安全——下一次若有
# 來源在「沒有逾時」的情況下調整 MAX_ITEMS，就會直接暴露在這個風險下（見
# docs/window-guard-report.md「背景」節，含即使沒有截斷保護也會被本保護擋下的重現）。
#
# 設計原則：
#   1. 不修改 compare() 本身一行程式碼——它是 Y3 已回放驗證、87 條 selftest 直接呼叫
#      的核心比對邏輯，任何改動都要重新承擔「逐位元組零回歸」的驗證責任。改用外層
#      wrapper（compare_guarded()）疊加視窗保護，compare() 100% 原封不動。
#   2. 資料來源：manifest 的 n（筆數），不新增／不修改快照 _meta 欄位（軌一 _meta
#      硬性上限 3 個 key，見 SPEC-window-guard.md「資料來源」節；軌二 _meta 雖無此
#      上限，仍統一走 manifest，兩軌讀法一致，不埋兩條邏輯）。
#   3. 只跳過「下架」（removed／rolled），「改寫」（changed）與「新增」（added）完全不
#      受影響——兩者都是 compare() 已經算好的值，本函式原樣沿用，不重算、不覆寫。
#   4. 截斷保護（v2）優先於視窗變更保護：compare() 本身已經因截斷跳過時
#      （trunc_old or trunc_new），原樣回傳，reason="truncated"，兩者同時成立時訊息與
#      行為都與現況（v3）逐位元組相同（零回歸的一部分）。
#   5. 沒有比較基準（manifest 缺 n）一律不觸發跳過，保留既有（v3）判定——新保護不應該
#      因為讀不到某個輔助欄位就意外擴大跳過範圍。
#   6. 門檻依 2026-08-27～09-04 全歷史 124 組「視窗穩定」真實資料訂定（相對變化最大僅
#      1.01%），與已知的 MAX_ITEMS 事件（相對變化 28.2%～67.0%）有 >25 倍安全邊界，
#      理由與完整數據見 docs/window-guard-report.md「門檻依據」節。
# ============================================================================

WINDOW_CHANGE_REL_THRESHOLD = 0.20   # 相對變化門檻：20%（見上方第 6 點門檻依據）
WINDOW_CHANGE_ABS_FLOOR = 5          # 絕對筆數下限：5 筆（避免小視窗來源被自然雜訊觸發）

_MANIFEST_CACHE = {}

def _load_manifest_cached(track, date):
    """v4 新增：讀單一 <track>/data/_manifest/<date>.json，同一輪 main() 內對同一個
    (track, date) 只讀一次磁碟（多個來源常共用同一天的 manifest）。找不到／解析失敗
    回傳 None，呼叫端一律保守處理，不假設一定讀得到。"""
    key = (track, date)
    if key not in _MANIFEST_CACHE:
        p = os.path.join(REPO, track, "data", "_manifest", "%s.json" % date)
        try:
            with open(p, encoding="utf-8") as f:
                _MANIFEST_CACHE[key] = json.load(f)
        except (OSError, ValueError):
            _MANIFEST_CACHE[key] = None
    return _MANIFEST_CACHE[key]

def window_size_of(source, date):
    """v4 新增：來源在某日的視窗大小（筆數）。優先讀 manifest 的 n（軌二既有欄位；軌一
    2026-09-03 commit 4211777 補上，見 SPEC-window-guard.md「資料來源」節），不讀、
    不新增快照內嵌 _meta 欄位。掃描 track-gov／track-crypto 兩軌（比照 snapshots()
    既有寫法），依序找第一個有該來源紀錄的 manifest；找不到（manifest 不存在、JSON
    壞掉、或當日該來源沒有紀錄）一律回傳 None，呼叫端（window_changed_significantly()）
    對 None 一律保守處理為「不跳過」，不會因為讀不到輔助欄位就擴大既有保護的跳過範圍。"""
    for track in ("track-gov", "track-crypto"):
        m = _load_manifest_cached(track, date)
        if not m:
            continue
        ch = m.get("channels") or m.get("sources") or {}
        v = ch.get(source)
        if v is not None and v.get("n") is not None:
            return v.get("n")
    return None

def window_changed_significantly(n_old, n_new):
    """v4 新增：視窗大小是否顯著變化。雙門檻設計（相對 ≥20% 且絕對 ≥5 筆須同時成立）
    沿用本專案 track-crypto/scripts/detect_delistings.py 既有的 breaker_pct + abs_floor
    慣例（GROUP_SOURCES 設定表），避免小視窗來源被 1~2 筆自然雜訊觸發、也避免大視窗
    來源的 1~2 筆自然雜訊被相對門檻放大誤觸發。門檻依據（實測數據）與「為何不會誤殺
    正常的每日筆數波動」的完整說明見 docs/window-guard-report.md「門檻依據」節：
    2026-08-27~09-04 全歷史 124 組視窗穩定真實資料，相對變化最大僅 1.01%（絕對差最大
    1 筆）；已知 MAX_ITEMS 100→50 事件（含次日恢復）實測相對變化 28.2%~67.0%（絕對差
    11~67 筆）——兩側對本門檻都有 >10 倍安全邊界。n_old／n_new 任一缺值，或 n_old<=0
    （防禦除以零），一律回傳 False（不跳過，見 window_size_of() 說明）。"""
    if n_old is None or n_new is None or n_old <= 0:
        return False
    abs_diff = abs(n_new - n_old)
    rel = abs_diff / n_old
    return rel >= WINDOW_CHANGE_REL_THRESHOLD and abs_diff >= WINDOW_CHANGE_ABS_FLOOR

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


def compare_guarded(source, cfg, f_old, f_new):
    """v4 新增：compare() 的唯讀外層包裝，疊加「視窗大小顯著變更 → 跳過下架判定」保護。
    compare() 本身一行都不改（見上方「設計原則」第 1 點）。

    回傳：compare() 原本的 7 個值（a, b, added, removed, changed, rolled, skip_removed，
    其中 removed／rolled／skip_removed 可能已被本函式覆寫）+ 3 個新值
    (skip_reason, n_old, n_new)，共 10 個值。
    skip_reason ∈ {"truncated", "window_change", None}：None 代表本日正常判定
    （此時 skip_removed 恆為 False）。"""
    a, b, added, removed, changed, rolled, skip_removed = compare(source, cfg, f_old, f_new)
    d_old, d_new = os.path.basename(f_old)[:10], os.path.basename(f_new)[:10]
    n_old, n_new = window_size_of(source, d_old), window_size_of(source, d_new)
    if skip_removed:
        # compare() 本身已判定跳過——目前唯一成因是 v2 截斷保護（trunc_old or
        # trunc_new），優先序高於視窗變更保護，原樣傳回，不重算、不覆寫任何欄位
        # （見「設計原則」第 4 點：兩者同時成立時，行為與訊息都與 v3 逐位元組相同）。
        return a, b, added, removed, changed, rolled, skip_removed, "truncated", n_old, n_new
    if window_changed_significantly(n_old, n_new):
        # 視窗大小顯著變化：比照 parser_version 的處理原則跳過下架判定，changed／added
        # 沿用 compare() 已算好的值，不重算、不放寬（見「設計原則」第 3 點）。
        return a, b, added, [], changed, [], True, "window_change", n_old, n_new
    return a, b, added, removed, changed, rolled, skip_removed, None, n_old, n_new

def render(source, cfg, d_old, d_new, a, b, added, removed, changed, skip_removed,
           skip_reason=None, n_old=None, n_new=None):
    L = []
    L.append("# 變動偵測 — %s" % cfg["label"])
    L.append("")
    L.append("| 項目 | 值 |")
    L.append("|---|---|")
    L.append("| 來源 | `%s` |" % source)
    L.append("| 比對區間 | `%s` → `%s` |" % (d_old, d_new))
    L.append("| **內容改寫** | **%d** |" % len(changed))
    L.append("| 新增 | %d |" % len(added))
    if skip_removed and skip_reason == "window_change":
        removed_cell = "N/A（本日視窗大小顯著變化，不判定）"
    elif skip_removed:
        removed_cell = "N/A（本日快照截斷，不判定）"
    else:
        removed_cell = str(len(removed))
    L.append("| 下架 | %s |" % removed_cell)
    L.append("| 偵測時間 | %s |" % datetime.now(timezone.utc).isoformat())
    L.append("")
    if skip_removed and skip_reason == "window_change":
        rel_pct = (abs(n_new - n_old) / n_old * 100.0) if n_old else float("nan")
        L.append("> ⚠️ **因視窗大小顯著變化，本日不做下架判定。** "
                  "比較區間內本來源的清單筆數（見每日 `_manifest/<date>.json` 的 `n`）"
                  "由 %s 變為 %s（相對變化 %.1f%%，達保護門檻：相對 ≥%.0f%% 且絕對 ≥%d 筆），"
                  "與「視窗大小穩定」的既有假設不符——若仍套用捲動視窗捨去規則，"
                  "可能把大量因視窗調整而自然消失的項目誤判為下架"
                  "（背景見 docs/y3-rolling-report.md 第 8.3 節，本保護依據見 "
                  "SPEC-window-guard.md 與 docs/window-guard-report.md）。"
                  "為避免假警報，本次完全不產生「下架」判定，比照既有 `parser_version` "
                  "改版跳過比對的原則；視窗大小穩定後，下一次比對即自動恢復判定，"
                  "不需人工介入、不留白名單。「內容改寫」比對不受影響"
                  "（僅比對兩邊都有的 id）。"
                  % (n_old, n_new, rel_pct, WINDOW_CHANGE_REL_THRESHOLD * 100, WINDOW_CHANGE_ABS_FLOOR))
        L.append("")
    elif skip_removed:
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

def _skip_reason_desc(skip_reason):
    """v4 新增：把 skip_reason（"truncated" / "window_change"）轉成主控台那一行的
    「下架」欄位文字與行尾提示 marker，單一來源維護兩種跳過原因的文字，避免 main() 內
    散落 if/else。截斷（truncated）文字與既有輸出逐字不變（v2 既有行為，零回歸）；
    視窗變動（window_change）是 v4 新增的第二種跳過原因，比照相同格式風格。"""
    if skip_reason == "truncated":
        return "截斷，不判定", "（⚠️ 本日快照截斷，下架判定已跳過）"
    if skip_reason == "window_change":
        return "視窗變動，不判定", "（⚠️ 視窗大小顯著變化，下架判定已跳過）"
    return "跳過，不判定", "（⚠️ 下架判定已跳過）"  # 防禦性 fallback，理論上不會走到


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
        a, b, added, removed, changed, rolled, skip_removed, skip_reason, n_old, n_new = \
            compare_guarded(source, cfg, f_old, f_new)
        if skip_removed:
            removed_desc, marker = _skip_reason_desc(skip_reason)
        else:
            removed_desc, marker = str(len(removed)), ""
        print("%s: %s→%s 改寫%d 下架%s 新增%d%s%s"
              % (source, d_old, d_new, len(changed), removed_desc, len(added),
                 ("（另有 %d 筆滾動移出視窗，不計為下架）" % len(rolled)) if rolled else "",
                 marker))
        if skip_reason == "window_change":
            # v4 新增：比照 parser_version 的處理原則改印 NOTICE（見 SPEC-window-guard.md）。
            # 獨立一行、格式比照 healthcheck.py 既有的 NOTICE 慣例，方便直接 grep。
            rel_pct = (abs(n_new - n_old) / n_old * 100.0) if n_old else float("nan")
            print("NOTICE %s: 視窗大小 %s→%s（相對變化 %.1f%%），下架判定本日跳過"
                  "（視窗變動保護，比照 parser_version 原則；視窗穩定後下一日自動恢復判定）"
                  % (source, n_old, n_new, rel_pct))
        if not (changed or removed):
            continue      # 只有新增（或跳過判定時無改寫可報）不算「變動事件」，不留紀錄
        total_changed += len(changed); total_removed += len(removed)
        outdir = os.path.join(CHANGES, source)
        os.makedirs(outdir, exist_ok=True)
        out = os.path.join(outdir, "%s.md" % d_new)
        with open(out, "w", encoding="utf-8") as f:
            f.write(render(source, cfg, d_old, d_new, a, b, added, removed, changed,
                            skip_removed, skip_reason, n_old, n_new))
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
