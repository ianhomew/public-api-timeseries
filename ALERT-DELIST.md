# 🔴 track-crypto x402_bazaar 自清單消失規模異常警報（熔斷）

本檔案由 `track-crypto/scripts/detect_delistings.py` 獨佔寫入，不與任何其他程式共用
（另見 `ALERT.md` 是 `scripts/healthcheck.py` 的獨立輸出，兩者互不相干）。

本檔案記錄「removed 率超過熔斷門檻」這個事實（見下方各則區塊的數字），**不代表這些
resource 已永久下架**：本程式對「自清單消失」與「永久下架」不畫等號（詳見
`track-crypto/scripts/detect_delistings.py` 檔頭「事件型別語意定義」小節與本機
`docs/detect-phase1-report.md` §5、§9——同一資料源實測約 5%～17%（依觀察窗長短）的
「自清單消失」案例會在數天內重新出現）。熔斷只代表移除比例超出日常區間（1.8%~3.7%），
需要人工確認成因，本程式不自動判斷是抓取異常還是真的有大量 resource 同時消失。

本檔案只會新增，不會自動刪除既有區塊：每一則對應一組已發生的熔斷事件
（特定來源×特定比對日期），不是「現在是否有異常」的即時狀態旗標。
人工確認後若需歸檔，請自行搬移或加註（例如在行尾加 `<!-- ack:YYYY-MM-DD -->`），
本程式不會自動清除任何已寫入的區塊。

## 🔴 track-crypto/x402_bazaar 自清單消失熔斷警報（2026-09-07）

<!-- detect_delistings:x402_bazaar:2026-09-07 -->

檢查時間（UTC）：2026-09-07T03:31:22+00:00

| 項目 | 值 |
|---|---|
| 來源 | `track-crypto/x402_bazaar` |
| 比對區間 | `2026-09-06` → `2026-09-07` |
| removed 率 | 8.43%（門檻 5.0%） |
| 前日筆數（去重後） | 16590 |
| 當日移除筆數 | 1399 |

本日 `x402_bazaar` 的「自清單消失」判定已**暫停**，未寫入 `data/x402_bazaar/events.jsonl`。removed 率超過日常區間（1.8%~3.7%），可能是抓取異常，也可能是真的有大量 resource 同時自清單消失，詳見 `changes/x402_bazaar/2026-09-07.md`。人工確認後可手動處理（本程式不會自動重放此區間）。

## 🔴 track-crypto/x402_bazaar 自清單消失熔斷警報（2026-09-08）

<!-- detect_delistings:x402_bazaar:2026-09-08 -->

檢查時間（UTC）：2026-09-08T03:31:45+00:00

| 項目 | 值 |
|---|---|
| 來源 | `track-crypto/x402_bazaar` |
| 比對區間 | `2026-09-07` → `2026-09-08` |
| removed 率 | 6.69%（門檻 5.0%） |
| 前日筆數（去重後） | 15578 |
| 當日移除筆數 | 1042 |
| 處置 | **隔離**：事件已寫入 `data/x402_bazaar/events_quarantine.jsonl`，未進 events.jsonl |
| 隔離原因 | parser_version 兩日不同（1 → 2），解析器改版當天不放行 |

本日 `x402_bazaar` 的「自清單消失」判定**未寫入** `data/x402_bazaar/events.jsonl`，因為除了移除規模超過熔斷門檻之外，還同時命中「疑似分頁截斷」的結構性指紋（見上表）。事件事實**沒有遺失**，已完整寫入隔離檔 `data/x402_bazaar/events_quarantine.jsonl`，人工複核確認不是抓取問題後可提升回事件流。詳見 `changes/x402_bazaar/2026-09-08.md`。
