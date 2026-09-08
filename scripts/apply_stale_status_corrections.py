#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apply_stale_status_corrections.py — 對 cex_currency_status 事件流裡「依現行規則
不該產生」的既有 STATUS_CHANGED 事件，補寫更正註記（**不刪除、不覆寫任何原始事件行**）。

任務：0908-1（docs/0908-1-renamed-event-report.md §7）
依據：docs/0907-E-gate-flap-report.md §9.2 待裁示第 1 項，使用者裁示「照建議（選項 b）」＝
      「用 scripts/apply_correction.py 另寫更正檔，不刪原行」。

背景
----
任務 E 於 2026-09-07 上線了語意過濾規則
（GROUP_SOURCES["cex_currency_status"]["groups"]["gate"]["status_filters"]）：
Gate 交易所某個幣種若**新舊兩側的 delisted 皆為 True**，其 withdraw_disabled 的變化
不再產生 STATUS_CHANGED 事件（改記進 track-crypto/data/_status_filter/suppressed.jsonl）。

但規則上線**之前**已經產生並公開的事件仍然留在 events.jsonl 裡。本工具替這些存量事件
補一份更正註記，讓事件流自我更正，同時完整保留歷史保真度。

為什麼 verdict 是 superseded_by_rule 而不是 false_event
------------------------------------------------------
這些事件**不是假的**：Gate 當時確實回報了 withdraw_disabled 的變化，快照可以逐筆複核。
改變的是我方的**發布規則**，不是事實。把 251 筆真實觀測標成「假事件」會違反本專案
「只陳述事實」的立場，因此本輪在 scripts/apply_correction.py 新增第三種 verdict。

安全性
------
本腳本**自己不寫任何檔案**，只是逐批呼叫 scripts/apply_correction.py（該工具全程唯讀
events.jsonl、只用附加模式寫 events-corrections.jsonl、結束時用 sha256 自我證明）。
本腳本另外在頭尾各取一次 events.jsonl 的 sha256 做第二層獨立驗證。

冪等
----
執行前先讀既有的 events-corrections.jsonl，**已經被本腳本寫過的批次會被跳過**
（以 corrected_by + reason_code + 完全相同的 targets 集合判定）。
因此重複執行、或中途失敗後重跑，都不會產生重複紀錄。

用法
----
  # 先看會做什麼（不寫任何檔案）
  python3 scripts/apply_stale_status_corrections.py --repo . --dry-run

  # 真的執行
  python3 scripts/apply_stale_status_corrections.py --repo .

  # 改成一筆事件一筆更正紀錄（預設是同一天的合成一筆，比照既有 C0001 的慣例）
  python3 scripts/apply_stale_status_corrections.py --repo . --group-by event
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys

CORRECTED_BY = "0908-1-gate-stale-status"
REASON_CODE = "SUPERSEDED_BY_STATUS_FILTER"
AUDIT_REF = ("docs/0907-E-gate-flap-report.md §9.2 待裁示第 1 項 ／ "
             "docs/0908-1-renamed-event-report.md §7")
VERDICT = "superseded_by_rule"
KEY_FIELDS = "date,source,group,key,event"
STREAM_LABEL = "cex_currency_status"
EVIDENCE_TMPL = (
    "任務 E 的語意過濾規則（GROUP_SOURCES['cex_currency_status']['groups']['gate']"
    "['status_filters']：withdraw_disabled 的變化在新舊兩側 delisted 皆為 True 時不發布）"
    "於 2026-09-07 上線。本批 {n} 筆事件產生於規則上線之前，逐筆回快照複核確認"
    "**符合該規則的抑制條件**（{date} 對照前一日快照，delisted 兩側皆 True），"
    "依現行規則不會被產生。事實本身為真（Gate 當時確實回報了該欄位變化，"
    "見 track-crypto/data/cex_currency_status/{date}.json.gz），"
    "因此不判定為假事件，只註記為「依現行規則不再發布」。原始事件行一行都沒有刪改。"
)


def sha256_of(path):
    if not os.path.exists(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_jsonl(path):
    rows = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def target_sig(targets):
    """一批 targets 的順序無關指紋，供冪等判斷。"""
    return tuple(sorted(json.dumps(t, ensure_ascii=False, sort_keys=True) for t in targets))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="repo 根目錄（正式目錄或沙盒副本）")
    ap.add_argument("--keys", default=None,
                    help="鍵值清單 JSON（預設取本腳本同目錄的 stale-status-changed-keys.json）")
    ap.add_argument("--group-by", default="date", choices=["date", "event", "all"],
                    help="每筆更正紀錄涵蓋多少事件：date=同一天合成一筆（預設，比照既有 C0001 慣例）；"
                         "event=一筆事件一筆紀錄；all=全部合成一筆")
    ap.add_argument("--dry-run", action="store_true", help="只印出會做什麼，不寫任何檔案")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    keys_path = args.keys or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          "stale-status-changed-keys.json")
    tool = os.path.join(repo, "scripts", "apply_correction.py")
    events = os.path.join(repo, "track-crypto", "data", "cex_currency_status", "events.jsonl")
    out_jsonl = os.path.join(repo, "track-crypto", "data", "cex_currency_status",
                             "events-corrections.jsonl")
    out_md = os.path.join(repo, "track-crypto", "data", "cex_currency_status",
                          "events-corrections.md")
    for p in (tool, events, keys_path):
        if not os.path.exists(p):
            print("錯誤：找不到 %s" % p, file=sys.stderr)
            return 2

    spec = json.load(open(keys_path, encoding="utf-8"))
    targets_all = [{k: t[k] for k in ("date", "source", "group", "key", "event")}
                   for t in spec["targets"]]
    print("鍵值清單：%s" % keys_path)
    print("  來源 events.jsonl  ：%s" % spec.get("events_jsonl_path"))
    print("  清單產生時 sha256  ：%s" % spec.get("events_jsonl_sha256"))
    print("  清單筆數           ：%d" % len(targets_all))

    before = sha256_of(events)
    print("  現況 events.jsonl  ：%s（%d 行）"
          % (before, sum(1 for _ in open(events, encoding="utf-8"))))
    if spec.get("events_jsonl_sha256") and spec["events_jsonl_sha256"] != before:
        print("  ⚠️ 注意：events.jsonl 的 sha256 與清單產生時不同（排程又追加了新事件）。")
        print("     這不影響正確性——apply_correction.py 會逐筆確認每個 target 真的存在；")
        print("     但若有**新**的存量事件也該更正，請重新產生鍵值清單。")

    # 分批
    if args.group_by == "date":
        buckets = {}
        for t in targets_all:
            buckets.setdefault(t["date"], []).append(t)
        batches = [(d, buckets[d]) for d in sorted(buckets)]
    elif args.group_by == "event":
        batches = [("%s/%s" % (t["date"], t["key"]), [t]) for t in targets_all]
    else:
        batches = [("all", targets_all)]

    existing = load_jsonl(out_jsonl)
    done = {target_sig(r["targets"]) for r in existing
            if r.get("corrected_by") == CORRECTED_BY and r.get("reason_code") == REASON_CODE}
    print("  既有更正紀錄       ：%d 筆（其中本任務已寫過 %d 批）" % (len(existing), len(done)))
    print("  分批方式           ：--group-by %s -> %d 批" % (args.group_by, len(batches)))
    print("")

    applied = skipped = 0
    for label, targets in batches:
        if target_sig(targets) in done:
            print("SKIP  %-12s %3d 筆（已存在相同批次，冪等跳過）" % (label, len(targets)))
            skipped += 1
            continue
        date_for_evidence = targets[0]["date"] if len({t["date"] for t in targets}) == 1 else "多日"
        cmd = [sys.executable, tool,
               "--events", events, "--out-jsonl", out_jsonl, "--out-md", out_md,
               "--key-fields", KEY_FIELDS, "--stream-label", STREAM_LABEL,
               "--verdict", VERDICT, "--reason-code", REASON_CODE,
               "--evidence", EVIDENCE_TMPL.format(n=len(targets), date=date_for_evidence),
               "--audit-ref", AUDIT_REF, "--corrected-by", CORRECTED_BY]
        for t in targets:
            cmd += ["--target", json.dumps(t, ensure_ascii=False)]
        if args.dry_run:
            print("DRY   %-12s %3d 筆（argv %d 項，未執行）" % (label, len(targets), len(cmd)))
            applied += 1
            continue
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print("FAIL  %-12s %3d 筆" % (label, len(targets)))
            print(r.stdout)
            print(r.stderr, file=sys.stderr)
            return 1
        cid = ""
        for ln in r.stdout.split("\n"):
            if ln.startswith("新增更正紀錄 "):
                cid = ln.split()[1].rstrip("：")
        print("OK    %-12s %3d 筆  -> %s" % (label, len(targets), cid))
        applied += 1

    after = sha256_of(events)
    print("")
    print("批次：套用 %d、冪等跳過 %d" % (applied, skipped))
    print("events.jsonl sha256 執行前 = %s" % before)
    print("events.jsonl sha256 執行後 = %s" % after)
    ok = (before == after)
    print("events.jsonl 是否未被更動：%s" % ("是" if ok else "否！！"))
    if not args.dry_run:
        rows = load_jsonl(out_jsonl)
        n_t = sum(len(r["targets"]) for r in rows if r.get("corrected_by") == CORRECTED_BY)
        print("events-corrections.jsonl 共 %d 筆紀錄，其中本任務涵蓋 %d 個事件" % (len(rows), n_t))
        ok = ok and (n_t == len(targets_all))
        print("涵蓋數是否等於清單筆數（%d）：%s" % (len(targets_all), "是" if n_t == len(targets_all) else "否！！"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
