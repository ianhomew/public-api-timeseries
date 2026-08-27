#!/usr/bin/env python3
"""里程碑檢查：資料累積天數達門檻時，自動在 repo 產生顯眼的待辦檔案。
不依賴任何人記得。每日隨 push 一起執行。
"""
import os, glob, json, datetime

REPO = os.path.expanduser("~/snap/public-api-timeseries")
CRYPTO = os.path.join(REPO, "track-crypto/data/x402_bazaar")
OUT = os.path.join(REPO, "NEXT-STEP.md")

days = sorted(os.path.basename(p)[:10] for p in glob.glob(os.path.join(CRYPTO, "*.json.gz")))
n = len(days)
size_mb = sum(os.path.getsize(p) for p in glob.glob(os.path.join(REPO, "track-crypto/data/*/*.json.gz"))) / 1e6

MILESTONES = [
    (90,  "上傳 track-crypto 到 Hugging Face Datasets"),
    (180, "檢視：是否有人引用？是否申請 g0v / NLnet 補助？"),
    (365, "一年檢查點：是否出現陌生人重複使用？決定加倍或處決"),
]
due = [(d, t) for d, t in MILESTONES if n >= d]

if not due:
    if os.path.exists(OUT):
        os.remove(OUT)
    print("days=%d 尚未達里程碑" % n)
    raise SystemExit(0)

nxt = [(d, t) for d, t in MILESTONES if n < d]
lines = [
    "# ⚠️ 里程碑已達成，請執行下列動作",
    "",
    "自動產生於 %s（由 scripts/milestone.py 檢查）" % datetime.date.today().isoformat(),
    "",
    "| 項目 | 值 |",
    "|---|---|",
    "| 已累積天數 | **%d 天** |" % n,
    "| 資料起訖 | %s ~ %s |" % (days[0], days[-1]) if days else "| 資料起訖 | - |",
    "| track-crypto 總量 | **%.2f GB** |" % (size_mb / 1000),
    "",
    "## 待辦",
]
for d, t in due:
    lines.append("- [ ] **（%d 天門檻）%s**" % (d, t))
if nxt:
    lines += ["", "## 下一個里程碑"]
    for d, t in nxt:
        lines.append("- %d 天（還有 %d 天）：%s" % (d, d - n, t))
lines += [
    "",
    "## Hugging Face 上傳備忘",
    "- 需要：HF 帳號 + **write 權限的 Access Token**",
    "- Token 存放：`~/snap/.env` 的 `HF_TOKEN=`（權限 600，不入 git）",
    "- 上傳腳本：`scripts/upload_hf.py`（待建立）",
    "- 免費方案為 **best-effort**，超過數 GB 需證明對他人有價值",
    "",
    "**此檔案由程式自動產生與刪除。門檻未達成時會自動移除。**",
]
with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print("已產生 NEXT-STEP.md：%d 天，%.2f GB" % (n, size_mb / 1000))
