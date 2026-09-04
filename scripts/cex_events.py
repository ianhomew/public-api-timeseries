#!/usr/bin/env python3
"""cex_events.py — 從每日 cex_symbols 快照萃取上架/下架事件流

為什麼需要：
  bybit / okx / mexc 三家 API 只回傳「存活」標的，下架後直接消失（下架史遭銷毀）。
  只有 HTX 保留 offline 紀錄（1,547/2,159）。
  用未修正生存者偏誤的資料回測，會系統性高估報酬。

輸出：track-crypto/data/cex_events/events.jsonl（累積、只追加）
  {"date","exchange","symbol","event","from","to"}
  event: LISTED / DELISTED / STATUS_CHANGED
  當「異常規模熔斷」觸發時（見 CB_MIN_ABS/CB_PCT），額外附加：
  {"note": "anomalous_scale", "removed_pct": <float>}（只在觸發時出現，不影響既有欄位）

完整性守門（2026-09-01 新增，見 docs/cex-events-audit.md）：
  1. 每日只取最後一份快照——同日重跑不是新事件，比照 detect_changes.py 的 snapshots()。
  2. 交易所級失敗守門——若某交易所在 data.errors 記錄擷取例外、或該日快照的
     exchanges 欄位缺席該交易所，這次轉換對該交易所「完全不判定」
    （LISTED/DELISTED/STATUS_CHANGED 皆跳過），並留下 gate_skips.jsonl 紀錄，不靜默跳過。
     （cex_symbols 是 7 家交易所各打一次無分頁 API，失敗是全有全無，
     不像有分頁/時間預算的來源會有「部分擷取」，故此處守門即等同軌二的「截斷守門」。）
  3. 異常規模熔斷——單一交易所單日 DELISTED 筆數超過經驗門檻時，
     事件仍照常寫入（不能為了消假警報就整批不報，見 docs/cex-events-audit.md §4），
     但加註 note:"anomalous_scale"，供下游或人工複核辨識。

gate_skips.jsonl 冪等寫入（2026-09-04 新增，見 specs/SPEC-gate-dedup.md、
docs/gate-dedup-report.md）：本檔 main() 每次執行都對「完整歷史」重新配對計算
（snapshots() 回傳全部歷史快照），若不去重，同一筆完整性守門紀錄會被每天重複附加。
去重鍵 (date, exchange, reason)，做法與下面 events.jsonl 的 seen 集合去重同構——
只用附加模式（"a"）寫檔，從不覆寫或刪減既有內容，只是「這次算出來的清單裡，
哪些已經寫過就不再寫一次」。GATE_LOG_SIZE_HINT_LINES 是純粹的行數提示（見該常數
註解），不是告警，觸發告警的邏輯在 scripts/healthcheck.py 的 check_cex_gate_skips()
（讀本檔案的 date==TODAY 紀錄，與本檔案的去重狀態無關，兩者互不影響）。

本工具只記錄事實，不做任何解讀或建議。
"""
import os, sys, gzip, json, glob
from collections import Counter
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "track-crypto/data/cex_symbols")
OUT = os.path.join(REPO, "track-crypto/data/cex_events")
JL = os.path.join(OUT, "events.jsonl")
GATE_LOG = os.path.join(OUT, "gate_skips.jsonl")
# 檔案大小防護的提示門檻（SPEC-gate-dedup.md 任務 1）：純粹是「該考慮歸檔了」的
# 提示，不是異常，不寫入任何 ALERT-*.md（見 docs/gate-dedup-report.md 設計理由）。
# 訂 500 行：本次去重後，正常運作下每個 (date,exchange,reason) 只會有一行，
# 7 家交易所全部每天都觸發（目前實測歷史 0 次觸發）也要連續 71 天才會碰到，
# 屬於「早該有人工介入調查為什麼天天觸發」的規模，不是誤觸發的門檻。
GATE_LOG_SIZE_HINT_LINES = 500

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

# 異常規模熔斷門檻（2026-09-01 依實測資料訂定，見 docs/cex-events-audit.md §4.2）：
#   2026-08-26~09-01 共 6 組跨日轉換 x 7 家交易所 = 42 組樣本，非零移除率介於 0.048%~1.572%；
#   已核實為真下架的最大單筆案例是 bybit 08-31→09-01（5/546=0.916%）。
#   門檻取「絕對值 10 檔」與「前一日筆數 1%」兩者取大，可讓已知的真實小規模事件維持不觸發，
#   同時標記 mexc 08-28（28/2123=1.32%）、08-30（33/2099=1.57%）這兩個目前資料量下的極端值。
#   樣本僅 7 天，門檻應隨資料持續累積重新校準，不是最終值。
CB_MIN_ABS = 10
CB_PCT = 0.01

def dig(obj, path):
    if path is None:
        return obj if isinstance(obj, list) else []
    for k in path:
        obj = (obj or {}).get(k, [])
    return obj or []

def snapshots():
    """每個 UTC 日期只取最後一份。
    同日多份是「當日重跑」的產物，不是改寫事件；跨日比較才有意義。
    做法照抄 scripts/detect_changes.py 的 snapshots()：同一天多檔時，
    字典序較大的檔名（時間戳記尾綴）自然排在後面、覆蓋較早的。"""
    per_day = {}
    for p in sorted(glob.glob(os.path.join(SRC, "*.json.gz"))):
        per_day[os.path.basename(p)[:10]] = p
    return [per_day[k] for k in sorted(per_day)]

def load(f):
    with gzip.open(f, "rt", encoding="utf-8") as fh:
        return json.load(fh)

def errors_of(j):
    """回傳這份快照裡，data.errors 記錄擷取例外的交易所名稱集合（比照 detect_changes.py）。"""
    d = j.get("data", j)
    return set((d.get("errors") or {}).keys())

def snapshot_from_json(j):
    """回傳 {exchange: {symbol: status}}，只含成功解析且非空的交易所。"""
    ex = j.get("data", j).get("exchanges", {})
    out = {}
    for name, spec in SPEC.items():
        rows = dig(ex.get(name), spec["path"])
        d = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            s = row.get(spec["sym"])
            if s:
                d[str(s)] = str(row.get(spec["st"]))
        if d:
            out[name] = d
    return out

def main():
    files = snapshots()
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

    # gate_skips.jsonl 冪等寫入（SPEC-gate-dedup.md，2026-09-04 新增）：
    # 上面的 for prev_f, cur_f in zip(...) 迴圈每次執行都對「完整歷史」重新配對計算
    # （snapshots() 回傳全部歷史快照，不是只算最新一天），若不去重，同一筆
    # (date, exchange, reason) 完整性守門紀錄會被每天重複附加一次，檔案隨天數線性膨脹
    # （見 docs/gate-alert-and-reaudit.md §5 額外發現 1；scripts/healthcheck.py 的
    # check_cex_gate_skips() 目前用「只看 date==TODAY」加上一層顯示層去重繞過這個問題，
    # 但寫入面本身從未修過，見該函式內建的顯示層 dedup 註解）。
    # 手法比照上面 events.jsonl 既有的 seen 集合去重：去重鍵為 (date, exchange, reason)
    # ——不含 from_date，因為同一 (date, exchange) 在正常單向日曆推進下只會對應一組
    # from_date（快照序列是嚴格遞增的日期鏈），加入 reason 是依 SPEC 指定鍵值逐字採用，
    # 也讓「同一天同一交易所但原因文字不同」這種理論上的邊界情況不會被誤判成同一筆
    # （目前程式碼不會產生這種情況，屬防禦性設計，說明見本機
    # docs/gate-dedup-report.md「設計理由」一節）。
    gate_seen = set()
    if os.path.exists(GATE_LOG):
        for line in open(GATE_LOG, encoding="utf-8"):
            try:
                g = json.loads(line)
                gate_seen.add((g["date"], g["exchange"], g["reason"]))
            except Exception:
                pass

    new = []
    gate_skips = []
    for prev_f, cur_f in zip(files[:-1], files[1:]):
        d_prev = os.path.basename(prev_f)[:10]
        d_cur = os.path.basename(cur_f)[:10]
        j_prev, j_cur = load(prev_f), load(cur_f)
        a, b = snapshot_from_json(j_prev), snapshot_from_json(j_cur)
        err_prev, err_cur = errors_of(j_prev), errors_of(j_cur)

        for exch in sorted(SPEC):
            reasons = []
            if exch in err_prev:
                reasons.append("%s 回報擷取錯誤" % d_prev)
            if exch in err_cur:
                reasons.append("%s 回報擷取錯誤" % d_cur)
            if exch not in a and exch not in err_prev:
                reasons.append("%s 快照缺席（非錯誤清單內，資料仍不可信）" % d_prev)
            if exch not in b and exch not in err_cur:
                reasons.append("%s 快照缺席（非錯誤清單內，資料仍不可信）" % d_cur)
            if reasons:
                msg = ("完整性守門：%s @ %s→%s 本轉換不判定（%s）"
                       % (exch, d_prev, d_cur, "；".join(reasons)))
                print("   [SKIP] " + msg)
                gate_skips.append({"date": d_cur, "exchange": exch, "from_date": d_prev,
                                    "reason": "；".join(reasons)})
                continue

            pa, pb = a[exch], b[exch]
            added = sorted(set(pb) - set(pa))
            removed = sorted(set(pa) - set(pb))
            changed = sorted(s for s in set(pa) & set(pb) if pa[s] != pb[s])

            for s in added:
                new.append({"date": d_cur, "exchange": exch, "symbol": s,
                            "event": "LISTED", "from": None, "to": pb[s]})

            removed_pct = (len(removed) / len(pa) * 100) if pa and removed else 0.0
            threshold = max(CB_MIN_ABS, len(pa) * CB_PCT)
            anomalous = len(removed) > threshold
            if anomalous:
                print("   [CB] %s @ %s→%s：DELISTED %d 檔（%.2f%% of %d），"
                      "超過熔斷門檻 max(%d, %.1f)——事件仍寫入，加註 anomalous_scale"
                      % (exch, d_prev, d_cur, len(removed), removed_pct, len(pa),
                         CB_MIN_ABS, len(pa) * CB_PCT))
            for s in removed:
                ev = {"date": d_cur, "exchange": exch, "symbol": s,
                      "event": "DELISTED", "from": pa[s], "to": None}
                if anomalous:
                    ev["note"] = "anomalous_scale"
                    ev["removed_pct"] = round(removed_pct, 4)
                new.append(ev)

            for s in changed:
                new.append({"date": d_cur, "exchange": exch, "symbol": s,
                            "event": "STATUS_CHANGED", "from": pa[s], "to": pb[s]})

    fresh = [e for e in new if (e["date"], e["exchange"], e["symbol"], e["event"]) not in seen]
    if fresh:
        with open(JL, "a", encoding="utf-8") as f:
            for e in fresh:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    # 只附加「這次執行才第一次算出來」的守門紀錄（gate_seen 未命中的），
    # 已存在的歷史紀錄原封不動保留、不重寫、不刪減——本區塊只用 "a" 附加模式開檔，
    # 從不用 "w" 整檔覆寫，任何情況下都不會動到既有內容（比照本檔案 events.jsonl
    # 一貫的附加寫入慣例）。
    fresh_gate_skips = [g for g in gate_skips
                        if (g["date"], g["exchange"], g["reason"]) not in gate_seen]
    if fresh_gate_skips:
        with open(GATE_LOG, "a", encoding="utf-8") as f:
            for g in fresh_gate_skips:
                f.write(json.dumps(g, ensure_ascii=False) + "\n")
        # 檔案大小防護（SPEC-gate-dedup.md 任務 1，「上限提示」路線，理由見
        # docs/gate-dedup-report.md「設計理由」一節：go-forward 去重已把成長速度限制在
        # 「每個 (date,exchange,reason) 最多一行」，正常運作下極罕見觸發，用輕量的
        # 一次性行數提示取代常駐的自動年份輪替機制，複雜度與風險都更低；
        # 真的需要歸檔時用 scripts/dedup_gate_skips.py --archive-before 手動處理）。
        try:
            _gate_log_lines = sum(1 for _ in open(GATE_LOG, encoding="utf-8"))
        except OSError:
            _gate_log_lines = None
        if _gate_log_lines is not None and _gate_log_lines >= GATE_LOG_SIZE_HINT_LINES:
            print("   [NOTE] %s 已累積 %d 行（提示門檻 %d），可考慮執行 "
                  "scripts/dedup_gate_skips.py --archive-before <YYYY-MM-DD> 歸檔舊紀錄"
                  % (GATE_LOG, _gate_log_lines, GATE_LOG_SIZE_HINT_LINES))

    c = Counter((e["exchange"], e["event"]) for e in fresh)
    print("新增事件 %d 筆（累積檔 %s）" % (len(fresh), JL))
    for (exch, ev), n in sorted(c.items()):
        print("   %-8s %-15s %d" % (exch, ev, n))
    if fresh_gate_skips:
        print("完整性守門觸發 %d 次新紀錄（紀錄於 %s；本次重新計算共 %d 次，%d 次為既有歷史重複已跳過）"
              % (len(fresh_gate_skips), GATE_LOG, len(gate_skips), len(gate_skips) - len(fresh_gate_skips)))
    print("EVENTS new=%d" % len(fresh))
    return 0

if __name__ == "__main__":
    sys.exit(main())
