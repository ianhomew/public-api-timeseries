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
# 第二把死人開關（2026-09-09 新增）：「有沒有已發生的熔斷事件還沒人複核」。
# 與上面的主開關語意不同，所以刻意分成兩個 healthchecks.io check：
#   主開關 HC_PING_URL        → 排程今天有沒有正常跑完（異常排除後隔天自動轉綠）
#   本開關 HC_REVIEW_PING_URL → 永久事件帳本裡有沒有未確認的區塊（人工 ack 後轉綠）
# 混在同一顆燈上就會變成 2026-09-07 起那種「永遠紅」的狀態，完全失去訊號價值
# （完整分析見 scripts/alert_state.py 檔頭與 docs/0909-deadman-switch-report.md）。
# 未設定 HC_REVIEW_PING_URL 時回傳 1：呼叫端會把待複核訊號**退回主開關**，
# 不允許它靜默消失（fail-closed）。
hc_review_ping() {   # $1: 同 hc_ping
  [ -n "${HC_REVIEW_PING_URL:-}" ] || return 1
  curl -fsS -m 10 --retry 3 -o /dev/null "${HC_REVIEW_PING_URL}${1:-}" || true
  return 0
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
  # 2026-09-09 修正：ALERT-BACKUP.md 是「即時狀態旗標」，語意是「現在異地備份有沒有問題」，
  # 因此每一條執行路徑都必須把它更新成當下的真相。舊版只在 HF_TOKEN 有設定的那條分支上
  # 寫／刪這個檔：若 token 之後被移除，上一次失敗留下的舊檔就永遠不會被清掉，變成
  # 第三個「永遠紅」的來源（與 ALERT-DELIST.md 同一類的病，見 scripts/alert_state.py 檔頭）。
  # 這裡把「備份未啟用」本身也視為異地備援異常並如實寫進旗標——備份沒在跑就是排程健康問題，
  # 正是主死人開關該通知的事。
  printf '# 異地備份未啟用\n\n時間（UTC）：%s\n\n`HF_TOKEN` 未設定，`scripts/hf_sync.py` 本日未執行，Hugging Face 私有備份沒有更新。\n排查：檢查 `~/snap/.env` 的 `HF_TOKEN`。\n本檔在下次同步成功後自動刪除。\n' "$(date -u -Is)" > ALERT-BACKUP.md
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

# 死人開關判定（2026-09-09 重寫）。
#
# 舊版：`if [ -f ALERT.md ] || [ -f ALERT-DETECT.md ] || ... ; then hc_ping /fail`
#   —— 用「檔案存不存在」一刀切。這個前提對 6 個即時狀態旗標成立，
#   對 ALERT-DELIST.md／ALERT-CEXBREAKER.md 這兩個**永久事件帳本**不成立：
#   它們的檔頭自己就寫著「只會新增，不會自動刪除既有區塊……不是『現在是否有異常』
#   的即時狀態旗標」，全 repo 也沒有任何程式碼路徑會刪除它們。
#   實測後果：ALERT-DELIST.md 於 2026-09-07 11:31:54（commit 5d29907）產生後從未消失，
#   死人開關自該日起每天 /fail 且永遠不會轉綠——一顆永遠紅的燈等於沒有燈。
#
# 舊版第二個問題：log 訊息寫死成「ALERT.md 存在 → 回報 fail」，不管實際是哪個檔案觸發。
#   2026-09-08 那天 ALERT.md 其實已被 healthcheck.py 刪除（該次 commit 的 name-status
#   是 `D ALERT.md`、healthcheck.log 寫「OK 2026-09-08 全部正常」），真正命中的是
#   ALERT-DELIST.md，這行訊息卻仍指向 ALERT.md，直接把排查方向帶錯。
#
# 新版：判定邏輯集中在 scripts/alert_state.py（語意登記表＋fail-closed 規則的唯一事實
#   來源，同一份登記表也給 scripts/daily_report.py 用，不再各自硬編碼一份檔名清單）。
#   本處只負責把結果翻成 ping，並把**實際觸發的是哪些檔案**逐行寫進 logs/push.log。
# >>> deadman-eval-begin  （scripts/selftest.py 的 push_sh.deadman_* 檢查會原文切出
#     這兩個界標之間的片段、套上 hc_ping／hc_review_ping 樁，實際用 bash 跑一遍驗證
#     fail-closed 行為。改動這一段時界標請一併保留，否則 selftest 會直接報錯。）
DEADMAN_RC=0
DEADMAN_OUT="$(python3 "$R/scripts/alert_state.py" --deadman 2>&1)" || DEADMAN_RC=$?
printf '%s\n' "$DEADMAN_OUT" | sed "s|^|$(date -Is) [deadman] |"

# fail-closed：預設兩盞燈都紅，只有在輸出裡明確讀到 `=ok` 才轉綠。
# alert_state.py 當掉、被刪、輸出被截斷、python3 不存在——全部自動落在紅燈側。
DEADMAN_PRIMARY=fail
DEADMAN_REVIEW=fail
case "$DEADMAN_OUT" in *DEADMAN_PRIMARY=ok*) DEADMAN_PRIMARY=ok ;; esac
case "$DEADMAN_OUT" in *DEADMAN_REVIEW=ok*) DEADMAN_REVIEW=ok ;; esac
echo "$(date -Is) [deadman] alert_state.py rc=${DEADMAN_RC} primary=${DEADMAN_PRIMARY} review=${DEADMAN_REVIEW}"

# 待複核訊號 → 第二個 check。未設定 HC_REVIEW_PING_URL 時不得靜默丟棄，退回主開關。
if [ "$DEADMAN_REVIEW" = "ok" ]; then
  hc_review_ping || echo "$(date -Is) [deadman] HC_REVIEW_PING_URL 未設定（待複核為 ok，無訊號可傳）"
else
  if ! hc_review_ping /fail; then
    echo "$(date -Is) [deadman] HC_REVIEW_PING_URL 未設定 → 待複核訊號退回主開關（fail-closed）；設定後兩者才會分離"
    DEADMAN_PRIMARY=fail
  fi
fi

# 排程健康訊號 → 主 check（既有的 HC_PING_URL，行為與網址完全不變）。
if [ "$DEADMAN_PRIMARY" = "ok" ]; then
  hc_ping
else
  hc_ping /fail
fi
# >>> deadman-eval-end
