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
import os, json, glob, gzip, statistics, datetime, subprocess, sys
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

# --- 體積檢查：parser_version 改版時跳過判定（SPEC-healthcheck-parserver.md，2026-09-02 新增）---
# 問題：體積檢查用「今日體積 ÷ 前 7 日中位數」，容許 LOW–HIGH（0.5–3.0×，見上方常數，本次
# 改動完全不動這兩個數字）。當來源的 parser_version 在比較視窗內改變過（例如解析器從只抓
# 前 15 筆改成分頁抓滿 100 筆），體積會一次性跳到門檻外，且會連續觸發，直到 7 日視窗被新
# 基準填滿為止——這不是真正的資料異常，是比較基準本身混雜了新舊解析器的產物。
# 解法：比照本專案既有且已在 detect_changes.py 驗證過的原則——parser_version 不同時
# 跳過比對（見 detect_changes.py 的 parser_version() 與 main() 內「解析器改版會讓整批
# body_sha256 改變，那不是機關改寫公告」註解）。套用到體積檢查：today 與比較視窗（prev，
# 最多 7 天）內任一天的 parser_version 不一致時，「今日體積 ÷ 前 7 日中位數」這個比較本身
# 不成立，跳過本次判定，不寫入 issues、不產生 ALERT.md 項目；LOW/HIGH 門檻本身完全不變，
# 版本一致時的判定邏輯也完全不變。視窗內全部天數都變成新版本後（版本改版累積滿 7 天新
# 快照，或來源本身歷史不足 7 天但已全數是新版本），本函式自然回到「版本一致」分支，
# 判定能力自動恢復，不需要人工介入、不查任何白名單、不留永久豁免。
#
# 軌一（track-crypto）／軌二（track-gov）快照格式不同，讀取 parser_version 的位置也不同：
#   軌二：直接寫在快照本體 _meta.parser_version
#         （見 track-gov/scripts/snap_gov.py：meta = {..., "parser_version": ...}）。
#   軌一：_meta 只有 source/fetched_at/license 3 個鍵，不含 parser_version
#         （見 track-crypto/scripts/snap_crypto.py 檔頭明文說明：「_meta 只有這 3 個鍵
#         （軌二的 channels/desc/source_home/robots_verified/parser_version 等擴充欄位
#         一律不進快照本體，只進 manifest」），parser_version 只寫在當日 manifest 的
#         sources[key].parser_version。
# 因此一律「先試快照本體，讀不到再試當日 manifest」，兩者都讀不到時預設 1，
# 比照 detect_changes.py 既有慣例（parser_version() 函式同樣預設 1）。
#
# 容錯：這裡新增了「讀取並解析快照內容」這個動作（既有體積判定只用 os.path.getsize 讀檔案
# 大小，從不解析內容）。healthcheck.py 沒有任何外層 try/except，main() 裡一個未捕捉的例外
# 會讓當次完全不產生 ALERT.md（比多判定一次更糟）。為了不讓「內容讀取／解析失敗」變成新的
# 當機風險，下面兩個讀取函式一律吞下例外、退回 None（最終預設為 1），比照 check_disk() 的
# 既有風格：檢查本身故障時寧可略過該項判定，也不能拖垮整支腳本。唯一副作用是「今日與某歷史
# 日都讀取失敗、且兩者版本其實不同」這種雙重失敗時會誤判為版本一致而照跑比值判定——這種
# 失敗模式的結果是「可能誤警」而非「可能漏警」，方向上與本專案「沉默即異常」的既有精神一致
# （寧可多疑，不可少疑），也不會比修改前更容易漏掉真異常。

def _rep_snapshot_path(paths):
    """同一天可能因重跑產生多份快照（NEVER_OVERWRITE 另存時間戳版本）。
    體積判定既有邏輯一律取當天體積最大的一份代表當天（today_sz / prev 皆是），
    parser_version 判定沿用同一份代表檔，避免『體積用 A 檔、版本用 B 檔』兩者不一致。"""
    return max(paths, key=os.path.getsize)

def _snapshot_meta_parser_version(path):
    """讀快照本體 _meta.parser_version（軌二 track-gov 適用；軌一 track-crypto 的
    _meta 沒有這個鍵，一定回傳 None，由呼叫端 fallback 去讀 manifest）。
    任何讀取／解析失敗一律回傳 None、不拋例外（理由見本節檔頭「容錯」說明）。"""
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            j = json.load(f)
        meta = j.get("data", j).get("_meta")
        if isinstance(meta, dict) and "parser_version" in meta:
            return meta["parser_version"]
    except Exception:
        pass
    return None

_manifest_cache = {}   # (track, date) -> 已解析的 manifest dict／None；同一天同一軌只讀一次檔

def _manifest_parser_version(track, key, date):
    """讀當日 manifest 的 parser_version（軌一 track-crypto 適用，見本節檔頭說明；
    軌二 track-gov 的 manifest 沒有這個欄位，一定回傳 None，但用不到——軌二一定先從
    _snapshot_meta_parser_version 就讀到了）。同一天同一軌的 manifest 只解析一次並快取，
    避免同一天有多個來源時（track-crypto 同一天可能有十幾個來源）重複讀同一份檔。"""
    ck = (track, date)
    if ck not in _manifest_cache:
        p = os.path.join(REPO, track, "data", "_manifest", date + ".json")
        try:
            _manifest_cache[ck] = json.load(open(p, encoding="utf-8"))
        except Exception:
            _manifest_cache[ck] = None
    m = _manifest_cache[ck]
    if not m:
        return None
    src = (m.get("channels") or m.get("sources") or {})
    v = (src.get(key) or {}).get("parser_version")
    return v

def snapshot_parser_version(track, key, date, paths):
    """單一來源單一天的 parser_version：
    軌二（track-gov）：parser_version 就在快照本體 _meta，優先嘗試（見本節檔頭格式說明）。
    軌一（track-crypto）：快照本體 _meta 明確保證不含 parser_version（snap_crypto.py 檔頭
    以 🔴 標記「快照本體格式不可改動」，list 3 個鍵不含 parser_version），嘗試讀快照本體
    必然落空——為避免每天對每個軌一來源都做一次「保證失敗」的完整 gzip 解壓＋JSON 解析
    （部分來源單日快照可達數 MB，例如 x402_bazaar；效能實測見
    docs/healthcheck-parserver-report.md），軌一直接跳過快照本體、改讀當日 manifest
    （已由 _manifest_parser_version 快取，同一天多個來源共用同一次檔案讀取）。
    這只是「先猜哪裡找得到答案」的效能捷徑，兩個分支最終讀到的值與都嘗試一遍完全相同
    （軌一原本嘗試快照本體也一定回傳 None），不改變任何判定結果，也不是來源白名單——
    分流依據是軌（track）這個結構性格式差異，不是個別來源。
    兩者都讀不到時預設 1（比照 detect_changes.py 既有慣例）。"""
    rep = _rep_snapshot_path(paths)
    if track == "track-gov":
        v = _snapshot_meta_parser_version(rep)
        if v is not None:
            return v
    v = _manifest_parser_version(track, key, date)
    return v if v is not None else 1

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
    prev_days = [dd for dd in days if dd < TODAY][-7:]
    prev = [max(os.path.getsize(p) for p in snaps[dd]) for dd in prev_days]
    if prev:
        # 新來源第一天沒有歷史快照可比（prev 為空），不告警；只有累積到至少一天歷史後才比對體積。
        v_today = snapshot_parser_version(track, key, TODAY, snaps[TODAY])
        v_prev = [snapshot_parser_version(track, key, dd, snaps[dd]) for dd in prev_days]
        if any(v != v_today for v in v_prev):
            # parser_version 在比較視窗內改變過：比照 detect_changes.py 既有原則跳過本次
            # 體積判定（見本節檔頭說明）。LOW/HIGH 門檻完全不變，只是這次不拿它來比。
            rebuilt = sum(1 for v in v_prev if v == v_today)
            old_versions = sorted(set(v for v in v_prev if v != v_today))
            old_desc = old_versions[0] if len(old_versions) == 1 else "/".join(str(v) for v in old_versions)
            print(f"NOTICE {label}: parser_version {old_desc}→{v_today}，體積基準重建中，暫不判定"
                  f"（第 {rebuilt}/{len(prev)} 天；視窗內全數為新版本後自動恢復判定，"
                  f"不需人工介入、不留白名單）")
            return
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

# --- 磁碟檢查（SPEC-parser-version-disk.md，2026-09-02 新增）---
# 門檻依 df 自己回報的 Capacity（Used/(Used+Avail)*100）為準，兩級：
#   DISK_WARN_PCT=70 提醒、DISK_CRIT_PCT=85 緊急。
# 理由（詳見 docs/parser-version-disk-report.md）：本專案是無人值守的封存系統，發現異常到
# 有人處理之間可能有數日延遲，門檻刻意比常見的 80/90 更早示警，換取更長的反應時間；
# 2026-09-02 實測目前用量僅 2%，兩個門檻都遠高於現況，不會誤報。
# 這是「不論原因」的通用安全網（含非本專案來源：系統日誌、apt cache、其他租戶等），
# 與下面「專案目錄自身成長速率」的估算是兩個獨立、互補的訊號。
DISK_WARN_PCT = 70
DISK_CRIT_PCT = 85
# 專案目錄每日增長速率的量測視窗上限（天）。14 天可以蓋過單一離群日（例如某天因手動重跑
# 多寫了幾份快照），又不會太舊；專案上線天數 < 14 天時，就用目前已有的全部完整天數。
GROWTH_WINDOW_DAYS = 14

def _disk_usage(path):
    """呼叫系統 df -kP，直接沿用 df 自己的 Capacity 計算方式（Used/(Used+Avail)，四捨五入），
    避免自行用 statvfs 重新算一次，卻因保留空間／捨入方式不同跟 df -h 顯示的數字對不起來。
    回傳 (使用率 pct: float, 可用位元組 avail_bytes: int)；df 執行失敗時回傳 (None, None)
    並印警告，讓磁碟檢查本身故障時不會中止整支 healthcheck.py。"""
    try:
        r = subprocess.run(["df", "-kP", path], capture_output=True, text=True,
                            timeout=10, check=True)
        fields = r.stdout.strip().splitlines()[-1].split()
        avail_bytes = int(fields[3]) * 1024
        pct = float(fields[4].rstrip("%"))
        return pct, avail_bytes
    except Exception as e:
        print("WARN check_disk：df 執行失敗，本次略過磁碟檢查：%s: %s"
              % (type(e).__name__, e), file=sys.stderr, flush=True)
        return None, None

def _project_daily_growth():
    """實測（非估計）專案目錄近 GROWTH_WINDOW_DAYS 天，每天實際新增了多少 bytes。
    掃描 track-*/data 下所有 *.json.gz 與 *.json（含 _manifest/、*.stats.json），依檔名開頭
    內嵌的 UTC 日期（NEVER_OVERWRITE：寫入後不再變動，比對 mtime 更能代表「那天寫入的量」）
    分組加總。只採計「今天以前」已完整跑完的日期；今天可能還在進行中，會低估，不列入。
    回傳統計 dict；可用天數 < 2 天（例如專案剛上線）時回傳 None，不勉強估算。"""
    per_day = {}
    for track in ("track-gov", "track-crypto"):
        d = os.path.join(REPO, track, "data")
        if not os.path.isdir(d):
            continue
        paths = (glob.glob(os.path.join(d, "**", "*.json.gz"), recursive=True) +
                  glob.glob(os.path.join(d, "**", "*.json"), recursive=True))
        for p in paths:
            fn = os.path.basename(p)
            if len(fn) < 10 or fn[4] != "-" or fn[7] != "-":
                continue
            day = fn[:10]
            if day >= TODAY:
                continue
            try:
                per_day[day] = per_day.get(day, 0) + os.path.getsize(p)
            except OSError:
                continue
    days = sorted(per_day)[-GROWTH_WINDOW_DAYS:]
    if len(days) < 2:
        return None
    sizes = [per_day[d] for d in days]
    return {"n_days": len(days), "first": days[0], "last": days[-1],
            "mean_bytes": statistics.mean(sizes), "median_bytes": statistics.median(sizes),
            "min_bytes": min(sizes), "max_bytes": max(sizes)}

def check_disk(issues):
    """根分割區使用率兩級門檻（見 DISK_WARN_PCT/DISK_CRIT_PCT）+ 專案目錄實測每日增長率與
    預估可用天數。不論是否超標都會印一行 DISK 摘要（隨 cron.log 留存，確保增長率／可用天數
    持續有真實量測數字可查）；超標時才寫進 issues（供 main() 產生 ALERT.md）。
    比照本檔既有行為：異常排除（使用率回到門檻以下）後，本函式自然不再 append，
    issues 恢復不含這筆，ALERT.md 依既有機制自動消失，不需額外收尾。"""
    pct, avail = _disk_usage(REPO)
    growth = _project_daily_growth()
    growth_desc = ""
    if growth:
        growth_desc = ("；專案目錄近 %d 天（%s ~ %s）實測平均每日增長 %.2f MB"
                        "（中位數 %.2f MB，範圍 %.2f–%.2f MB）"
                        % (growth["n_days"], growth["first"], growth["last"],
                           growth["mean_bytes"] / 1e6, growth["median_bytes"] / 1e6,
                           growth["min_bytes"] / 1e6, growth["max_bytes"] / 1e6))
        if avail is not None and growth["mean_bytes"] > 0:
            days_left = avail / growth["mean_bytes"]
            growth_desc += ("；若僅以此速率消耗目前剩餘空間，估計約可再撐 %.0f 天"
                             "（假設無其他來源持續增長，僅供參考，不含系統其他增長來源如"
                             "日誌／套件快取）" % days_left)
    if pct is None:
        return
    print("DISK 根分割區使用率 %.1f%%（門檻：提醒 %d%% ／ 緊急 %d%%）%s"
          % (pct, DISK_WARN_PCT, DISK_CRIT_PCT, growth_desc))
    if pct >= DISK_CRIT_PCT:
        issues.append(("disk", "根分割區使用率 %.1f%%，已達緊急門檻（%d%%）%s"
                                % (pct, DISK_CRIT_PCT, growth_desc)))
    elif pct >= DISK_WARN_PCT:
        issues.append(("disk", "根分割區使用率 %.1f%%，已達提醒門檻（%d%%）%s"
                                % (pct, DISK_WARN_PCT, growth_desc)))

# --- CEX 完整性守門告警（SPEC-gate-alert.md，2026-09-04 新增）---
# 背景：cex_events.py（commit e6668b8，2026-09-01）新增交易所級完整性守門，觸發時寫
# track-crypto/data/cex_events/gate_skips.jsonl，但原本沒有接任何告警——守門觸發時沒人
# 會知道（docs/cex-events-audit.md §7.3 第 4 點自己指出的缺口）。
#
# 為什麼不能併入 ALERT.md 的 issues 清單（見 main() 呼叫處），也不比照 ALERT-DELIST.md
# 用「只追加、永久保留」的語意：
#   1. 「不可寫進 ALERT.md」是 SPEC 硬性限制：healthcheck.py 對 ALERT.md 是整檔覆寫
#      （issues 為空時 os.remove(OUT)，非空時 open(OUT,"w") 整段重寫，見 main()），
#      若由本函式以外的地方（例如 cex_events.py 自己）直接寫 ALERT.md，下一輪
#      healthcheck.py 執行時一定會把內容洗掉（已實證，見 docs/gate-alert-and-reaudit.md）。
#   2. gate_skips.jsonl 是「只追加」的事實日誌，且 cex_events.py 每次執行都會對**完整
#      歷史**的所有相鄰快照配對重新掃過一次（不是只算最新一天）——同一個歷史上的失敗，
#      只要那組快照配對還在，往後每天都會被重新附加一次幾乎相同的紀錄。這點與
#      ALERT-DELIST.md 刻意設計成「永久觸發紀錄」不同：那裡的「一旦判定熔斷就是既成事實」
#      語意，套在這裡會讓本告警一旦觸發過一次就永遠回不去「無異常」狀態，違反
#      SPEC-gate-alert.md「要能自動消失、不留永久殘留」的硬性要求。
# 做法：只看「最新一次轉換」（gate_skips.jsonl 裡 date 欄位等於 TODAY 的紀錄）有沒有
# 觸發，比照 check_truncation_streak() 只認 dates[-1]==TODAY 那天的精神——每天的
# TODAY 都不同，昨天以前的舊紀錄（不論 gate_skips.jsonl 裡實際存了幾份重複）一律不看，
# 該交易所下一次轉換恢復正常（不再產生 date==TODAY 的紀錄）時，本檔自動被刪除。
GATE_ALERT_OUT = os.path.join(REPO, "ALERT-CEXGATE.md")

# --- track-crypto 下架偵測完整性守門告警（SPEC-gate-dedup.md，2026-09-04 新增）---
# 背景：track-crypto/scripts/detect_delistings.py 的完整性守門不通過時（judge() 回傳
# "GATE_FAIL"），先前只落地 changes/<source>/YYYY-MM-DD.md 與 CHANGES.md 索引列，
# 沒有接任何告警——只有 BREAKER（熔斷）會呼叫 write_alert_block()／
# write_alert_block_group() 寫 ALERT-DELIST.md。這與上面 check_cex_gate_skips()
# 處理的 gate_skips.jsonl 缺告警是同一類但不同程式的缺口（gate-alert 子代理
# 2026-09-04 稽核 SPEC-gate-alert.md 時一併發現，本輪一併修，見
# docs/gate-alert-and-reaudit.md §5、specs/SPEC-gate-dedup.md）。
#
# 為什麼不沿用 ALERT-DELIST.md、改開獨立檔案（與上面 check_cex_gate_skips() 選擇
# 獨立於 ALERT.md 的理由同構，但這裡是相對於 ALERT-DELIST.md 而非 ALERT.md）：
#   1. ALERT-DELIST.md 的檔頭文字（write_alert_block_group() 寫入、已隨每日 push
#      進公開 repo）明文宣告「本檔案由 track-crypto/scripts/detect_delistings.py
#      獨佔寫入，不與任何其他程式共用」——這是已發布的設計不變量。若讓本檔案
#      （healthcheck.py）也寫入 ALERT-DELIST.md，會讓這句已公開的話變成謊言，
#      也讓兩支排程時機不同的程式（detect_delistings.py 在 push.sh 第 2c 步、
#      healthcheck.py 在第 4b 步）對同一個檔案做「讀-改-寫」，任一方的格式假設
#      稍有出入就可能損毀對方已寫入的永久熔斷紀錄——這正是要避免的檔案所有權衝突
#      （量化細節與其他方案的取捨見本機 docs/gate-dedup-report.md「設計理由」一節）。
#   2. ALERT-DELIST.md 的生命週期語意是「永久觸發紀錄，刻意不會因隔天恢復正常而
#      消失」（detect_delistings.py 檔頭原文），與 SPEC 要求 GATE_FAIL 告警「要能
#      自動消失」直接相反——與上面 gate_skips/ALERT-CEXGATE.md 面對 ALERT-DELIST.md
#      時的判斷完全同構（見 check_cex_gate_skips() 上方模組層級註解第 2 點），
#      沿用同一個結論：語意不相容的兩種生命週期不該共用同一個實體檔案。
# 做法（與 check_cex_gate_skips() 完全對稱）：只看 track-crypto/data/_gate_fail/
# gate_skips.jsonl 裡 date==TODAY 的紀錄，異常排除後（不再有 date==TODAY 的紀錄）
# 自動刪除本檔案，不留永久殘留。
DELIST_GATE_ALERT_OUT = os.path.join(REPO, "ALERT-DELISTGATE.md")

def check_delist_gate_fail():
    """讀 track-crypto/data/_gate_fail/gate_skips.jsonl，只取 date==TODAY 的紀錄
    判斷「這次轉換」是否觸發 GATE_FAIL；寫入／刪除獨立檔案 ALERT-DELISTGATE.md
    （不進 ALERT.md 的 issues 清單，理由見上方模組層級註解；與 check_cex_gate_skips()
    是結構相同的姊妹函式，唯一差別是讀的事實檔案／鍵值欄位／輸出檔名不同）。"""
    p = os.path.join(REPO, "track-crypto", "data", "_gate_fail", "gate_skips.jsonl")
    today_fails = []
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    g = json.loads(line)
                except Exception:
                    continue
                if g.get("date") == TODAY:
                    today_fails.append(g)

    # record_gate_fail() 寫入時已去重（見 track-crypto/scripts/detect_delistings.py），
    # 這裡再做一次顯示層去重純屬防禦性寫法，比照 check_cex_gate_skips() 的既有慣例
    # （即使上游手動被重跑導致罕見的重複，這裡也只影響顯示筆數，不影響正確性）。
    dedup = {}
    for g in today_fails:
        key = (g.get("source"), g.get("group"), g.get("from_date"), g.get("date"), g.get("reason"))
        dedup[key] = g
    today_fails = sorted(dedup.values(), key=lambda g: (g.get("source") or "", g.get("group") or ""))

    print("DELIST_GATE_FAIL 今日（%s）觸發來源數 = %d" % (TODAY, len(today_fails)))

    if not today_fails:
        if os.path.exists(DELIST_GATE_ALERT_OUT):
            os.remove(DELIST_GATE_ALERT_OUT)
        return

    def _label(g):
        source, group = g.get("source"), g.get("group")
        return ("`%s`" % source) if group == source else ("`%s`／子集合 `%s`" % (source, group))

    lines = [
        "# 🔴 track-crypto 下架偵測完整性守門觸發",
        "",
        f"檢查時間（UTC）：{NOW_UTC.isoformat(timespec='seconds')}",
        f"檢查時間（台北）：{NOW_TAIPEI.isoformat(timespec='seconds')}",
        f"對應轉換目標日（UTC，該來源最新快照日）：{TODAY}",
        "",
        "| 來源 | 比對區間 | 前日筆數 | 當日筆數 | 原因 |",
        "|---|---|---|---|---|",
    ] + [
        "| %s | `%s` → `%s` | %r | %r | %s |"
        % (_label(g), g.get("from_date"), g.get("date"), g.get("n_old"), g.get("n_new"), g.get("reason"))
        for g in today_fails
    ] + [
        "",
        ("以上來源（或子集合）本次轉換的自清單消失／新增判定**已跳過**（不寫 LISTED／"
         "DELISTED／REAPPEARED／STATUS_CHANGED），原始快照本身仍照常保存，只是這次轉換"
         "不參與比對。人類可讀細節見對應 `changes/<source>/%s.md`。" % TODAY),
        "",
        ("排查建議：檢查對應來源的 adapter 是否變更或暫時性故障"
         "（`track-crypto/adapters/`／`track-crypto/logs/`），確認後可手動重跑 "
         "`python3 track-crypto/scripts/detect_delistings.py` 補算。"),
        "",
        ("本檔由 `scripts/healthcheck.py`（`check_delist_gate_fail()`）自動產生，只反映"
         "**最新一次轉換**的守門狀態；異常排除後（該來源下一次轉換不再觸發）會自動刪除，"
         "不留永久殘留。完整歷史紀錄（含已排除的舊紀錄）見 "
         "`track-crypto/data/_gate_fail/gate_skips.jsonl`。"),
    ]
    open(DELIST_GATE_ALERT_OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("ALERT-DELISTGATE %s %d 個來源／子集合觸發完整性守門" % (TODAY, len(today_fails)))


def check_cex_gate_skips():
    """讀 track-crypto/data/cex_events/gate_skips.jsonl，只取 date==TODAY 的紀錄
    判斷「這次轉換」是否觸發守門；寫入／刪除獨立檔案 ALERT-CEXGATE.md（不進 ALERT.md
    的 issues 清單，理由見上方模組層級註解）。"""
    p = os.path.join(REPO, "track-crypto", "data", "cex_events", "gate_skips.jsonl")
    today_skips = []
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    g = json.loads(line)
                except Exception:
                    continue
                if g.get("date") == TODAY:
                    today_skips.append(g)

    # gate_skips.jsonl 本身沒有去重機制（cex_events.py 對 events.jsonl 有 seen 去重，
    # 對 gate_skips.jsonl 沒有，見 docs/gate-alert-and-reaudit.md）；同一天內若
    # push.sh 被手動重跑，同一組合可能被寫入超過一次。這裡只影響顯示筆數，
    # 用 (exchange, from_date, date) 當鍵去重，內容相同時取最後一筆即可。
    dedup = {}
    for g in today_skips:
        key = (g.get("exchange"), g.get("from_date"), g.get("date"))
        dedup[key] = g
    today_skips = sorted(dedup.values(), key=lambda g: (g.get("exchange") or "",))

    print("CEX_GATE_SKIPS 今日（%s）觸發交易所數 = %d" % (TODAY, len(today_skips)))

    if not today_skips:
        if os.path.exists(GATE_ALERT_OUT):
            os.remove(GATE_ALERT_OUT)
        return

    lines = [
        "# 🔴 cex_events 完整性守門觸發",
        "",
        f"檢查時間（UTC）：{NOW_UTC.isoformat(timespec='seconds')}",
        f"檢查時間（台北）：{NOW_TAIPEI.isoformat(timespec='seconds')}",
        f"對應轉換目標日（UTC，cex_symbols 最新快照日）：{TODAY}",
        "",
        "| 交易所 | 比對區間 | 原因 |",
        "|---|---|---|",
    ] + [
        "| `%s` | `%s` → `%s` | %s |" % (g.get("exchange"), g.get("from_date"), g.get("date"), g.get("reason"))
        for g in today_skips
    ] + [
        "",
        ("以上交易所本次轉換的上／下架事件判定**已跳過**（不寫 LISTED／DELISTED／"
         "STATUS_CHANGED），原始快照本身仍照常保存，只是這組交易所這次不參與比對。"
         "設計見 `docs/cex-events-audit.md` §4.2。"),
        "",
        ("排查建議：檢查對應交易所端點是否變更或暫時性故障"
         "（`track-crypto/adapters/cex_symbols.py` 的 `ENDPOINTS`／`track-crypto/logs/`），"
         "確認後可手動重跑 `python3 scripts/cex_events.py` 補算。"),
        "",
        ("本檔由 `scripts/healthcheck.py`（`check_cex_gate_skips()`）自動產生，只反映"
         "**最新一次轉換**的守門狀態；異常排除後（該交易所下一次轉換不再觸發）會自動刪除，"
         "不留永久殘留。完整歷史紀錄（含已排除的舊紀錄）見 "
         "`track-crypto/data/cex_events/gate_skips.jsonl`。"),
    ]
    open(GATE_ALERT_OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("ALERT-CEXGATE %s %d 個交易所觸發完整性守門" % (TODAY, len(today_skips)))


def main():
    issues = []
    pending = []
    check_timestamps(issues)
    check_disk(issues)
    for track in ("track-crypto", "track-gov"):
        check_manifest(track, issues, pending)
        check_truncation_streak(track, issues)
    for track, key in ACTIVE:
        check_source(track, key, issues, pending)

    if pending:
        print(f"--- {len(pending)} 項尚在排程寬限期內（非異常） ---")
        for a, b in pending:
            print(f"PENDING {a}: {b}")

    # 獨立告警檔（不進 issues／ALERT.md，見 check_cex_gate_skips() 模組層級註解）
    check_cex_gate_skips()
    check_delist_gate_fail()  # 同上，見 check_delist_gate_fail() 模組層級註解（本輪新增）

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
