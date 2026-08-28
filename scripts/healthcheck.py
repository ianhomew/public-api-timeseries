#!/usr/bin/env python3
"""每日自我檢查：沉默即異常。
在 repo 根目錄產生／刪除 ALERT.md，隨每日 push 上到 GitHub。
只陳述事實（缺檔／體積異常／manifest 失敗），不做解讀。

時區鐵律：所有快照檔名一律用 **UTC 日期**，本檢查也一律用 UTC 比對。
"""
import os, json, glob, statistics, datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT  = os.path.join(REPO, "ALERT.md")
TODAY = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

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

def snapshots(track, key):
    d = os.path.join(REPO, track, "data", key)
    out = {}
    for p in glob.glob(os.path.join(d, "*.json.gz")):
        out.setdefault(os.path.basename(p)[:10], []).append(p)
    return out

def check_source(track, key, issues):
    label = f"{track}/{key}"
    d = os.path.join(REPO, track, "data", key)
    snaps = snapshots(track, key)
    if not snaps:
        if not os.path.isdir(d):
            # adapter 檔案存在（否則不會進到 ACTIVE），但快照目錄從未建立過 → 從沒成功跑過一次
            issues.append((label, "來源已設定但從未產出：adapter 已部署，但今日完全沒有對應快照目錄"))
        else:
            issues.append((label, "沒有任何快照檔"))
        return
    days = sorted(snaps)
    if TODAY not in snaps:
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

def check_manifest(track, issues):
    p = os.path.join(REPO, track, "data", "_manifest", TODAY + ".json")
    if not os.path.exists(p):
        issues.append((track, f"今日 manifest 不存在 → 排程可能沒跑（UTC {TODAY}）"))
        return
    try:
        m = json.load(open(p, encoding="utf-8"))
    except Exception as e:
        issues.append((track, f"manifest 無法解析：{type(e).__name__}: {e}"))
        return
    for name, v in (m.get("sources") or m.get("channels") or {}).items():
        if not v.get("ok"):
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
    check_timestamps(issues)
    for track in ("track-crypto", "track-gov"):
        check_manifest(track, issues)
    for track, key in ACTIVE:
        check_source(track, key, issues)

    if not issues:
        if os.path.exists(OUT):
            os.remove(OUT)
        print(f"OK {TODAY} 全部正常（{len(ACTIVE)} 個來源）")
        return 0

    lines = [
        "# 🔴 每日自我檢查發現異常",
        "",
        f"檢查時間（UTC）：{datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')}",
        f"檢查基準日（UTC）：{TODAY}",
        "",
        "| 來源 | 問題 |",
        "|---|---|",
    ] + [f"| `{a}` | {b} |" for a, b in issues] + [
        "",
        "本檔由 `scripts/healthcheck.py` 自動產生。異常排除後會自動刪除。",
        "",
        "排查順序：`crontab -l` → `track-*/logs/cron.log` → 手動執行 snapshotter。",
    ]
    open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print(f"ALERT {TODAY} {len(issues)} 項異常")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
