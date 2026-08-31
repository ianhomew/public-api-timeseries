# track-gov — 台灣政府公告每日快照（可問責性存檔）

回上層：[專案總覽](../README.md)

這是原始公告存檔，**不含任何分析、解讀或評論**。

每日對指定欄目做完整快照，保存 `body_sha256`，用來偵測發布後的**改寫、下架、撤稿**。

## 收錄來源（18 個）

筆數、體積、耗時：舊 12 個來源沿用 2026-08-27 UTC 舊實測值；新 6 個來源
（`fda_clarify`／`fsc_lawnotice`／`fsc_penalty`／`ftc_decision`／`pres_news`／`tpe_clarify`）
本輪已從 VPS `track-gov/data/_manifest/2026-08-31.json`、`track-gov/logs/cron.log` 補齊
2026-08-31 UTC 實測值（唯讀讀取既有紀錄，本輪未重新執行抓取）。

| channel | 機關與類別 | 筆數 | 每日壓縮後 | 一輪耗時 | MAX_ITEMS／等效上限 |
|---|---|---|---|---|---|
| `cbc_press` | 中央銀行 新聞稿／新聞參考資料 | 99 | 47 KB | 304s | MAX_ITEMS=100；MAX_PAGES=5 |
| `ey_press` | 行政院 本院新聞 | 100 | 176 KB | 356s | MAX_ITEMS=100；MAX_PAGES=1 |
| `fda_clarify` | 衛生福利部食品藥物管理署（食藥署） 食藥闢謠專區 | 33（`truncated=true`，600s 預算截斷，目標 50 未達成，2026-08-31 UTC） | 14.6 KB（14,937 B） | 610.3s | MAX_ITEMS=50 |
| `fsc_clarification` | 金融監督管理委員會（金管會） 即時新聞澄清 | 50（全部歷史） | 40 KB | 142s | MAX_PAGES=50 |
| `fsc_lawnotice` | 金融監督管理委員會（金管會） 法規草案預告 | 100（2026-08-31 UTC） | 24.7 KB（25,281 B） | 244.4s | MAX_PAGES=8 |
| `fsc_penalty` | 金融監督管理委員會（金管會） 裁罰案件 | 100（2026-08-31 UTC） | 136.7 KB（140,021 B） | 300.7s | MAX_PAGES=8 |
| `ftc_decision` | 公平交易委員會 本會行政決定（處分書及不處分決議書） | 100（2026-08-31 UTC） | 17.1 KB（17,478 B） | 187.3s | MAX_PAGES=10 |
| `moda_press` | 數位發展部 新聞發布 | 100 | 98 KB | 120s | MAX_ITEMS=100；MAX_PAGES=1 |
| `moe_clarify` | 教育部 即時新聞澄清 | 80（全部歷史） | 73 KB | 327s | MAX_ITEMS=100；MAX_PAGES=2 |
| `moe_press` | 教育部 即時新聞 | 100 | 121 KB | 420s | MAX_ITEMS=100；MAX_PAGES=2 |
| `moea_press` | 經濟部 本部新聞 | 100 | 115 KB | 226s | MAX_ITEMS=100；MAX_PAGES=10 |
| `mof_press` | 財政部 本部新聞 | 99 | 82 KB | 308s | MAX_ITEMS=100；MAX_PAGES=10 |
| `mohw_press` | 衛生福利部 焦點新聞 | 100 | 118 KB | 277s | MAX_ITEMS=100；MAX_PAGES=5 |
| `moi_press` | 內政部 新聞稿 | 100 | 99 KB | 381s | MAX_ITEMS=100；MAX_PAGES=1 |
| `moj_press` | 法務部 新聞發布 | 99 | 107 KB | 596s | MAX_ITEMS=50；MAX_PAGES=5 |
| `mol_press` | 勞動部 新聞稿 | 100 | 133 KB | 289s | MAX_ITEMS=100；MAX_PAGES=3 |
| `pres_news` | 總統府 本府新聞稿 | 15（官方清單本身僅 15 筆可取，非截斷，DESC 已誠實標註，2026-08-31 UTC） | 41.2 KB（42,216 B） | 39.2s | MAX_ITEMS=100 |
| `tpe_clarify` | 台北市政府 即時新聞澄清 | 39（`truncated=true`，600s 預算截斷，目標 50 未達成，2026-08-31 UTC） | 27.2 KB（27,850 B） | 603.6s | MAX_ITEMS=50；MAX_PAGES=8 |

原 12 個來源合計每日約 **1.19 MB**、約 1,260 次請求、約 62 分鐘（2026-08-27 UTC 舊實測值；
2026-08-31 UTC 重新查核 manifest，同 12 個來源當日合計約 **1.13 MB**（1,152,708 B），屬同量級的正常日常波動）。
新增 6 個來源 2026-08-31 UTC 實測合計約 **262 KB**（267,783 B）、耗時合計約 **31.4 分鐘**
（610.3+244.4+300.7+187.3+39.2+603.6 = 1,985.5 秒）。18 個來源合計每日壓縮後約 **1.35 MB**（1,420,491 B）。
已累積天數：舊 12 個來源介於 4～6 天（`cbc_press`／`ey_press` 6 天，`fsc_clarification` 7 天，其餘 4～5 天）；
新 6 個來源皆為 **4 天**（2026-08-28～08-31）。來源：`track-gov/data/_manifest/2026-08-31.json`、
`track-gov/logs/cron.log`、`ls track-gov/data/<source>/ | wc -l`（本輪唯讀查核）。

**未收錄**：

| 機關 | 原因 |
|---|---|
| 環境部 | robots.txt 明文禁止 `/Page/`、`/page/`、`/News_Content.aspx`，新聞稿全部落在禁止路徑；且全站 Cloudflare JS 挑戰，`Cf-Mitigated: challenge` |

## 架構

一個來源一支 adapter，放在 `adapters/<key>.py`，至少提供：

```python
KEY, DESC, SOURCE_HOME, ROBOTS_VERIFIED
def collect(fetch, clean) -> list[dict]   # id, url, title, date, body_text
```

部分新機關（`fda_clarify`／`tpe_clarify`／`moj_press`）另支援 `collect(fetch, clean, deadline=None)`，
由驅動程式傳入 UNIX 時間戳，逾時停止並回傳已取得資料（向下相容：`deadline=None` 時行為與舊版相同）。

`scripts/snap_gov.py` 自動載入 `adapters/*.py`，統一計算 `body_sha256`、原子寫入、
產生 manifest。新增機關不必改主程式；`detect_changes.py` 與 `healthcheck.py`
也會自動探索 adapter 清單。

單獨執行一個來源：`python3 scripts/snap_gov.py fsc_clarification`

端點、欄位、踩過的坑 → [docs/sources.md](../docs/sources.md)

## 為什麼存

50 篇中 **49 篇已存在於 Internet Archive**，但抽樣中位擷取數僅 **1 次**，
其中 56% 的篇目無法用 Wayback 偵測發布後的改寫（此為 `fsc_clarification` 頻道抽樣結果，
2026-08-27 UTC 實測；本輪新增的 6 個機關未重新抽測 Wayback 覆蓋率）。

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
截至目前已偵測到 1 起改寫（2026-08-29，`mof_press`，見專案根目錄 [README.md](../README.md)
「首次偵測到的改寫紀錄」）。

可執行範例 → [docs/data-format.md](../docs/data-format.md)

## 排程

每日台北時間 **09:30** 觸發（VPS `crontab -l`，2026-08-31 查核），`flock -w 1800` 最多等 30 分鐘避免與抓取鎖衝突。

## 法律依據

- **著作權法第 9 條第 2 項**明文：「公文包括公務員職務上草擬之文告、講稿、**新聞稿**」→ 不受著作權保護。
- robots.txt 合規：每個機關在納入前都逐一親驗 robots.txt，實際 Disallow 行記錄於各 adapter 的
  `ROBOTS_VERIFIED` 欄位，並寫入每份快照的 `_meta`。被明文禁止者一律不收錄，不做例外。
- 一律不抓附件檔，只抓 HTML 正文。
- 個資揭露情況：沿用既有 `docs/sources.md`「個資揭露」章節記載（掃描範圍僅涵蓋舊 12 機關）。
  另有 2026-08-31 稽核（`docs/audit-fable-full.md` Y5 節）對新 6 機關做過唯讀個資掃描，結果：
  `tpe_clarify` 14 個行動電話、`fsc_lawnotice` 18 個 email＋1 個行動電話＋84 處聯絡人標記，
  `ftc_decision` 案由欄位含受處分自然人姓名的可能性尚未評估；身分證字號在 18 個來源全部 0 命中。
  此掃描結果尚未正式併入 `docs/sources.md`「個資揭露」章節，需另一輪任務補上。

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