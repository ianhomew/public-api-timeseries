#!/usr/bin/env bash
# 每日：更新統計快取 → 偵測變動 → 里程碑檢查 → commit → push
set -euo pipefail
R="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$R"
export GIT_AUTHOR_NAME=vps-snapshotter
export GIT_AUTHOR_EMAIL=snapshotter@users.noreply.github.com
export GIT_COMMITTER_NAME=vps-snapshotter
export GIT_COMMITTER_EMAIL=snapshotter@users.noreply.github.com

mkdir -p logs

# 1) 統計快取（讓 ts 指令維持毫秒級）
python3 "$R/scripts/explore.py" --build-cache >/dev/null 2>>logs/cache.err || echo "$(date -Is) [WARN] build-cache 失敗" >> logs/cache.err

# 2) 偵測內容改寫／下架，產生 unified diff 紀錄
DETECT="$(python3 "$R/scripts/detect_changes.py" 2>&1 | tee -a logs/detect.log)" || {
  echo "$(date -Is) [FATAL] detect_changes 失敗，仍繼續提交資料" >&2
  DETECT="changed=0 removed=0 DETECT_FAILED"
}
CHANGED="$(printf '%s' "$DETECT" | sed -n 's/.*changed=\([0-9]*\).*/\1/p' | tail -1)"
REMOVED="$(printf '%s' "$DETECT" | sed -n 's/.*removed=\([0-9]*\).*/\1/p' | tail -1)"
CHANGED="${CHANGED:-0}"; REMOVED="${REMOVED:-0}"

# 3) OpenTimestamps：對資料清單蓋章（證明「這份資料在此時已存在」）
python3 "$R/scripts/stamp.py" >> logs/stamp.log 2>&1 || echo "$(date -Is) [WARN] stamp 失敗" >> logs/stamp.log

# 4) 里程碑
python3 "$R/scripts/milestone.py" >> logs/milestone.log 2>&1 || echo "$(date -Is) [WARN] milestone 失敗" >> logs/milestone.log

# 4) 提交
git add -A
if git diff --cached --quiet; then
  echo "$(date -Is) 無變更，略過"
  exit 0
fi
D="$(date -u +%F)"
N="$(git diff --cached --name-only | wc -l)"

if [ "$CHANGED" -gt 0 ] || [ "$REMOVED" -gt 0 ]; then
  git commit -q -F - <<EOF
[ALERT] ${D} 偵測到內容改寫 ${CHANGED} 筆、下架 ${REMOVED} 筆

政府公告在發布後被修改或移除。
完整 unified diff 見 CHANGES.md 與 changes/ 目錄。

本紀錄由程式自動產生，僅陳述「內容是否被修改」此一事實，不含任何解讀或評論。
EOF
  echo "$(date -Is) [ALERT] 改寫 ${CHANGED} 下架 ${REMOVED}"
else
  git commit -q -m "data: ${D} 每日快照 (${N} 檔變更)"
fi

if git push -q origin main; then
  echo "$(date -Is) 已推送 ${N} 檔"
else
  echo "$(date -Is) 推送失敗" >&2
  exit 1
fi
