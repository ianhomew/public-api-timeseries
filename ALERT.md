# 🔴 每日自我檢查發現異常

檢查時間（UTC）：2026-08-30T04:55:12+00:00
檢查基準日（UTC）：2026-08-30

| 來源 | 問題 |
|---|---|
| `track-gov/moi_press` | manifest 標記失敗：URLError: <urlopen error [Errno -3] Temporary failure in name resolution> |
| `track-gov/moi_press` | 今日（UTC 2026-08-30）缺檔；最後一份為 2026-08-28（已 2 天無新資料） |

本檔由 `scripts/healthcheck.py` 自動產生。異常排除後會自動刪除。

排查順序：`crontab -l` → `track-*/logs/cron.log` → 手動執行 snapshotter。
