# 🔴 每日自我檢查發現異常

檢查時間（UTC）：2026-08-27T09:12:06+00:00
檢查基準日（UTC）：2026-08-27

| 來源 | 問題 |
|---|---|
| `track-crypto/vast_gpu` | 體積異常：今日 174,956 B，前 1 日中位數 21,086 B（8.30×，容許 0.5–3.0×） |

本檔由 `scripts/healthcheck.py` 自動產生。異常排除後會自動刪除。

排查順序：`crontab -l` → `track-*/logs/cron.log` → 手動執行 snapshotter。
