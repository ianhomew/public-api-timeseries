# 🔴 cex_events 上下架規模異常警報（熔斷）

本檔案由 `scripts/cex_events.py` 獨佔寫入，不與任何其他程式共用
（`ALERT.md` 是 `scripts/healthcheck.py` 的輸出、`ALERT-DELIST.md` 是
`track-crypto/scripts/detect_delistings.py` 的輸出、`ALERT-CEXGATE.md` 是
`scripts/healthcheck.py` 讀 `gate_skips.jsonl` 後的輸出，四者互不相干）。

本檔案記錄「某交易所單日 DELISTED 筆數超過熔斷門檻」這個事實。**熔斷不代表事件是假的**：
本程式對熔斷採「標記但不否決」——事件**已經照常寫入** `track-crypto/data/cex_events/events.jsonl`，
每一筆都帶 `note:"anomalous_scale"`、`breaker_tripped:true`、`removed_pct`、`breaker_threshold`
四個欄位。本檔案的用途是**要求人工複核**，不是宣告資料有錯。

本檔案只會新增，不會自動刪除既有區塊；只對「最新一組轉換」寫入（理由見
`scripts/cex_events.py` 的 `write_alert_block_cexbreaker()` docstring）。
人工確認後若需歸檔，請自行搬移或加註（例如在行尾加 `<!-- ack:YYYY-MM-DD -->`）。

## 🔴 cex_events／kucoin 上下架規模異常熔斷警報（2026-09-08）

<!-- cex_events:kucoin:2026-09-08 -->

檢查時間（UTC）：2026-09-08T03:30:18+00:00

| 項目 | 值 |
|---|---|
| 交易所 | `kucoin` |
| 比對區間 | `2026-09-07` → `2026-09-08` |
| 前日筆數 | 1008 |
| 當日 DELISTED 筆數 | 25（2.48%） |
| 熔斷門檻（筆數） | 10.1＝max(10, 1.0%×前日筆數) |
| 同組 LISTED／STATUS_CHANGED | 0／0 |
| 分頁截斷指紋 tail_cover | 0.0000（參考值，門檻 0.50；本來源不用它否決，見 BREAKER_TRUNCATION_QUARANTINE） |
| 處置 | **標記但不否決**：事件已寫入 `track-crypto/data/cex_events/events.jsonl` |

本組轉換產生的每一筆事件（LISTED／DELISTED／STATUS_CHANGED）都已帶 `note:"anomalous_scale"`、`breaker_tripped:true`、`removed_pct`、`breaker_threshold` 四個欄位，**需要人工複核**。本程式不對成因下判斷（零觀點鐵律）：可能是抓取異常，也可能是真的有大量交易對同時下架。若複核後判定為假事件，請用 `scripts/apply_correction.py` 更正，不要手動編輯事件流。

## 🔴 cex_events／bitget 上下架規模異常熔斷警報（2026-09-12）

<!-- cex_events:bitget:2026-09-12 -->

檢查時間（UTC）：2026-09-12T03:30:20+00:00

| 項目 | 值 |
|---|---|
| 交易所 | `bitget` |
| 比對區間 | `2026-09-11` → `2026-09-12` |
| 前日筆數 | 1780 |
| 當日 DELISTED 筆數 | 19（1.07%） |
| 熔斷門檻（筆數） | 17.8＝max(10, 1.0%×前日筆數) |
| 同組 LISTED／STATUS_CHANGED | 0／0 |
| 分頁截斷指紋 tail_cover | 0.0000（參考值，門檻 0.50；本來源不用它否決，見 BREAKER_TRUNCATION_QUARANTINE） |
| 處置 | **標記但不否決**：事件已寫入 `track-crypto/data/cex_events/events.jsonl` |

本組轉換產生的每一筆事件（LISTED／DELISTED／STATUS_CHANGED）都已帶 `note:"anomalous_scale"`、`breaker_tripped:true`、`removed_pct`、`breaker_threshold` 四個欄位，**需要人工複核**。本程式不對成因下判斷（零觀點鐵律）：可能是抓取異常，也可能是真的有大量交易對同時下架。若複核後判定為假事件，請用 `scripts/apply_correction.py` 更正，不要手動編輯事件流。
