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

熔斷語意統一（2026-09-07 新增，任務 C，見本機 docs/0907-C-breaker-semantics-report.md）：
  背景：同一個「熔斷」概念，本檔案是「標記但不否決」，
  track-crypto/scripts/detect_delistings.py 卻是「否決整組」，同一個概念兩種行為。
  2026-09-06→09-07 x402_bazaar 熔斷因此讓 1,399 筆 DELISTED、387 筆 LISTED、
  21 筆 REAPPEARED 永久遺失（docs/0907-events-audit-0904-0907.md §6.1）。
  本輪統一成本檔案原本就在用的「標記但不否決」，兩支程式共用同一組欄位名與同一條規則。

  本檔案的三項改動（全部是純加法，既有欄位與既有判定邏輯逐字元不變）：
    1. 標記欄位由 2 個擴充為 4 個，並且**套用到該組轉換產生的每一筆事件**
       （LISTED／DELISTED／STATUS_CHANGED），不再只標記 DELISTED：
         note:"anomalous_scale"（既有，值不變）、removed_pct（既有，值不變）、
         breaker_tripped:true（新增）、breaker_threshold（新增，單位是筆數）。
       理由：熔斷是「這一組轉換整體異常」的性質，不是個別移除項目的性質；
       下游要排除一次異常轉換時，必須能一致地排除該轉換的全部事件。
    2. 新增告警：本檔案的熔斷過去**完全沒有接任何告警管道**（只有 stdout 一行 [CB]，
       進 logs/cex_events.log 就沒人看了）。本輪比照 detect_delistings.py 的
       ALERT-DELIST.md 前例，新增本檔案獨佔的 ALERT-CEXBREAKER.md，
       只對「最新一組轉換」寫入（理由見 write_alert_block_cexbreaker() docstring），
       歷史熔斷的永久紀錄本來就在 events.jsonl 的 breaker_tripped 欄位裡。
    3. 完整性守門（上面第 2 點）由「否決並丟棄」升級為「否決但隔離保存」：
       本來會寫入的事件改寫進 events_quarantine.jsonl，事實不再遺失。
       events.jsonl 的內容完全不受影響（守門本來就不寫進去），
       scripts/verify_prod.py 的冪等檢查只雜湊 events.jsonl，也不受影響。

  為什麼本檔案**不**套用 detect_delistings.py 的「分頁截斷指紋 → 隔離」那一道閘門
  （BREAKER_TRUNCATION_QUARANTINE = False，見該常數註解）：cex_symbols 的 7 家
  交易所全部是單次不分頁端點（例如 MEXC 的 /api/v3/exchangeInfo），結構上不存在
  「分頁提前中止砍掉連續尾端」這種失敗模式；失敗是全有全無，已由上面第 2 點的
  交易所級守門涵蓋（docs/0907-events-audit-0904-0907.md §5.1 已獨立確認這一點）。
  這是「同一條規則、依資料形狀宣告是否適用」，不是兩套規則。

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

# --------------------------------------------------------------------------
# 熔斷語意統一（2026-09-07）新增的常數。名稱與語意與
# track-crypto/scripts/detect_delistings.py 的同名常數一致。
# --------------------------------------------------------------------------
# 隔離檔：完整性守門觸發時，「本來會寫入 events.jsonl 的事件」改寫到這裡，
# 事實完整保留、可人工複核後提升。只追加、去重鍵與 events.jsonl 相同的四元組
# (date, exchange, symbol, event)。
QUARANTINE_JL = os.path.join(OUT, "events_quarantine.jsonl")
# 本檔案獨佔的熔斷告警檔（比照 ALERT-DELIST.md 的所有權設計，見
# write_alert_block_cexbreaker() docstring）。
ALERT_CEXBREAKER = os.path.join(REPO, "ALERT-CEXBREAKER.md")
# 本檔案不套用「分頁截斷指紋 → 隔離」閘門，理由見檔頭「熔斷語意統一」最後一段
# （7 家交易所皆為單次不分頁端點，結構上沒有這種失敗模式）。保留成常數而不是直接
# 刪掉相關程式碼，是為了讓「為什麼兩支程式在這一點上不同」在原始碼裡就看得到；
# 未來若有分頁型端點加入 cex_symbols，把這個值改成 True 即可。
BREAKER_TRUNCATION_QUARANTINE = False
# 分頁截斷指紋門檻（與 detect_delistings.BREAKER_TAIL_COVER_MAX 同值同義）。
# 本檔案只把算出來的 tail_cover 寫進告警當參考資訊，不用它否決任何事情。
BREAKER_TAIL_COVER_MAX = 0.50
# 完整性守門觸發時要不要把「本來會寫入的事件」寫進隔離檔。**預設 False（不寫）**，
# 與 detect_delistings.QUARANTINE_GATE_FAIL 同名同義同預設值（統一語意的一部分）。
# 理由見該常數註解：守門不通過＝這份快照本身已知不可信，由它推出來的差集幾乎必然是
# 假象，保存價值低；實測若開啟，光 agent_virtuals 4 個歷史截斷日就會產生 65,788 筆
# 隔離紀錄（約 13 MB）。本檔案的守門歷來 0 次觸發（gate_skips.jsonl 不存在），
# 開不開啟對現況都沒有實際差別，預設值與 detect_delistings 保持一致比較重要。
QUARANTINE_GATE_FAIL = False

# --------------------------------------------------------------------------
# 熔斷語意統一（2026-09-07）新增的函式。與
# track-crypto/scripts/detect_delistings.py 的同名函式行為一致（同一條規則）。
# --------------------------------------------------------------------------

def removal_tail_metrics(order_keys, removed_keys):
    """分頁截斷指紋：算「前一日清單順序中，結尾連續且全部被移除」的區塊。
    回傳 (tail_run, tail_cover)。定義與 detect_delistings.removal_tail_metrics()
    逐字相同。本檔案只把結果當參考資訊寫進告警，不用它否決任何事情
    （見 BREAKER_TRUNCATION_QUARANTINE 常數註解）。"""
    removed = set(removed_keys)
    if not removed:
        return 0, 0.0
    run = 0
    for k in reversed(list(order_keys)):
        if k in removed:
            run += 1
        else:
            break
    return run, run / len(removed)


def breaker_marks(removed_pct, threshold_count):
    """熔斷事件的標記欄位（與 detect_delistings.breaker_marks() 同名同義同欄位）。
    note 沿用本檔案 2026-09-01 起就在用的既有值，不新造第二個名字；
    removed_pct 沿用既有欄位與既有的 round(...,4) 精度；
    breaker_tripped／breaker_threshold 為 2026-09-07 新增，breaker_threshold
    一律是**筆數**（本檔案本來就用筆數比較，detect_delistings 第一階段的百分比
    門檻會先換算成筆數，兩邊單位因此一致）。"""
    return {"note": "anomalous_scale", "breaker_tripped": True,
            "removed_pct": round(float(removed_pct), 4),
            "breaker_threshold": round(float(threshold_count), 4)}


def load_quarantine_seen():
    """讀隔離檔目前所有四元組鍵值，供 write_quarantine() 冪等判斷。
    手法與 main() 讀 events.jsonl 建 seen 集合完全相同。"""
    seen = set()
    if os.path.exists(QUARANTINE_JL):
        for line in open(QUARANTINE_JL, encoding="utf-8"):
            try:
                e = json.loads(line)
                seen.add((e["date"], e["exchange"], e["symbol"], e["event"]))
            except Exception:
                pass
    return seen


def write_quarantine(events, reason_code, reason_text, seen):
    """把「本來會寫進 events.jsonl、但這組轉換不可信」的事件完整寫進隔離檔。

    設計理由（與 detect_delistings.write_quarantine() 同一套）：
      1. **隔離不是丟棄**。舊行為（完整性守門觸發就 continue）會讓那一組轉換的
         LISTED／DELISTED／STATUS_CHANGED 全部消失且不會自動重放。
      2. 只追加、去重鍵與 events.jsonl 相同，重跑不會長出重複行（冪等）。
      3. 隔離檔不是 events.jsonl 的一部分：scripts/verify_prod.py 的冪等檢查
         只雜湊 track-crypto/data/*/events.jsonl，本檔案不在其列。
    """
    if not events:
        return []
    fresh = []
    for e in events:
        k = (e["date"], e["exchange"], e["symbol"], e["event"])
        if k in seen:
            continue
        rec = dict(e)
        rec["quarantine_reason"] = reason_code
        rec["quarantine_detail"] = reason_text
        fresh.append((k, rec))
    if not fresh:
        return []
    os.makedirs(os.path.dirname(QUARANTINE_JL), exist_ok=True)
    with open(QUARANTINE_JL, "a", encoding="utf-8") as f:
        for _k, rec in fresh:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    for k, _rec in fresh:
        seen.add(k)
    return [rec for _k, rec in fresh]


def write_alert_block_cexbreaker(exch, d_cur, lines):
    """寫入 ALERT-CEXBREAKER.md（本檔案獨佔的熔斷告警檔）。

    為什麼要有這個檔案：本檔案的熔斷從 2026-09-01 上線至今**沒有接任何告警管道**，
    只有 stdout 一行 [CB] 進 logs/cex_events.log。實測 events.jsonl 裡已經有 26 筆
    note:"anomalous_scale" 的事件，代表熔斷確實觸發過，但從來沒有人被通知。
    「標記但不否決」若沒有配套告警，等於把判斷責任丟給不存在的下游。

    為什麼不寫進既有檔案：ALERT.md 是 healthcheck.py 獨佔（每次執行整檔覆寫／刪除）；
    ALERT-DELIST.md 檔頭明文宣告「由 detect_delistings.py 獨佔寫入，不與任何其他
    程式共用」；ALERT-CEXGATE.md 是 healthcheck.py 的輸出且語意是「異常排除後自動
    消失」。三者都不能共用，比照既有前例另開獨立檔案。

    為什麼只對「最新一組轉換」寫入（呼叫端條件）：main() 每次執行都對**完整歷史**
    重新配對計算，若每一組歷史熔斷都寫一則，部署當下就會憑空生出多則歷史告警，
    而 scripts/push.sh 的死人開關是用「檔案存不存在」判斷的，等於部署即報 fail。
    歷史熔斷的永久紀錄本來就在 events.jsonl 的 breaker_tripped 欄位裡，不需要
    告警檔再存一份。這與 healthcheck.py 的 check_cex_gate_skips()「只看 date==TODAY」
    是同一個處理原則。

    冪等：用 HTML 註解 marker 判斷同一組 (exchange, date) 是否已寫過，只追加、
    永不刪除既有區塊（與 detect_delistings.write_alert_block() 相同）。
    """
    marker = "<!-- cex_events:%s:%s -->" % (exch, d_cur)
    existing = ""
    if os.path.exists(ALERT_CEXBREAKER):
        with open(ALERT_CEXBREAKER, encoding="utf-8") as f:
            existing = f.read()
    if marker in existing:
        return False
    block = "\n".join(
        ["", "## \U0001f534 cex_events／%s 上下架規模異常熔斷警報（%s）" % (exch, d_cur),
         "", marker, ""] + lines + [""])
    if existing.strip():
        content = existing.rstrip("\n") + "\n" + block
    else:
        header = """# 🔴 cex_events 上下架規模異常警報（熔斷）

本檔案由 `scripts/cex_events.py` 獨佔寫入，不與任何其他程式共用
（`ALERT.md` 是 `scripts/healthcheck.py` 的輸出、`ALERT-DELIST.md` 是
`track-crypto/scripts/detect_delistings.py` 的輸出、`ALERT-CEXGATE.md` 是
`scripts/healthcheck.py` 讀 `gate_skips.jsonl` 後的輸出，四者互不相干）。

本檔案記錄「某交易所單日 DELISTED 筆數超過熔斷門檻」這個事實。**熔斷不代表事件是假的**：
本程式對熔斷採「標記但不否決」——事件**已經照常寫入** `track-crypto/data/cex_events/events.jsonl`，
每一筆都帶 `note:"anomalous_scale"`、`breaker_tripped:true`、`removed_pct`、`breaker_threshold`
四個欄位。本檔案的用途是**要求人工複核**，不是宣告資料有錯。

本檔案只會新增，不會自動刪除既有區塊；只對「最新一組轉換」寫入（理由見
`scripts/cex_events.py` 的 `write_alert_block_cexbreaker()` docstring）。
人工確認後若需歸檔，請自行搬移或加註（例如在行尾加 `<!-- ack:YYYY-MM-DD -->`）。
"""
        content = header + block
    with open(ALERT_CEXBREAKER, "w", encoding="utf-8") as f:
        f.write(content)
    return True


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

    # 熔斷語意統一（2026-09-07）：隔離檔的既有鍵值（冪等用）、本次熔斷紀錄、
    # 以及「最新一組轉換」的日期（告警只對最新一組寫入，理由見
    # write_alert_block_cexbreaker() docstring）。
    q_seen = load_quarantine_seen()
    quarantined_total = 0
    breaker_trips = []
    latest_date = os.path.basename(files[-1])[:10]

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
                # 熔斷語意統一（2026-09-07）第 3 項：守門由「否決並丟棄」升級為
                # 「否決但隔離保存」。只有兩側都有解析出資料時才算得出有意義的差集
                # （某一側整個交易所缺席時，「全部消失」是純粹的抓取假象，寫進隔離檔
                # 只是噪音，維持原本只留 gate_skips 紀錄的作法）。
                if QUARANTINE_GATE_FAIL and exch in a and exch in b:
                    qa, qb = a[exch], b[exch]
                    q_events = []
                    for s in sorted(set(qb) - set(qa)):
                        q_events.append({"date": d_cur, "exchange": exch, "symbol": s,
                                          "event": "LISTED", "from": None, "to": qb[s]})
                    for s in sorted(set(qa) - set(qb)):
                        q_events.append({"date": d_cur, "exchange": exch, "symbol": s,
                                          "event": "DELISTED", "from": qa[s], "to": None})
                    for s in sorted(s for s in set(qa) & set(qb) if qa[s] != qb[s]):
                        q_events.append({"date": d_cur, "exchange": exch, "symbol": s,
                                          "event": "STATUS_CHANGED", "from": qa[s], "to": qb[s]})
                    q_fresh = write_quarantine(q_events, "GATE_FAIL", "；".join(reasons), q_seen)
                    quarantined_total += len(q_fresh)
                    if q_fresh:
                        print("   [QUARANTINE] %s @ %s→%s：%d 筆事件寫入 %s"
                              % (exch, d_prev, d_cur, len(q_fresh), QUARANTINE_JL))
                continue

            pa, pb = a[exch], b[exch]
            added = sorted(set(pb) - set(pa))
            removed = sorted(set(pa) - set(pb))
            changed = sorted(s for s in set(pa) & set(pb) if pa[s] != pb[s])

            # 熔斷語意統一（2026-09-07）：這一組轉換的事件先收集到 pair_events，
            # 熔斷標記在下面一次套用到整組（不再只標記 DELISTED），最後才 extend 進
            # new。既有的三段 append 內容逐字元不變，只是換了容器名稱。
            pair_events = []
            for s in added:
                pair_events.append({"date": d_cur, "exchange": exch, "symbol": s,
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
                pair_events.append(ev)

            for s in changed:
                pair_events.append({"date": d_cur, "exchange": exch, "symbol": s,
                            "event": "STATUS_CHANGED", "from": pa[s], "to": pb[s]})

            # 熔斷語意統一（2026-09-07）：標記是「這一組轉換整體異常」的性質，
            # 所以套用到整組（LISTED／DELISTED／STATUS_CHANGED），不只 DELISTED。
            # 上面 for s in removed 迴圈裡既有的兩行 note／removed_pct 指派刻意保留
            # 原樣（值與這裡算出來的完全相同，重複指派無副作用），是為了讓
            # scripts/selftest.py 的 mut_ce_anomaly 破壞驗證錨點與既有語意都不受影響。
            if anomalous:
                marks = breaker_marks(removed_pct, threshold)
                for ev in pair_events:
                    ev.update(marks)
                tail_run, tail_cov = removal_tail_metrics(pa, removed)
                breaker_trips.append({
                    "date": d_cur, "from_date": d_prev, "exchange": exch,
                    "n_prev": len(pa), "n_removed": len(removed), "n_added": len(added),
                    "n_changed": len(changed), "removed_pct": round(removed_pct, 4),
                    "threshold": round(threshold, 4),
                    "tail_run": tail_run, "tail_cover": round(tail_cov, 4),
                })
            new.extend(pair_events)

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

    # 熔斷語意統一（2026-09-07）：只對「最新一組轉換」的熔斷寫告警，
    # 理由見 write_alert_block_cexbreaker() docstring（避免部署當下憑空生出多則
    # 歷史告警，讓 scripts/push.sh 的死人開關立刻報 fail）。
    alerts_written = 0
    for t in breaker_trips:
        if t["date"] != latest_date:
            continue
        lines = [
            "檢查時間（UTC）：%s" % datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "",
            "| 項目 | 值 |",
            "|---|---|",
            "| 交易所 | `%s` |" % t["exchange"],
            "| 比對區間 | `%s` \u2192 `%s` |" % (t["from_date"], t["date"]),
            "| 前日筆數 | %d |" % t["n_prev"],
            "| 當日 DELISTED 筆數 | %d（%.2f%%） |" % (t["n_removed"], t["removed_pct"]),
            "| 熔斷門檻（筆數） | %.1f＝max(%d, %.1f%%\u00d7前日筆數) |"
            % (t["threshold"], CB_MIN_ABS, CB_PCT * 100),
            "| 同組 LISTED／STATUS_CHANGED | %d／%d |" % (t["n_added"], t["n_changed"]),
            "| 分頁截斷指紋 tail_cover | %.4f（參考值，門檻 %.2f；本來源不用它否決，"
            "見 BREAKER_TRUNCATION_QUARANTINE） |" % (t["tail_cover"], BREAKER_TAIL_COVER_MAX),
            "| 處置 | **標記但不否決**：事件已寫入 `track-crypto/data/cex_events/events.jsonl` |",
            "",
            ("本組轉換產生的每一筆事件（LISTED／DELISTED／STATUS_CHANGED）都已帶 "
             "`note:\"anomalous_scale\"`、`breaker_tripped:true`、`removed_pct`、"
             "`breaker_threshold` 四個欄位，**需要人工複核**。本程式不對成因下判斷"
             "（零觀點鐵律）：可能是抓取異常，也可能是真的有大量交易對同時下架。"
             "若複核後判定為假事件，請用 `scripts/apply_correction.py` 更正，"
             "不要手動編輯事件流。"),
        ]
        if write_alert_block_cexbreaker(t["exchange"], t["date"], lines):
            alerts_written += 1

    c = Counter((e["exchange"], e["event"]) for e in fresh)
    print("新增事件 %d 筆（累積檔 %s）" % (len(fresh), JL))
    for (exch, ev), n in sorted(c.items()):
        print("   %-8s %-15s %d" % (exch, ev, n))
    if fresh_gate_skips:
        print("完整性守門觸發 %d 次新紀錄（紀錄於 %s；本次重新計算共 %d 次，%d 次為既有歷史重複已跳過）"
              % (len(fresh_gate_skips), GATE_LOG, len(gate_skips), len(gate_skips) - len(fresh_gate_skips)))
    # 熔斷語意統一（2026-09-07）新增的一行 SUMMARY，格式與既有 EVENTS 那行同構，
    # 既有輸出逐字元未動（下游若有在 grep "EVENTS new=" 或「新增事件 %d 筆」不受影響）。
    print("BREAKER_SEMANTICS trips=%d trips_latest=%d alerts_written=%d quarantined=%d"
          % (len(breaker_trips), sum(1 for t in breaker_trips if t["date"] == latest_date),
             alerts_written, quarantined_total))
    print("EVENTS new=%d" % len(fresh))
    return 0

if __name__ == "__main__":
    sys.exit(main())
