#!/usr/bin/env bash
# 每日：更新統計快取 → 偵測變動 → 里程碑檢查 → commit → push
set -Eeuo pipefail
R="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$R"
export GIT_AUTHOR_NAME=vps-snapshotter
export GIT_AUTHOR_EMAIL=snapshotter@users.noreply.github.com
export GIT_COMMITTER_NAME=vps-snapshotter
export GIT_COMMITTER_EMAIL=snapshotter@users.noreply.github.com

mkdir -p logs

# 死人開關（healthchecks.io）：成功跑完才 ping。
# 若 VPS 當機、斷網、cron 沒跑、push 失敗 —— 都不會 ping，外部服務逾時後通知使用者。
# ping 網址等同一把權杖，因此放在 .gitignore 內的 ~/snap/.env，不寫進這支公開腳本。
set -a; . "$HOME/snap/.env" 2>/dev/null || true; set +a
hc_ping() {   # $1: 空字串=成功 / "/fail"=失敗 / "/start"=開始
  [ -n "${HC_PING_URL:-}" ] || return 0
  curl -fsS -m 10 --retry 3 -o /dev/null "${HC_PING_URL}${1:-}" || true
}
trap 'hc_ping /fail' ERR
hc_ping /start

# 1) 統計快取（讓 ts 指令維持毫秒級）
python3 "$R/scripts/explore.py" --build-cache >/dev/null 2>>logs/cache.err || echo "$(date -Is) [WARN] build-cache 失敗" >> logs/cache.err

# 2) 偵測內容改寫／下架，產生 unified diff 紀錄
DETECT_OK=1
DETECT="$(python3 "$R/scripts/detect_changes.py" 2>&1 | tee -a logs/detect.log)" || {
  echo "$(date -Is) [FATAL] detect_changes 失敗，仍繼續提交資料" >&2
  DETECT="changed=0 removed=0 DETECT_FAILED"
  DETECT_OK=0
}
# 變動偵測是這個專案的核心功能。它掛掉時若沉默地以「0 筆變動」繼續，
# 等於核心功能失效卻回報一切正常。改為明確留下告警並通知。
if [ "$DETECT_OK" = "0" ]; then
  {
    echo "# 🔴 變動偵測失敗"
    echo
    echo "檢查時間（UTC）：$(date -u -Is)"
    echo
    echo "\`scripts/detect_changes.py\` 執行失敗，本日**未進行**改寫／下架偵測。"
    echo "資料快照仍已保存，但這一天的比對結果不存在。"
    echo
    echo "排查：\`python3 scripts/detect_changes.py\` 手動執行看錯誤訊息。"
  } > ALERT-DETECT.md
else
  rm -f ALERT-DETECT.md
fi
CHANGED="$(printf '%s' "$DETECT" | sed -n 's/.*changed=\([0-9]*\).*/\1/p' | tail -1)"
REMOVED="$(printf '%s' "$DETECT" | sed -n 's/.*removed=\([0-9]*\).*/\1/p' | tail -1)"
CHANGED="${CHANGED:-0}"; REMOVED="${REMOVED:-0}"

# 2b) CEX 上/下架事件流（生存者偏誤修正：3 家交易所只回存活標的）
python3 "$R/scripts/cex_events.py" >> logs/cex_events.log 2>&1 || echo "$(date -Is) [WARN] cex_events 失敗" >> logs/cex_events.log

# 2c) 軌一「自清單消失」偵測（第一階段：僅 x402_bazaar，白名單制）
python3 "$R/track-crypto/scripts/detect_delistings.py" >> logs/detect_delistings.log 2>&1 || echo "$(date -Is) [WARN] detect_delistings 失敗" >> logs/detect_delistings.log

# 3) OpenTimestamps：對資料清單蓋章（證明「這份資料在此時已存在」）
python3 "$R/scripts/stamp.py" >> logs/stamp.log 2>&1 || echo "$(date -Is) [WARN] stamp 失敗" >> logs/stamp.log

# 4) 里程碑
python3 "$R/scripts/milestone.py" >> logs/milestone.log 2>&1 || echo "$(date -Is) [WARN] milestone 失敗" >> logs/milestone.log

# 4b) 自我檢查：沉默即異常（缺檔／體積異常／manifest 失敗 → 產生 ALERT.md）
if ! python3 "$R/scripts/healthcheck.py" >> logs/healthcheck.log 2>&1; then
  # 自我檢查自己掛掉，不能當成「沒異常」——那是最危險的靜默失敗
  echo "$(date -Is) [FATAL] healthcheck 失敗" >> logs/healthcheck.log
  {
    echo "# 🔴 自我檢查程式失敗"
    echo
    echo "檢查時間（UTC）：$(date -u -Is)"
    echo
    echo "\`scripts/healthcheck.py\` 執行失敗，本日**未進行**缺檔／體積／manifest 檢查。"
    echo "資料是否正常抓取，本日無法由自動機制確認。"
  } > ALERT-HEALTH.md
else
  rm -f ALERT-HEALTH.md
fi

# 4c) 每日巡檢報告（主動回報，非只在異常時通知）
#     失敗不得中斷提交流程：報告是附加價值，資料保存才是主線。
if ! python3 "$R/scripts/daily_report.py" >> logs/daily_report.log 2>&1; then
  echo "$(date -Is) [WARN] daily_report 失敗" >> logs/daily_report.log
  printf '# 每日巡檢報告產生失敗\n\n產生時間（UTC）：%s\n\n請執行 python3 scripts/daily_report.py 查看錯誤。\n' "$(date -u -Is)" > REPORT.md
fi

# 4d) Hugging Face 私有備份同步（軌一 4 個大型來源異地備份，增量、冪等）
#     失敗不中斷提交流程（異地備援不是當天能否 push 的必要條件），
#     但**必須留下告警**：本專案原則是「任何失敗但只記 WARN 的地方都要補告警」。
if [ -n "${HF_TOKEN:-}" ]; then
  # hf_sync 需要 huggingface_hub，只裝在 ~/snap/venv，不能用系統 python3（2026-09-04 實測踩過）
  if "$HOME/snap/venv/bin/python3" "$R/scripts/hf_sync.py" >> logs/hf_sync.log 2>&1; then
    rm -f ALERT-BACKUP.md
  else
    echo "$(date -Is) [WARN] hf_sync 失敗" >> logs/hf_sync.log
    printf '# 異地備份未更新\n\n時間（UTC）：%s\n\n`scripts/hf_sync.py` 執行失敗，Hugging Face 私有備份本日未同步。\n排查：`logs/hf_sync.log`。\n本檔在下次同步成功後自動刪除。\n' "$(date -u -Is)" > ALERT-BACKUP.md
  fi
else
  echo "$(date -Is) [SKIP] HF_TOKEN 未設定，略過 hf_sync" >> logs/hf_sync.log
fi

# 4) 提交
git add -A
if git diff --cached --quiet; then
  echo "$(date -Is) 無變更，略過"
  hc_ping
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
  hc_ping /fail
  exit 1
fi

# 資料抓取本身有異常時（healthcheck.py 產生了 ALERT.md），
# 即使 push 成功也回報失敗，讓使用者收到通知，不必自己去 GitHub 看。
if [ -f ALERT.md ] || [ -f ALERT-DETECT.md ] || [ -f ALERT-HEALTH.md ] || [ -f ALERT-DELIST.md ] || [ -f ALERT-BACKUP.md ] || [ -f ALERT-CEXGATE.md ]; then
  echo "$(date -Is) ALERT.md 存在 → 回報 fail"
  hc_ping /fail
else
  hc_ping
fi
