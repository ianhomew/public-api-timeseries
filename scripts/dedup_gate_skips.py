#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/dedup_gate_skips.py — 通用一次性去重／歸檔工具（SPEC-gate-dedup.md 任務 1）

背景：
  cex_events.py 的 track-crypto/data/cex_events/gate_skips.jsonl、
  track-crypto/scripts/detect_delistings.py 的 track-crypto/data/_gate_fail/gate_skips.jsonl
  兩份「完整性守門」事實紀錄檔，寫入端本輪都已改成「去重後才附加」（見兩支程式
  main()/record_gate_fail() 內的 gate_seen／既有鍵值檢查邏輯，本工具與寫入端各自獨立，
  互不依賴），能防止**往後**再產生新的重複行。但若某份檔案在本次修復**之前**就已經
  累積過重複行，寫入端的「防未來」機制不會回頭清理**既有**的重複——這正是本工具要做的：
  一次性掃過整份檔案，同一個去重鍵只保留**最早出現**（檔案是附加寫入，行序＝時間序，
  「最早出現」＝「檔案裡第一次出現的那一行」，沒有另外的時間戳欄位可用，設計理由見
  本機 docs/gate-dedup-report.md「設計理由」一節）。

安全機制（比照 scripts/apply_correction.py 的既有慣例）：
  - 預設 dry-run：只印統計，不動檔案。真的要寫檔必須明確加 --apply。
  - --apply 動檔前，先把原始檔案完整複製一份成 <file>.bak-<UTC時間戳>（額外的實體備份，
    即使本工具本身邏輯有誤，原始資料仍有第二份副本可還原，不只是「相信程式碼寫對了」）。
  - 寫檔用「寫到同目錄暫存檔 + os.replace()」的原子替換手法，不會有「寫到一半被中斷、
    檔案處於半寫入狀態」的中繼風險。
  - 不刪除任何一筆**邏輯上獨特**的歷史紀錄：重複行的定義是「去重鍵完全相同」，
    被丟棄的行在內容上與保留的那一行等價（無法解析的行一律原樣保留，不視為可安全丟棄
    的重複，即使它出現多次——寧可多留、不可誤刪，見下方 --key 解析失敗處理）。
  - 執行前後印 sha256，供人工核對「動了什麼」。

--archive-before（可選，SPEC「按年份輪替」選項的手動版本，理由見設計文件）：
  把去重後日期早於指定日期的紀錄，搬到 <file 去副檔名>-archive-before-<cutoff>.jsonl，
  熱檔只留 >= cutoff 的紀錄。歸檔檔案本身也會先讀出既有鍵值，避免多次執行造成
  歸檔檔案內部重複。

用法：
  # 先看看有多少重複、會怎麼處理（不動檔案）：
  python3 scripts/dedup_gate_skips.py --file track-crypto/data/cex_events/gate_skips.jsonl \
      --key date,exchange,reason

  # 確認後真的套用：
  python3 scripts/dedup_gate_skips.py --file track-crypto/data/cex_events/gate_skips.jsonl \
      --key date,exchange,reason --apply

  # 同時把 2026 年之前的紀錄搬去歸檔檔案：
  python3 scripts/dedup_gate_skips.py --file track-crypto/data/cex_events/gate_skips.jsonl \
      --key date,exchange,reason --apply --archive-before 2027-01-01

  # detect_delistings.py 的 GATE_FAIL 事實紀錄（本輪新增，鍵值多一個 group 欄位）：
  python3 scripts/dedup_gate_skips.py --file track-crypto/data/_gate_fail/gate_skips.jsonl \
      --key date,source,group,reason --apply
"""
import argparse
import hashlib
import json
import os
import shutil
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


def load_lines(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [line.rstrip("\n") for line in f if line.strip()]


def key_of(line, fields):
    """回傳 (ok, key)。ok=False 代表這行無法解析（JSON 壞掉或缺欄位）——
    這種行永遠視為「獨特」，不參與去重比對，只保留、不丟棄（見檔頭安全機制說明）。"""
    try:
        obj = json.loads(line)
    except Exception:
        return False, None
    if not isinstance(obj, dict):
        return False, None
    key = tuple(obj.get(f) for f in fields)
    if any(v is None for v in key):
        return False, None
    return True, key


def dedup_lines(lines, fields):
    """回傳 (kept_lines, dropped_count, distinct_keys)。保留每個鍵值第一次出現的那一行，
    行序（＝原始附加順序＝時間序）完全不變。"""
    seen = set()
    kept = []
    dropped = 0
    for line in lines:
        ok, key = key_of(line, fields)
        if not ok:
            kept.append(line)  # 無法解析／缺鍵欄位：一律保留，不參與去重
            continue
        if key in seen:
            dropped += 1
            continue
        seen.add(key)
        kept.append(line)
    return kept, dropped, len(seen)


def split_archive(lines, fields, cutoff):
    """回傳 (hot_lines, archive_lines)：date 欄位 < cutoff 的進 archive，其餘留在 hot。
    無法解析或沒有 date 欄位的行一律留在 hot（不歸檔不明資料，避免誤搬）。"""
    hot, archive = [], []
    for line in lines:
        try:
            obj = json.loads(line)
        except Exception:
            hot.append(line)
            continue
        d = obj.get("date") if isinstance(obj, dict) else None
        if d and isinstance(d, str) and d < cutoff:
            archive.append(line)
        else:
            hot.append(line)
    return hot, archive


def atomic_write_lines(path, lines):
    tmp = path + ".tmp-%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", required=True, help="目標 .jsonl 檔案路徑")
    ap.add_argument("--key", required=True, help="去重鍵欄位，逗號分隔，例如 date,exchange,reason")
    ap.add_argument("--apply", action="store_true", help="真的寫檔（預設 dry-run，只印統計）")
    ap.add_argument("--archive-before", metavar="YYYY-MM-DD", default=None,
                     help="可選：把去重後 date < 此日期的紀錄搬到 <file>-archive-before-<cutoff>.jsonl")
    args = ap.parse_args()

    fields = [f.strip() for f in args.key.split(",") if f.strip()]
    if not fields:
        print("FATAL --key 不可為空", file=sys.stderr)
        return 1

    path = args.file
    if not os.path.exists(path):
        print("檔案不存在：%s（沒有需要處理的內容，屬正常情況——例如守門從未觸發過）" % path)
        return 0

    before_sha = sha256_of(path)
    lines = load_lines(path)
    kept, dropped, distinct = dedup_lines(lines, fields)

    print("=" * 70)
    print("檔案：%s" % path)
    print("去重鍵：%s" % (fields,))
    print("原始行數：%d" % len(lines))
    print("去重後行數：%d（distinct keys=%d）" % (len(kept), distinct))
    print("被判定為重複而移除的行數：%d" % dropped)
    print("執行前 sha256：%s" % before_sha)

    archive_lines = []
    if args.archive_before:
        kept, archive_lines = split_archive(kept, fields, args.archive_before)
        print("--archive-before %s：熱檔留 %d 行，歸檔 %d 行" %
              (args.archive_before, len(kept), len(archive_lines)))

    if not args.apply:
        print("dry-run（未加 --apply）：檔案未變動。")
        print("=" * 70)
        return 0

    if dropped == 0 and not archive_lines:
        print("沒有重複行、也沒有要歸檔的內容，檔案不需要變動，略過寫入。")
        print("=" * 70)
        return 0

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = "%s.bak-%s" % (path, ts)
    shutil.copyfile(path, backup_path)
    print("已備份原始檔案：%s" % backup_path)

    atomic_write_lines(path, kept)
    after_sha = sha256_of(path)
    print("已套用去重（附加模式覆蓋為去重後內容，行內容/順序不變，只移除重複行）。")
    print("執行後 sha256：%s" % after_sha)

    if archive_lines:
        archive_path = "%s-archive-before-%s.jsonl" % (
            path[:-6] if path.endswith(".jsonl") else path, args.archive_before)
        existing_archive = load_lines(archive_path)
        existing_keys = set()
        for line in existing_archive:
            ok, key = key_of(line, fields)
            if ok:
                existing_keys.add(key)
        new_archive_lines = []
        for line in archive_lines:
            ok, key = key_of(line, fields)
            if ok and key in existing_keys:
                continue
            if ok:
                existing_keys.add(key)
            new_archive_lines.append(line)
        with open(archive_path, "a", encoding="utf-8") as f:
            for line in new_archive_lines:
                f.write(line + "\n")
        print("已附加 %d 行到歸檔檔案：%s（%d 行因與既有歸檔內容鍵值重複而跳過）"
              % (len(new_archive_lines), archive_path, len(archive_lines) - len(new_archive_lines)))

    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
