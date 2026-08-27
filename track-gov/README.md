# track-gov — 台灣政府公告每日快照（可問責性存檔）

**這是原始公告存檔，不含任何分析、解讀或評論。**

## 為什麼做這個
金管會全站「內頁」在 Internet Archive Wayback Machine 的存檔數是 **0 份**。
對照組：公平會內頁 16,518 份、中央銀行 20,344 份。
台灣金融監理的核心機關，是目前最大的公開存檔黑洞。

本專案每日對指定欄目做完整快照，保存 `sha256`，用來偵測**靜默改寫、下架、撤稿**。

## 授權與法律依據
- 資料以 **CC BY 4.0** 釋出
- **著作權法第 9 條第 2 項**明文：「公文包括公務員職務上草擬之文告、講稿、**新聞稿**」→ 不受著作權保護
- 個資風險低：裁罰受處分人多為法人；自然人姓名官方已遮罩（如「林00先生」）
- robots.txt 合規：金管會僅 `Disallow: /uploaddowndoc`，本專案未觸及

## 目前收錄
| channel | 來源 | 筆數 | 說明 |
|---|---|---|---|
| `fsc_clarification` | 金管會 即時新聞澄清（id=609） | **50**（全部歷史） | 2017-03 起。內頁 Wayback 存檔 = 0 |

全部歷史僅 50 筆，每年新增約 5 筆 → **維護成本近乎零**，這是能撐數年的關鍵。

## 資料結構
```
data/<channel>/YYYY-MM-DD.json.gz
data/_manifest/YYYY-MM-DD.json
```
每筆包含：`dataserno`、`url`、`title`、`date`、`body_text`、`body_sha256`、`raw_sha256`、`raw_bytes`

**偵測改寫的方法**：比對相同 `dataserno` 在不同日期的 `body_sha256`。

## 技術備註（踩過的坑）
- 內頁 URL **必須帶 `&dtable=News`**，否則回傳的頁面不含正文
- 分頁參數是 **`&page=N`**（`pageNum`/`currentPage` 等皆無效）
- `class="page-edit"` **是內容容器，不是頁尾**。正文結構為 `ap > maincontent > subject/date > page-edit > zbox > main-a_01 > main-a_03`
- 純靜態 HTML、無 Cloudflare、無 rate limit

## 抓取禮貌
每次請求間隔 1 秒，每日僅執行一次，附帶可識別的 User-Agent。

## 免責
本存檔僅記錄公開網頁在特定時間點的內容，**不對資料正確性作任何保證**，
**不構成任何投資建議、法律意見或分析觀點**。使用者應自行至官方網站查證。
