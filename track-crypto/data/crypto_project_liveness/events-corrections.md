# events-corrections — crypto_project_liveness 更正註記（人類可讀版，自動產生）

> 本檔由 `events-corrections.jsonl` 自動重新算出，請勿手動編輯本檔；
> 要新增/查詢更正，請改 `events-corrections.jsonl` 或用 `apply_correction.py`。
> 對應的原始事實串流：`events.jsonl`（本機制絕不刪除、絕不覆寫該檔）。

共 1 筆更正紀錄。

| # | 更正時間 | 判定 | 指向的原始事件 | 原因代碼 | 依據 | 稽核報告 |
|---|---|---|---|---|---|---|
| 1 | 2026-09-07T09:30:00.388224+00:00 | **判定為假事件** | date='2026-09-06' source='crypto_project_liveness' group='_hacks' key='stake dao\x1f1773273600' event='DELISTED'; date='2026-09-06' source='crypto_project_liveness' group='_hacks' key='stake dao\x1f1779840000' event='DELISTED'; date='2026-09-06' source='crypto_project_liveness' group='_hacks' key='stake dao yield\x1f1773273600' event='LISTED'; date='2026-09-06' source='crypto_project_liveness' group='_hacks' key='stake dao yield\x1f1779840000' event='LISTED' | UPSTREAM_RENAME | DefiLlama 端把 Stake DAO 改名為 Stake DAO Yield：09-05 與 09-06 兩份快照的 defillamaId 皆為 "249"，date/classification/technique/amount/chain/bridgeHack/targetType/language 逐一相同（逐欄位比對表見稽核報告 §5.5）。複合主鍵 (name,date) 因此把同 2 筆歷史事件誤判為 2 筆消失＋2 筆新增。 | docs/0907-events-audit-0904-0907.md §5.5 ／ docs/0907-B-rename-key-report.md §6 |
