#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apply_correction.py — 「更正註記」機制原型（設計與理由見 docs/cex-events-audit.md §5）

目的：對 events.jsonl 裡「已經公開」的一或多筆事件，事後補上更正判定，
      不刪除、不覆寫原始那幾行——只在旁邊「追加」一筆結構化紀錄到 events-corrections.jsonl，
      並把 events-corrections.md（人類可讀版）整份從 jsonl 重新算出來。

為什麼不直接在 events.jsonl 裡加一種新的 event 類型（例如 "CORRECTED"）：
  見 docs/cex-events-audit.md §5.1 的完整理由，摘要三點：
  1. events.jsonl 的 event 欄位是**已公開在 CC BY 4.0 repo 的封閉集合**
     （cex_events 流：{LISTED, DELISTED, STATUS_CHANGED}；track-crypto 逐來源流：
     {LISTED, DELISTED, REAPPEARED, STATUS_CHANGED, RENAMED}），可能已有外部消費者
     依賴它；**未經預告**地新增事件型別，等於是「沒有預告」地改變一個已發布的公開介面。

     ⚠️ 注意本條反對的是「未經預告」，不是「永遠不得新增」。本專案已經有過兩次
     經裁示後新增型別的先例（REAPPEARED、STATUS_CHANGED），2026-09-08 又新增了
     RENAMED（第 5 種，只作用於 track-crypto 逐來源流）。新增型別的既定程序是：
     (a) 由使用者／父代理明確裁示；(b) 舊型別的語意、欄位、產生條件一律不變，
     既有事件行一行都不刪改（只增不減）；(c) 在 docs/operations.md 的
     「型別集合變更史」表留下公告紀錄。**更正判定仍然不走這條路**——理由是下面
     第 2、3 點（認知類別不同、本專案偏好附加檔案），與型別數量無關。
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
    "verdict":        "false_event",                      # false_event｜confirmed_true｜superseded_by_rule
                                                          #   false_event        判定為假事件（資料源根本沒有發生這件事，
                                                          #                      或是我方程式的判定瑕疵造出來的）
                                                          #   confirmed_true     複核後仍確認為真（不更正，只留下複核紀錄）
                                                          #   superseded_by_rule 事實為真（資料源確實回報了這個變化），
                                                          #                      但依**後來才上線的**發布規則，這一筆已不再
                                                          #                      屬於會被發布的事件。2026-09-08 新增，用於
                                                          #                      任務 E 語意過濾上線前既已產生的存量事件。
                                                          #                      刻意不用 false_event：那會把「上游真的回報過
                                                          #                      的觀測」誤記成「沒發生過」，違反本專案
                                                          #                      「只陳述事實」的立場。
    "reason_code":    "SAME_DAY_RERUN_ARTIFACT",           # 簡短分類代碼，供程式化篩選
    "evidence":       "一句話講清楚依據，通常引用稽核報告裡的依據代碼",
    "audit_ref":      "docs/cex-events-audit.md#xxx",      # 對應完整稽核報告位置，可查完整脈絡
    "corrected_by":   "cex-events-audit-2026-09-01"        # 這次稽核／更正流程的識別
  }

用法（cex_events，既有用法完全不變）：
  python3 apply_correction.py \
    --events events.jsonl --out-jsonl events-corrections.jsonl --out-md events-corrections.md \
    --target '{"date":"2026-08-30","exchange":"mexc","symbol":"XXX","event":"DELISTED"}' \
    --verdict false_event --reason-code DEMO --evidence "..." \
    --audit-ref "docs/cex-events-audit.md#demo" --corrected-by "demo"

2026-09-07 新增（任務 B，docs/0907-B-rename-key-report.md §6）：支援 cex_events 以外的事件流
------------------------------------------------------------------------------------
  問題：本工具原本把主鍵欄位寫死成 (date, exchange, symbol, event)，那是
  scripts/cex_events.py 產生的 events.jsonl 的 schema。track-crypto 的
  track-crypto/data/<source>/events.jsonl 是另一種 schema
  (date, source, group, key, event)，直接餵給本工具會在 load_events_keys()
  丟 KeyError: 'exchange'（實測輸出見報告 §6.1），完全無法使用——也就是說
  「更正註記」機制在本次修正之前只涵蓋 cex_events 一種事件流。

  修法（純加法，不改既有預設行為）：新增兩個有預設值的參數
    --key-fields   逗號分隔的主鍵欄位名稱，預設 "date,exchange,symbol,event"
                   （＝既有行為，cex_events 呼叫端一個字都不必改）
    --stream-label 產生的 markdown 標題裡的事件流名稱，預設 "cex_events"
                   （＝既有行為）
  events.jsonl 仍然全程唯讀、仍然只用附加模式寫 corrections、仍然在結束時
  用 sha256 前後比對證明沒被動到——這三個安全機制一個字都沒有放寬。

  track-crypto 用法範例：
  python3 apply_correction.py \
    --events track-crypto/data/crypto_project_liveness/events.jsonl \
    --out-jsonl track-crypto/data/crypto_project_liveness/events-corrections.jsonl \
    --out-md track-crypto/data/crypto_project_liveness/events-corrections.md \
    --key-fields date,source,group,key,event --stream-label crypto_project_liveness \
    --target '{"date":"2026-09-06","source":"crypto_project_liveness","group":"_hacks","key":"stake dao\u001f1773273600","event":"DELISTED"}' \
    --verdict false_event --reason-code UPSTREAM_RENAME --evidence "..." \
    --audit-ref "docs/0907-events-audit-0904-0907.md#55" --corrected-by "rename-key-0907"
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


DEFAULT_KEY_FIELDS = ("date", "exchange", "symbol", "event")


def load_events_keys(events_path, key_fields=DEFAULT_KEY_FIELDS):
    """回傳 events.jsonl 裡所有主鍵欄位組合的集合，供存在性檢查。

    key_fields 預設 (date,exchange,symbol,event)＝cex_events 的 schema（既有行為）。
    仍然用 e[欄位] 直接索引而不是 e.get()：事件流是同質的（同一份檔案裡每一行都是
    同一個 schema），欄位名稱給錯時**必須立刻炸開**，不能默默把每一行都算成
    「鍵值裡有 None」然後在後面回報「找不到這筆事件」——那會把「參數打錯」
    誤導成「事件不存在」。"""
    keys = set()
    with open(events_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            keys.add(tuple(e[f] for f in key_fields))
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


def render_target_text(t):
    """把一筆 target dict 轉成人類可讀字串。

    向後相容：欄位剛好是 cex_events 那四個時，維持既有的固定順序輸出
    （"日期 交易所 幣種 事件"），與本次修改之前逐字元相同；其餘 schema
    一律用 "欄位=值" 逐項列出（依 target dict 自身的欄位順序），
    不假設任何特定欄位存在。"""
    if set(t) == set(DEFAULT_KEY_FIELDS):
        return f"{t['date']} {t['exchange']} {t['symbol']} {t['event']}"
    return " ".join(f"{k}={t[k]!r}" for k in t)


def render_md(rows, events_path, stream_label="cex_events"):
    lines = []
    lines.append(f"# events-corrections — {stream_label} 更正註記（人類可讀版，自動產生）")
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
        targets = "; ".join(render_target_text(t) for t in r["targets"])
        verdict_zh = {"false_event": "**判定為假事件**", "confirmed_true": "複核後仍確認為真",
                      "superseded_by_rule": "**依現行規則不再發布**（事實為真）"}.get(
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
    ap.add_argument("--verdict", required=True,
                     choices=["false_event", "confirmed_true", "superseded_by_rule"])
    ap.add_argument("--reason-code", required=True)
    ap.add_argument("--evidence", required=True)
    ap.add_argument("--audit-ref", required=True)
    ap.add_argument("--corrected-by", required=True)
    ap.add_argument("--key-fields", default=",".join(DEFAULT_KEY_FIELDS),
                     help="逗號分隔的主鍵欄位名稱（預設 %(default)s＝cex_events schema；"
                          "track-crypto 事件流請用 date,source,group,key,event）")
    ap.add_argument("--stream-label", default="cex_events",
                     help="產生的 markdown 標題裡的事件流名稱（預設 %(default)s）")
    args = ap.parse_args()
    key_fields = tuple(x.strip() for x in args.key_fields.split(",") if x.strip())
    if not key_fields:
        print("錯誤：--key-fields 不可為空", file=sys.stderr)
        return 1

    before_hash = sha256_of(args.events)

    valid_keys = load_events_keys(args.events, key_fields)
    targets = [json.loads(t) for t in args.target]
    for t in targets:
        missing = [f for f in key_fields if f not in t]
        if missing:
            print("錯誤：--target %r 缺少主鍵欄位 %r，中止（不寫入任何檔案）"
                  % (t, missing), file=sys.stderr)
            return 1
        key = tuple(t[f] for f in key_fields)
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
    md = render_md(all_rows, args.events, args.stream_label)
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
