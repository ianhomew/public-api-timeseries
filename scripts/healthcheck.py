#!/usr/bin/env python3
"""每日自我檢查：沉默即異常。
在 repo 根目錄產生／刪除 ALERT.md，隨每日 push 上到 GitHub。
只陳述事實（缺檔／體積異常／manifest 失敗），不做解讀。

時區鐵律：所有快照檔名一律用 **UTC 日期**，本檢查也一律用 UTC 比對。

排程時間判定（2026-08-31 修正）：
軌一 track-crypto 08:00 台北起跑（agent_virtuals 全量後預估 35～60 分鐘）、
軌二 track-gov   09:30 台北起跑（實測約 72 分鐘）、
push.sh 11:30 台北起跑（本檢查在此流程內執行）。
在「該軌預期完成時間」之前，「今日缺檔／manifest 不存在」一律不計為異常，
只列為中性的「尚未執行」狀態；超過預期完成時間仍缺檔才是真異常
（不論已缺幾天，一旦超過該軌今日的預期完成時間，都會被抓到，見 check_source/check_manifest）。
"""
import os, json, glob, statistics, datetime
from datetime import timezone, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT  = os.path.join(REPO, "ALERT.md")
# 回放測試用：可用環境變數覆寫「現在時刻」／「今天日期」。
# 正式環境（cron）不會設定這兩個變數，行為與改動前完全相同。
# HEALTHCHECK_NOW 格式：ISO8601 UTC，例如 2026-08-28T23:59:00+00:00
_NOW_OVERRIDE = os.environ.get("HEALTHCHECK_NOW")
NOW_UTC = (datetime.datetime.fromisoformat(_NOW_OVERRIDE) if _NOW_OVERRIDE
           else datetime.datetime.now(timezone.utc))
TODAY = os.environ.get("HEALTHCHECK_TODAY") or NOW_UTC.strftime("%Y-%m-%d")

# 台北 = UTC+8，固定時差（台灣不實施日光節約時間），不可用系統本地時區（本機可能不是台北時區）。
TAIPEI = timezone(timedelta(hours=8))
NOW_TAIPEI = NOW_UTC.astimezone(TAIPEI)

# 排程起跑時間（台北）：僅供狀態文字顯示用。
SCHEDULE_TAIPEI = {"track-crypto": "08:00", "track-gov": "09:30"}
# 預期完成時間（台北）＝ 起跑時間 + 實測耗時 + 30 分鐘寬限。
# track-crypto：08:00 起跑。2026-08-31 起 agent_virtuals 改抓全量（TIME_BUDGET_SECS 600→3000），
# 預估 35～60 分鐘 → 09:20 前完成，保守估計已含寬限。
# track-gov  ：09:30 起跑，實測約 72 分鐘 → 11:15 前完成保守估計已含寬限。
EXPECTED_DONE_TAIPEI = {"track-crypto": "09:20", "track-gov": "11:15"}

def _grace_passed(track):
    """判斷「現在（台北）」是否已過該軌今日的預期完成時間。
    未知軌道（不在表中）一律視為已過寬限，避免漏檢真異常。"""
    exp = EXPECTED_DONE_TAIPEI.get(track)
    if not exp:
        return True
    hh, mm = (int(x) for x in exp.split(":"))
    return (NOW_TAIPEI.hour, NOW_TAIPEI.minute) >= (hh, mm)

# 軌一若沒有 adapters 目錄（例如回滾到舊版驅動程式）時的降級清單。
# 絕對不可讓「adapters 目錄不存在」變成空清單去檢查 —— 那等於自我檢查什麼都不檢查卻回報正常。
FALLBACK_CRYPTO = ["x402_bazaar", "cex_symbols", "vast_gpu"]

def _adapter_keys(track):
    """從 <track>/adapters/*.py 自動探索 KEY，新增來源不必改這支程式。
    回傳 (keys, adapters目錄是否存在)：呼叫端要用第二個值判斷是否該降級。"""
    import re as _re
    adir = os.path.join(REPO, track, "adapters")
    if not os.path.isdir(adir):
        return [], False
    out = []
    for fn in sorted(os.listdir(adir)):
        if fn.endswith(".py") and not fn.startswith("_"):
            m = _re.search(r'^KEY\s*=\s*["\'](.+?)["\']',
                           open(os.path.join(adir, fn), encoding="utf-8").read(), _re.M)
            if m:
                out.append(m.group(1))
    return out, True

_crypto_keys, _crypto_adapters_exist = _adapter_keys("track-crypto")
if not _crypto_adapters_exist:
    # adapters 目錄不存在（例如回滾）：不可變空清單，回退到寫死清單。
    _crypto_keys = FALLBACK_CRYPTO

_gov_keys, _ = _adapter_keys("track-gov")

ACTIVE = ([("track-crypto", k) for k in _crypto_keys] +
          [("track-gov", k) for k in _gov_keys])
LOW, HIGH = 0.5, 3.0   # 體積相對前 7 日中位數的容許區間

# 連續截斷告警（SPEC-trunc-alert.md，2026-08-31 新增）：
# 同一來源連續 N 天 manifest 的 truncated=true 就告警。預設 2（每日一輪，連兩天即異常）。
# 可用環境變數覆寫，正式環境不設定，等同預設值 2。
TRUNC_STREAK_N = int(os.environ.get("TRUNC_STREAK_N", "2"))

def snapshots(track, key):
    d = os.path.join(REPO, track, "data", key)
    out = {}
    for p in glob.glob(os.path.join(d, "*.json.gz")):
        out.setdefault(os.path.basename(p)[:10], []).append(p)
    return out

def check_source(track, key, issues, pending):
    label = f"{track}/{key}"
    d = os.path.join(REPO, track, "data", key)
    snaps = snapshots(track, key)
    if not snaps:
        if not _grace_passed(track):
            pending.append((label, f"尚未執行（排程 {SCHEDULE_TAIPEI.get(track, '?')} 起跑，"
                                    f"預期 {EXPECTED_DONE_TAIPEI.get(track, '?')} 前完成，目前尚未有任何快照）"))
            return
        if not os.path.isdir(d):
            # adapter 檔案存在（否則不會進到 ACTIVE），但快照目錄從未建立過 → 從沒成功跑過一次
            issues.append((label, "來源已設定但從未產出：adapter 已部署，但今日完全沒有對應快照目錄"))
        else:
            issues.append((label, "沒有任何快照檔"))
        return
    days = sorted(snaps)
    if TODAY not in snaps:
        if not _grace_passed(track):
            pending.append((label, f"今日尚未執行（排程 {SCHEDULE_TAIPEI.get(track, '?')} 起跑，"
                                    f"預期 {EXPECTED_DONE_TAIPEI.get(track, '?')} 前完成）；最後一份為 {days[-1]}"))
            return
        # 已過該軌今日預期完成時間仍缺檔 → 真異常，不論已缺幾天都會在此被抓到。
        issues.append((label, f"今日（UTC {TODAY}）缺檔；最後一份為 {days[-1]}"
                              f"（已 {(datetime.date.fromisoformat(TODAY) - datetime.date.fromisoformat(days[-1])).days} 天無新資料）"))
        return
    today_sz = max(os.path.getsize(p) for p in snaps[TODAY])
    prev = [max(os.path.getsize(p) for p in snaps[d]) for d in days if d < TODAY][-7:]
    if prev:
        # 新來源第一天沒有歷史快照可比（prev 為空），不告警；只有累積到至少一天歷史後才比對體積。
        med = statistics.median(prev)
        if med > 0 and (today_sz < med * LOW or today_sz > med * HIGH):
            issues.append((label, f"體積異常：今日 {today_sz:,} B，前 {len(prev)} 日中位數 {med:,.0f} B"
                                  f"（{today_sz/med:.2f}×，容許 {LOW}–{HIGH}×）"))

def _fmt_num(v):
    """千分位格式化；非數字原樣轉字串（manifest 欄位理論上都是數字，防禦性處理）。"""
    return f"{v:,}" if isinstance(v, (int, float)) else str(v)

def check_truncation_streak(track, issues):
    """連續 TRUNC_STREAK_N 天 truncated=true 就告警（SPEC-trunc-alert.md，2026-08-31 新增）。
    讀 <track>/data/_manifest/*.json 每來源的 truncated 欄位（由 snap_gov.py v4 寫入）。
    沒有這個欄位的軌道（目前軌一 track-crypto 尚無每來源時間預算/截斷機制）自動略過，不會誤判。
    只用 <= TODAY 的 manifest，今日 manifest 不存在時交給 check_manifest 處理，避免重複告警。
    異常排除（連續天數 < 門檻）後，這裡自然不會再產生任何項目 → issues 為空 → ALERT.md 自動移除，
    比照本檔既有行為，不留永久殘留。"""
    mdir = os.path.join(REPO, track, "data", "_manifest")
    if not os.path.isdir(mdir):
        return
    all_dates = sorted(os.path.basename(p)[:10]
                        for p in glob.glob(os.path.join(mdir, "*.json")))
    dates = [d for d in all_dates if d <= TODAY]
    if not dates or dates[-1] != TODAY:
        return
    cache = {}
    def load(d):
        if d not in cache:
            p = os.path.join(mdir, d + ".json")
            try:
                cache[d] = json.load(open(p, encoding="utf-8"))
            except Exception:
                cache[d] = None
        return cache[d]
    m_today = load(TODAY)
    if not m_today:
        return
    channels_today = m_today.get("channels") or m_today.get("sources") or {}
    idx_today = len(dates) - 1
    for name, v in channels_today.items():
        if "truncated" not in v or not v.get("truncated"):
            continue
        # 由今天往前累計連續截斷天數
        streak = []
        for back in range(0, len(dates)):
            di = idx_today - back
            if di < 0:
                break
            d = dates[di]
            m = load(d)
            if not m:
                break
            ch = (m.get("channels") or m.get("sources") or {})
            cv = ch.get(name)
            if not cv or "truncated" not in cv or not cv.get("truncated"):
                break
            streak.append((d, cv))
        if len(streak) < TRUNC_STREAK_N:
            continue
        # 找連續截斷開始前，最近一次「未截斷」當日的筆數，當作目標筆數參考。
        target_n = None
        for back in range(len(streak), len(dates)):
            di = idx_today - back
            if di < 0:
                break
            d = dates[di]
            m = load(d)
            if not m:
                continue
            ch = (m.get("channels") or m.get("sources") or {})
            cv = ch.get(name)
            if cv and not cv.get("truncated") and cv.get("n") is not None:
                target_n = cv.get("n")
                break
        target_str = f"{_fmt_num(target_n)} 筆" if target_n is not None else "未知（近期無未截斷紀錄可比對）"
        day_desc = "；".join(
            f"{d} 實際 {_fmt_num(cv.get('n'))} 筆／耗時 {_fmt_num(cv.get('secs'))}s"
            for d, cv in reversed(streak))
        issues.append((f"{track}/{name}",
            f"連續 {len(streak)} 天截斷（truncated=true，達門檻 {TRUNC_STREAK_N} 天）："
            f"{day_desc}；目標（近期未截斷）約 {target_str}"))

def check_manifest(track, issues, pending):
    p = os.path.join(REPO, track, "data", "_manifest", TODAY + ".json")
    if not os.path.exists(p):
        if not _grace_passed(track):
            pending.append((track, f"今日 manifest 尚未產生（排程 {SCHEDULE_TAIPEI.get(track, '?')} 起跑，"
                                    f"預期 {EXPECTED_DONE_TAIPEI.get(track, '?')} 前完成）"))
        else:
            issues.append((track, f"今日 manifest 不存在 → 排程可能沒跑（UTC {TODAY}）"))
        return
    try:
        m = json.load(open(p, encoding="utf-8"))
    except Exception as e:
        issues.append((track, f"manifest 無法解析：{type(e).__name__}: {e}"))
        return
    for name, v in (m.get("sources") or m.get("channels") or {}).items():
        if not v.get("ok"):
            # manifest 內已明確記錄失敗，是既成事實而非時間判定問題，不套用寬限規則。
            issues.append((f"{track}/{name}", f"manifest 標記失敗：{v.get('error','(無錯誤訊息)')}"))

def check_timestamps(issues):
    """時間戳是「資料在該時刻已存在」的唯一客觀證據。
    清單檔產生了卻沒有對應的 .ots，代表當天蓋章失敗 —— 不可靜默略過。
    （stamp.py 會自動補蓋；若隔日仍缺，就是持續性故障。）"""
    d = os.path.join(REPO, "timestamps")
    if not os.path.isdir(d):
        issues.append(("timestamps", "timestamps/ 目錄不存在 → 從未蓋過時間戳"))
        return
    missing = [os.path.basename(p) for p in sorted(glob.glob(os.path.join(d, "SHA256SUMS-*.txt")))
               if not os.path.exists(p + ".ots")]
    if missing:
        issues.append(("timestamps",
                       "缺少 OpenTimestamps 證明 %d 份：%s（stamp.py 會嘗試補蓋，"
                       "若隔日仍缺代表 calendar 持續無回應）"
                       % (len(missing), "、".join(missing))))

def main():
    issues = []
    pending = []
    check_timestamps(issues)
    for track in ("track-crypto", "track-gov"):
        check_manifest(track, issues, pending)
        check_truncation_streak(track, issues)
    for track, key in ACTIVE:
        check_source(track, key, issues, pending)

    if pending:
        print(f"--- {len(pending)} 項尚在排程寬限期內（非異常） ---")
        for a, b in pending:
            print(f"PENDING {a}: {b}")

    if not issues:
        if os.path.exists(OUT):
            os.remove(OUT)
        print(f"OK {TODAY} 全部正常（{len(ACTIVE)} 個來源，{len(pending)} 項尚在寬限期內）")
        return 0

    lines = [
        "# 🔴 每日自我檢查發現異常",
        "",
        f"檢查時間（UTC）：{NOW_UTC.isoformat(timespec='seconds')}",
        f"檢查時間（台北）：{NOW_TAIPEI.isoformat(timespec='seconds')}",
        f"檢查基準日（UTC）：{TODAY}",
        "",
        "| 來源 | 問題 |",
        "|---|---|",
    ] + [f"| `{a}` | {b} |" for a, b in issues] + [""]

    if pending:
        lines += [
            "## 尚在排程寬限期內（非異常，僅供參考）",
            "",
            "| 來源 | 狀態 |",
            "|---|---|",
        ] + [f"| `{a}` | {b} |" for a, b in pending] + [""]

    lines += [
        "本檔由 `scripts/healthcheck.py` 自動產生。異常排除後會自動刪除。",
        "",
        "排查順序：`crontab -l` → `track-*/logs/cron.log` → 手動執行 snapshotter。",
    ]
    open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print(f"ALERT {TODAY} {len(issues)} 項異常")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
