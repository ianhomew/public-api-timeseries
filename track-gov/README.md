# track-gov — 台灣政府公告每日快照（可問責性存檔）

回上層：[專案總覽](../README.md)

這是原始公告存檔，**不含任何分析、解讀或評論**。

每日對指定欄目做完整快照，保存 `body_sha256`，用來偵測發布後的**改寫、下架、撤稿**。

## 收錄來源

| channel | 機關與類別 | 筆數 | 每日壓縮後 | 一輪耗時 |
|---|---|---|---|---|
| `fsc_clarification` | 金管會 即時新聞澄清 | 50（全部歷史） | 40 KB | 142s |
| `moe_clarify` | 教育部 即時新聞澄清 | 80（全部歷史） | 73 KB | 327s |
| `moj_press` | 法務部 新聞發布 | 99 | 107 KB | 596s |
| `cbc_press` | 中央銀行 新聞稿／新聞參考資料 | 99 | 47 KB | 304s |
| `mof_press` | 財政部 本部新聞 | 99 | 82 KB | 308s |
| `mol_press` | 勞動部 新聞稿 | 100 | 133 KB | 289s |
| `moda_press` | 數位發展部 新聞發布 | 100 | 98 KB | 120s |
| `moi_press` | 內政部 新聞稿 | 100 | 99 KB | 381s |
| `ey_press` | 行政院 本院新聞 | 100 | 176 KB | 356s |
| `mohw_press` | 衛生福利部 焦點新聞 | 100 | 118 KB | 277s |
| `moe_press` | 教育部 即時新聞 | 100 | 121 KB | 420s |
| `moea_press` | 經濟部 本部新聞 | 100 | 115 KB | 226s |

合計每日約 **1.19 MB**、約 1,260 次請求、約 62 分鐘（每次請求間隔 1 秒）。
數值為 2026-08-27（UTC）在 VPS 實測。

**未收錄**：

| 機關 | 原因 |
|---|---|
| 環境部 | robots.txt 明文禁止 `/Page/`、`/page/`、`/News_Content.aspx`，新聞稿全部落在禁止路徑；且全站 Cloudflare JS 挑戰，`Cf-Mitigated: challenge` |

## 架構

一個來源一支 adapter，放在 `adapters/<key>.py`，只需提供：

```python
KEY, DESC, SOURCE_HOME, ROBOTS_VERIFIED
def collect(fetch, clean) -> list[dict]   # id, url, title, date, body_text
```

`scripts/snap_gov.py` 自動載入 `adapters/*.py`，統一計算 `body_sha256`、原子寫入、
產生 manifest。新增機關不必改主程式；`detect_changes.py` 與 `healthcheck.py`
也會自動探索 adapter 清單。

單獨執行一個來源：`python3 scripts/snap_gov.py fsc_clarification`

端點、欄位、踩過的坑 → [docs/sources.md](../docs/sources.md)

## 為什麼存

50 篇中 **49 篇已存在於 Internet Archive**，但抽樣中位擷取數僅 **1 次**，
其中 56% 的篇目無法用 Wayback 偵測發布後的改寫。

因此本軌的價值是**高頻改寫偵測**，不是「唯一副本」。
早期文件曾宣稱「內頁 Wayback 存檔 0 份」，該測法有誤，已更正 →
[docs/revisions.md](../docs/revisions.md)

## 怎麼偵測改寫

每筆包含 `id`、`url`、`title`、`date`、`body_text`、`body_sha256`。
（金管會另保留 `dataserno` 欄位，與 2026-08-27 之前的快照相容。）

比對相同 `id` 在**不同日期**的 `body_sha256`，不同即為改寫。
同一 UTC 日期內的多份快照屬於重跑產物，只取當日最後一份，不視為改寫事件。

**揮發性內容過濾**：部分機關頁面正文含「瀏覽人次」計數器，每次抓取都會變。
這類行在寫入前即被移除，否則每日 diff 會天天誤報改寫，真訊號被雜訊淹沒。
`scripts/detect_changes.py` 每日自動執行，有變動才產生 `changes/` 與 `CHANGES.md`。

可執行範例 → [docs/data-format.md](../docs/data-format.md)

## 法律依據

- **著作權法第 9 條第 2 項**明文：「公文包括公務員職務上草擬之文告、講稿、**新聞稿**」→ 不受著作權保護。
- 個資風險低：裁罰受處分人多為法人；自然人姓名官方已遮罩（如「林00先生」）。
- robots.txt 合規：每個機關在納入前都逐一親驗 robots.txt，實際 Disallow 行記錄於各 adapter 的
  `ROBOTS_VERIFIED` 欄位，並寫入每份快照的 `_meta`。被明文禁止者一律不收錄，不做例外。
- 一律不抓附件檔，只抓 HTML 正文。

## 目錄

```
data/<channel>/YYYY-MM-DD.json.gz   一天一檔，日期為 UTC，永不覆蓋
data/_manifest/YYYY-MM-DD.json      當日筆數、成敗、大小、耗時
adapters/<key>.py                   各機關的抓取規則（一個來源一支）
scripts/snap_gov.py                 主程式，自動載入 adapters/
```

## 授權

資料 **CC BY 4.0**，程式碼 **MIT**。使用時請標示來源。

## 免責

本存檔僅記錄公開網頁在特定時間點的內容，不對資料正確性作任何保證，
不構成任何投資建議、法律意見或分析觀點。使用者應自行至官方網站查證。
