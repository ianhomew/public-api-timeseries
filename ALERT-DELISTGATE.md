# 🔴 track-crypto 下架偵測完整性守門觸發

檢查時間（UTC）：2026-09-14T03:33:32+00:00
檢查時間（台北）：2026-09-14T11:33:32+08:00
對應轉換目標日（UTC，該來源最新快照日）：2026-09-14

| 來源 | 比對區間 | 前日筆數 | 當日筆數 | 原因 |
|---|---|---|---|---|
| `agent_virtuals`／子集合 `_items` | `2026-09-13` → `2026-09-14` | 83710 | 61462 | 當日(2026-09-14)：truncated(True) 非布林 False（缺失/True 一律 fail-closed 視為不完整）（n=61462） |

以上來源（或子集合）本次轉換的自清單消失／新增判定**已跳過**（不寫 LISTED／DELISTED／REAPPEARED／RENAMED／STATUS_CHANGED），原始快照本身仍照常保存，只是這次轉換不參與比對。人類可讀細節見對應 `changes/<source>/2026-09-14.md`。

排查建議：檢查對應來源的 adapter 是否變更或暫時性故障（`track-crypto/adapters/`／`track-crypto/logs/`），確認後可手動重跑 `python3 track-crypto/scripts/detect_delistings.py` 補算。

本檔由 `scripts/healthcheck.py`（`check_delist_gate_fail()`）自動產生，只反映**最新一次轉換**的守門狀態；異常排除後（該來源下一次轉換不再觸發）會自動刪除，不留永久殘留。完整歷史紀錄（含已排除的舊紀錄）見 `track-crypto/data/_gate_fail/gate_skips.jsonl`。
