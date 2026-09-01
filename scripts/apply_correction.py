#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apply_correction.py — 「更正註記」機制原型（設計與理由見 docs/cex-events-audit.md §5）

目的：對 events.jsonl 裡「已經公開」的一或多筆事件，事後補上更正判定，
      不刪除、不覆寫原始那幾行——只在旁邊「追加」一筆結構化紀錄到 events-corrections.jsonl，
      並把 events-corrections.md（人類可讀版）整份從 jsonl 重新算出來。

為什麼不直接在 events.jsonl 裡加一種新的 event 類型（例如 "CORRECTED"）：
  見 docs/cex-events-audit.md §5.1 的完整理由，摘要三點：
  1. events.jsonl 的 schema（event ∈ {LISTED,DELISTED,STATUS_CHANGED}）已公開在 CC BY 4.0 的
     repo 裡，可能已有外部消費者依賴這個封閉集合；憑空加第 4 種事件类型等於是「沒有預告」地
     改變一個已發布的公開介面。
  2. cex_events.py 檔頭明講「本工具只記錄事實，不做任何解讀或建議」；而「更正判定」本質上是
     人／稽核流程的判斷，跟「這一刻資料源真的回傳了什麼」是不同的認知類別，混在同一個檔案裡
     會讓「事實串流」與「事後判斷」的界線變模糊。
  3. 本專案已有先例：anomalous_scale 這個標記是用「附加、可選欄位」而非「新的 event 值」做的
     （見 cex_events.py 本身），代表「用附加檔案/附加欄位做標註、不動核心 schema」是這個
     專案一貫的設計偏好。

安全機制（避免更正機制本身變成新的資料破壞來源）：
  - 每個 --target 都會先在 events.jsonl 逐行比對 (date,exchange,symbol,event) 是否真的存在，
    不存在就直接報錯中止（防止更正一個根本不存在的事件、或打錯字卻默默通過）。
  - 全程只用「唯讀開檔」讀 events.jsonl、只用「附加模式」開 events-corrections.jsonl；
    程式碼裡完全沒有任何會截斷或覆寫 events.jsonl 的呼叫。
  - 執行前後主動用 sha256 比對 events.jsonl，證明真的沒被動到（見 main() 結尾輸出）。
  - events-corrections.md 每次執行都整份重新從 events-corrections.jsonl 重新算出來，
    不是手動維護的自由格式文字——避免「md 講的」跟「jsonl 記的」兩份長期漂移不一致。

correction 紀錄 schema（每行一個 JSON object）：
  {
    "correction_id":  "C0001",                          # 流水號，本檔內唯一
    "corrected_at":   "2026-09-01T12:00:00+00:00",        # 這次更正動作發生的時間（不是原事件時間）
    "targets": [                                          # 指回一或多筆原始事件，逐筆精確比對四個鍵值
      {"date": "...", "exchange": "...", "symbol": "...", "event": "DELISTED"}
    ],
    "verdict":        "false_event",                      # false_event｜confirmed_true 二選一
    "reason_code":    "SAME_DAY_RERUN_ARTIFACT",           # 簡短分類代碼，供程式化篩選
    "evidence":       "一句話講清楚依據，通常引用稽核報告裡的依據代碼",
    "audit_ref":      "docs/cex-events-audit.md#xxx",      # 對應完整稽核報告位置，可查完整脈絡
    "corrected_by":   "cex-events-audit-2026-09-01"        # 這次稽核／更正流程的識別
  }

用法：
  python3 apply_correction.py \
    --events events.jsonl --out-jsonl events-corrections.jsonl --out-md events-corrections.md \
    --target '{"date":"2026-08-30","exchange":"mexc","symbol":"XXX","event":"DELISTED"}' \
    --verdict false_event --reason-code DEMO --evidence "..." \
    --audit-ref "docs/cex-events-audit.md#demo" --corrected-by "demo"
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone


def sha256_of(path):
    if not os.path.exists(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_events_keys(events_path):
    """回傳 events.jsonl 裡所有 (date,exchange,symbol,event) 鍵值的集合，供存在性檢查。"""
    keys = set()
    with open(events_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            keys.add((e["date"], e["exchange"], e["symbol"], e["event"]))
    return keys


def load_corrections(jsonl_path):
    rows = []
    if os.path.exists(jsonl_path):
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def render_md(rows, events_path):
    lines = []
    lines.append("# events-corrections — cex_events 更正註記（人類可讀版，自動產生）")
    lines.append("")
    lines.append("> 本檔由 `events-corrections.jsonl` 自動重新算出，請勿手動編輯本檔；")
    lines.append("> 要新增/查詢更正，請改 `events-corrections.jsonl` 或用 `apply_correction.py`。")
    lines.append(f"> 對應的原始事實串流：`{os.path.basename(events_path)}`（本機制絕不刪除、絕不覆寫該檔）。")
    lines.append("")
    if not rows:
        lines.append("（目前沒有任何更正紀錄——代表尚未有稽核判定任何已公開事件為假事件。）")
        lines.append("")
        return "\n".join(lines)
    lines.append(f"共 {len(rows)} 筆更正紀錄。")
    lines.append("")
    lines.append("| # | 更正時間 | 判定 | 指向的原始事件 | 原因代碼 | 依據 | 稽核報告 |")
    lines.append("|---|---|---|---|---|---|---|")
    for i, r in enumerate(rows, 1):
        targets = "; ".join(
            f"{t['date']} {t['exchange']} {t['symbol']} {t['event']}" for t in r["targets"]
        )
        verdict_zh = {"false_event": "**判定為假事件**", "confirmed_true": "複核後仍確認為真"}.get(
            r["verdict"], r["verdict"]
        )
        lines.append(
            f"| {i} | {r['corrected_at']} | {verdict_zh} | {targets} | "
            f"{r['reason_code']} | {r['evidence']} | {r['audit_ref']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", required=True, help="events.jsonl 路徑（全程唯讀）")
    ap.add_argument("--out-jsonl", required=True, help="events-corrections.jsonl 路徑（附加）")
    ap.add_argument("--out-md", required=True, help="events-corrections.md 路徑（整份重算重寫）")
    ap.add_argument("--target", action="append", required=True,
                     help="JSON 字串，可重複給多次，指向一或多筆原始事件")
    ap.add_argument("--verdict", required=True, choices=["false_event", "confirmed_true"])
    ap.add_argument("--reason-code", required=True)
    ap.add_argument("--evidence", required=True)
    ap.add_argument("--audit-ref", required=True)
    ap.add_argument("--corrected-by", required=True)
    args = ap.parse_args()

    before_hash = sha256_of(args.events)

    valid_keys = load_events_keys(args.events)
    targets = [json.loads(t) for t in args.target]
    for t in targets:
        key = (t["date"], t["exchange"], t["symbol"], t["event"])
        if key not in valid_keys:
            print("錯誤：--target %r 在 %s 裡找不到對應的原始事件，中止（不寫入任何檔案）"
                  % (t, args.events), file=sys.stderr)
            return 1

    existing = load_corrections(args.out_jsonl)
    correction_id = "C%04d" % (len(existing) + 1)
    record = {
        "correction_id": correction_id,
        "corrected_at": datetime.now(timezone.utc).isoformat(),
        "targets": targets,
        "verdict": args.verdict,
        "reason_code": args.reason_code,
        "evidence": args.evidence,
        "audit_ref": args.audit_ref,
        "corrected_by": args.corrected_by,
    }

    # 只用附加模式寫 jsonl；events.jsonl 全程沒有任何開檔動作寫入
    with open(args.out_jsonl, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    all_rows = load_corrections(args.out_jsonl)
    md = render_md(all_rows, args.events)
    with open(args.out_md, "w", encoding="utf-8") as f:
        f.write(md)

    after_hash = sha256_of(args.events)
    print("新增更正紀錄 %s：%s" % (correction_id, json.dumps(record, ensure_ascii=False)))
    print("events-corrections.jsonl 現有 %d 筆" % len(all_rows))
    print("events.jsonl sha256 執行前 = %s" % before_hash)
    print("events.jsonl sha256 執行後 = %s" % after_hash)
    print("events.jsonl 是否未被更動：%s" % ("是" if before_hash == after_hash else "否！！"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
