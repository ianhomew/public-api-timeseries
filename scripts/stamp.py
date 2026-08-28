#!/usr/bin/env python3
"""stamp.py — 對每日資料清單蓋 OpenTimestamps 時間戳

目的：檔名、mtime、fetched_at、git commit date 全部可偽造。
OTS 把清單的 sha256 寫入 Bitcoin，任何人都能獨立驗證「這份資料在該時間點已存在」。

流程：
  1. 掃描所有 data/**/*.json.gz，產生 SHA256SUMS（path + sha256）
  2. ots stamp SHA256SUMS -> SHA256SUMS.ots
  3. 兩個檔案都 commit 進 repo

驗證方式（任何人）：
  ots verify SHA256SUMS.ots      # 需等 Bitcoin 確認，約數小時
  sha256sum -c SHA256SUMS         # 驗證檔案未被竄改
"""
import os, sys, time, hashlib, glob, subprocess
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OTS = os.path.expanduser("~/snap/.venv-ots/bin/ots")
STAMPDIR = os.path.join(REPO, "timestamps")

def sha256_of(path, buf=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(buf)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def main():
    files = sorted(glob.glob(os.path.join(REPO, "track-*/data/*/*.json.gz")))
    if not files:
        print("無資料檔，略過")
        return 0
    os.makedirs(STAMPDIR, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sums = os.path.join(STAMPDIR, "SHA256SUMS-%s.txt" % today)

    lines = ["# public-api-timeseries 資料完整性清單",
             "# 產生時間 (UTC): %s" % datetime.now(timezone.utc).isoformat(),
             "# 檔案數: %d" % len(files),
             "# 驗證: sha256sum -c 此檔；時間證明: ots verify <此檔>.ots",
             ""]
    for f in files:
        rel = os.path.relpath(f, REPO)
        lines.append("%s  %s" % (sha256_of(f), rel))
    body = "\n".join(lines) + "\n"

    # 內容未變則不重複蓋章（避免每天產生相同清單的冗餘 .ots）
    if os.path.exists(sums) and open(sums, encoding="utf-8").read().split("\n", 3)[3:] == body.split("\n", 3)[3:]:
        print("清單內容未變，略過重新產生")
        backfill()          # 但仍要補蓋先前失敗的日期
        return 0
    with open(sums, "w", encoding="utf-8") as f:
        f.write(body)
    print("已產生 %s（%d 個檔案）" % (os.path.basename(sums), len(files)))

    if not os.path.exists(OTS):
        print("[WARN] 找不到 ots 客戶端，略過蓋章：%s" % OTS, file=sys.stderr)
        return 1

    ok = do_stamp(sums)
    backfill()          # 順便補蓋歷史上失敗的日期
    return 0 if ok else 1


def do_stamp(sums):
    """對單一清單檔蓋章。逐次拉長逾時；仍失敗則降為「至少 1 個 calendar」。

    2026-08-28 實測失敗案例：預設 --timeout 5 秒、-m 2，
    四個 calendar 只有一個在時限內回應 → 蓋章失敗，但當時只留下一行 WARN。
    時間戳是本專案「資料在該時刻已存在」的唯一客觀證據，不能靜默失敗。
    """
    attempts = [("--timeout", "30", "-m", "2"),
                ("--timeout", "60", "-m", "2"),
                ("--timeout", "60", "-m", "1")]   # 最後退讓：1 個 calendar 也算數
    for n, opts in enumerate(attempts, 1):
        try:
            r = subprocess.run([OTS, "stamp", *opts, sums],
                               capture_output=True, text=True, timeout=180)
            out = (r.stdout + r.stderr).strip()
        except subprocess.TimeoutExpired:
            out = "本機 subprocess 逾時"
        if os.path.exists(sums + ".ots"):
            print("✅ 時間戳已提交：%s.ots（%d bytes，第 %d 次嘗試，%s）"
                  % (os.path.basename(sums), os.path.getsize(sums + ".ots"), n, " ".join(opts)))
            return True
        print("[第 %d 次失敗 %s] %s" % (n, " ".join(opts), out[-200:]), file=sys.stderr)
        time.sleep(5)
    print("[ERROR] %s 蓋章失敗（已重試 %d 次）" % (os.path.basename(sums), len(attempts)),
          file=sys.stderr)
    return False


def backfill():
    """補蓋：任何 SHA256SUMS-*.txt 若缺少對應的 .ots，就再試一次。

    時間戳晚一天蓋仍然有效，只是「證明存在的時點」精度差一天，
    遠優於永久沒有證明。
    """
    missing = [p for p in sorted(glob.glob(os.path.join(STAMPDIR, "SHA256SUMS-*.txt")))
               if not os.path.exists(p + ".ots")]
    if not missing:
        return
    print("補蓋 %d 份先前失敗的清單：%s"
          % (len(missing), ", ".join(os.path.basename(p) for p in missing)))
    for p in missing:
        do_stamp(p)


if __name__ == "__main__":
    sys.exit(main())
