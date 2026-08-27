# track-gov — 台灣政府公告每日快照（可問責性存檔）

回上層：[專案總覽](../README.md)

這是原始公告存檔，**不含任何分析、解讀或評論**。

每日對指定欄目做完整快照，保存 `body_sha256`，用來偵測發布後的**改寫、下架、撤稿**。

## 收錄來源

| channel | 來源 | 筆數 | 說明 |
|---|---|---|---|
| `fsc_clarification` | 金管會 即時新聞澄清（`id=609`） | **50**（全部歷史） | 2017-03 起，每年約新增 5 筆 |

每日壓縮後約 **42 KB**，一輪約 52 次請求、約 113 秒。維護成本近乎零。

端點、欄位、踩過的坑 → [docs/sources.md](../docs/sources.md)

## 為什麼存

50 篇中 **49 篇已存在於 Internet Archive**，但抽樣中位擷取數僅 **1 次**，
其中 56% 的篇目無法用 Wayback 偵測發布後的改寫。

因此本軌的價值是**高頻改寫偵測**，不是「唯一副本」。
早期文件曾宣稱「內頁 Wayback 存檔 0 份」，該測法有誤，已更正 →
[docs/revisions.md](../docs/revisions.md)

## 怎麼偵測改寫

每筆包含 `dataserno`、`url`、`title`、`date`、`body_text`、`body_sha256`、`raw_sha256`、`raw_bytes`。

比對相同 `dataserno` 在不同日期的 `body_sha256`，不同即為改寫。
`scripts/detect_changes.py` 每日自動執行，有變動才產生 `changes/` 與 `CHANGES.md`。

可執行範例 → [docs/data-format.md](../docs/data-format.md)

## 法律依據

- **著作權法第 9 條第 2 項**明文：「公文包括公務員職務上草擬之文告、講稿、**新聞稿**」→ 不受著作權保護。
- 個資風險低：裁罰受處分人多為法人；自然人姓名官方已遮罩（如「林00先生」）。
- robots.txt 合規：金管會僅 `Disallow: /uploaddowndoc`，本專案未觸及。

## 目錄

```
data/<channel>/YYYY-MM-DD.json.gz   一天一檔，日期為 UTC，永不覆蓋
data/_manifest/YYYY-MM-DD.json      當日筆數、成敗、大小、耗時
scripts/snap_gov.py                 抓取程式
```

## 授權

資料 **CC BY 4.0**，程式碼 **MIT**。使用時請標示來源。

## 免責

本存檔僅記錄公開網頁在特定時間點的內容，不對資料正確性作任何保證，
不構成任何投資建議、法律意見或分析觀點。使用者應自行至官方網站查證。
