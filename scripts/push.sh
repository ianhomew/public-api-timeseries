#!/usr/bin/env bash
# 每日自動提交與推送。只提交 .gitignore 允許的檔案（軌一大型資料不入庫）
set -euo pipefail
cd "$HOME/snap/public-api-timeseries"
export GIT_AUTHOR_NAME=vps-snapshotter
export GIT_AUTHOR_EMAIL=snapshotter@users.noreply.github.com
export GIT_COMMITTER_NAME=vps-snapshotter
export GIT_COMMITTER_EMAIL=snapshotter@users.noreply.github.com

git add -A
if git diff --cached --quiet; then
  echo "$(date -Is) 無變更，略過"
  exit 0
fi
D=$(date -u +%F)
N=$(git diff --cached --name-only | wc -l)
git commit -q -m "data: ${D} 每日快照 (${N} 檔變更)"
if git push -q origin main 2>&1; then
  echo "$(date -Is) 已推送 ${N} 檔"
else
  echo "$(date -Is) 推送失敗" >&2
  exit 1
fi
