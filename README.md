# public-api-timeseries

保存那些「官方不留歷史」的公開數字。

每天對一組公開端點各取一次快照，永久保存。這個 repo 只存原始回應，**不做任何分析、解讀或建議**。

- 資料授權：**CC BY 4.0**
- 程式碼授權：**MIT**（見 [LICENSE](LICENSE)）
- 資料起始日：**2026-08-26（UTC）**

## 為什麼

這些端點只回傳「現在」的值。今天變了，明天就查不到昨天的值。官方沒有歷史 API，
Internet Archive 的擷取頻率不足以還原時間序列，公開資料集平台上也沒有現成副本。

每個來源納入前都要通過三步驗證。判準與逐一查證結果見 [docs/why.md](docs/why.md)。

## 目前收錄

### `track-crypto/` — 加密貨幣與 AI 算力市場

| 來源 | 內容 | 最近一次筆數 | 狀態 |
|---|---|---|---|
| `x402_bazaar` | x402 協議全量掛牌 | 14,755 | 每日抓取 |
| `cex_symbols` | 7 家交易所交易對與狀態 | 10,744 | 每日抓取 |
| `vast_gpu` | vast.ai GPU 現貨報價 | 512 | 每日抓取 |
| `mcp_registry` | MCP 官方註冊表 | 82,612 | **2026-08-27 起停止抓取**，已抓資料保留 |

筆數為 2026-08-27（UTC）快照實測值。每日壓縮後合計約 **6.6 MB**。

### `track-gov/` — 台灣政府公告（可問責性存檔）

| 來源 | 內容 | 最近一次筆數 | 狀態 |
|---|---|---|---|
| `fsc_clarification` | 金管會 即時新聞澄清（全部歷史） | 50 | 每日抓取 |

每日壓縮後約 **42 KB**。每年約新增 5 筆。

各來源的端點、欄位、已知限制見 [docs/sources.md](docs/sources.md)。

## 資料長什麼樣

```
<track>/data/<source>/YYYY-MM-DD.json.gz    一天一檔，永不覆蓋
<track>/data/_manifest/YYYY-MM-DD.json      當日各來源成敗、大小、耗時
timestamps/SHA256SUMS-YYYY-MM-DD.txt(.ots)  OpenTimestamps 時間戳
```

檔名日期一律為 **UTC**。檔案結構、欄位、可執行的讀取範例見
[docs/data-format.md](docs/data-format.md)。

## 怎麼下載

```bash
git clone https://github.com/ianhomew/public-api-timeseries.git
```

注意：`track-crypto/data/**/*.json.gz` 目前**不入 GitHub**（體積考量，見 `.gitignore`）。
GitHub 上可取得的是 `_manifest`、`track-gov` 資料、時間戳與程式碼。
`track-crypto` 原始資料保存於 VPS，累積後再發布到資料集平台，時程見
[docs/operations.md](docs/operations.md)。

檢視已存檔的快照：

```bash
python3 scripts/explore.py                              # 總覽
python3 scripts/explore.py x402_bazaar 2026-08-27       # 預覽某日快照
python3 scripts/explore.py --diff fsc_clarification 2026-08-27 2026-08-28
```

## 抓取方式

每個來源每日僅抓取一輪，請求間隔 1 秒，附帶可識別的 User-Agent。
施工前逐一查驗 robots.txt，明確禁止者一律排除。
原子寫入、絕不覆蓋既有檔案。完整原則見 [docs/methodology.md](docs/methodology.md)。

## 變動偵測

`track-gov` 每筆含 `body_sha256`。比對相同 `dataserno` 在不同日期的 hash，
即可發現內容被改寫或下架。有變動時才留下紀錄：

```
CHANGES.md                              累積索引
changes/<source>/YYYY-MM-DD.md          當日 unified diff
```

> 截至 2026-08-27（UTC）尚未偵測到任何改寫或下架，因此上列檔案尚未產生。

`track-crypto/data/cex_events/events.jsonl` 記錄交易所上架／下架事件流，
需累積兩份以上快照才會產生。細節見 [docs/operations.md](docs/operations.md)。

## 目前狀態

| 項目 | 值（2026-08-27 UTC 查核） |
|---|---|
| 已累積天數 | 2 天 |
| 每日排程 | 09:00 / 09:30 / 11:30（**台北時間**） |
| 自我檢查 | `ALERT.md` 存在時代表偵測到異常 |
| 變動紀錄 | 尚未產生 |

## 這個專案不做什麼

- 不做網站、API 或儀表板
- 不做即時警報或推播
- 不做任何分析、解讀或評論

## 文件索引

| 文件 | 內容 |
|---|---|
| [docs/why.md](docs/why.md) | 收錄判準與三步驗證結果 |
| [docs/sources.md](docs/sources.md) | 每個來源的端點、欄位、已知限制 |
| [docs/data-format.md](docs/data-format.md) | 檔名規則、JSON 結構、讀取範例 |
| [docs/methodology.md](docs/methodology.md) | 抓取原則、robots.txt、原子寫入、時間戳 |
| [docs/revisions.md](docs/revisions.md) | 經複核被推翻或收斂的宣稱 |
| [docs/operations.md](docs/operations.md) | 排程、自我檢查、里程碑 |
| [track-crypto/README.md](track-crypto/README.md) | 軌一速覽 |
| [track-gov/README.md](track-gov/README.md) | 軌二速覽 |

## 免責

本存檔僅記錄公開端點在特定時間點的回應內容，不對資料正確性作任何保證，
不構成任何投資建議、法律意見或分析觀點。使用者應自行向原始來源查證。
